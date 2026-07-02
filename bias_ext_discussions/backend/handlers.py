from __future__ import annotations

from django.core.exceptions import PermissionDenied

from bias_core.extensions.platform import api_error
from bias_core.extensions.platform import log_admin_action
from bias_core.extensions.platform import ResourceQueryOptions, merge_resource_includes, parse_resource_query_options
from bias_core.extensions.platform import wants_jsonapi_response
from bias_core.extensions import ResourceEndpointDefinition
from bias_core.extensions.platform import PaginationService
from bias_ext_discussions.backend import content_posts
from bias_ext_discussions.backend.models import Discussion
from bias_ext_discussions.backend.schemas import (
    DiscussionCreateSchema,
    DiscussionOutSchema,
    DiscussionReadStateSchema,
    DiscussionUpdateSchema,
)
from bias_ext_discussions.backend.resources import attach_discussion_resource_posts
from bias_ext_discussions.backend.services import DiscussionService


DISCUSSION_LIST_BASE_FIELDS = (
    "id",
    "title",
    "slug",
    "created_at",
    "updated_at",
    "last_posted_at",
    "last_post_number",
    "comment_count",
    "participant_count",
    "view_count",
    "is_locked",
    "is_sticky",
    "is_hidden",
    "approval_status",
    "approval_note",
    "is_subscribed",
    "is_unread",
    "unread_count",
    "last_read_at",
    "last_read_post_number",
    "hidden_at",
)

ANONYMOUS_DISCUSSION_LIST_TAG_FIELDS = (
    "id",
    "name",
    "slug",
    "color",
    "icon",
)


def get_runtime_resource_registry(*args, **kwargs):
    from bias_core.extensions.runtime import get_runtime_resource_registry as runtime_get_resource_registry

    return runtime_get_resource_registry(*args, **kwargs)


def get_runtime_service(service_key: str, default=None):
    from bias_core.extensions.runtime import get_runtime_service as runtime_get_service

    return runtime_get_service(service_key, default)


def _service_method(service, name: str):
    if isinstance(service, dict):
        method = service.get(name)
    else:
        method = getattr(service, name, None)
    if not callable(method):
        raise RuntimeError(f"Discussions 扩展运行时服务缺少方法: {name}")
    return method


def has_forum_permission(user, permission_names) -> bool:
    return bool(_service_method(get_runtime_service("users.service"), "has_forum_permission")(user, permission_names))


def serialize_user(user, *, resource: str = "user_detail", context: dict | None = None):
    if not user:
        return None
    return get_resource_registry().serialize(
        str(resource or "user_detail"),
        user,
        context or {},
    )


def get_resource_registry():
    return get_runtime_resource_registry()


def serialize_discussion_payload(
    discussion,
    user=None,
    resource_options=None,
    default_includes=(),
    resource_context=None,
):
    resource_options = resource_options or ResourceQueryOptions()
    includes = merge_resource_includes(
        ("user", "last_posted_user"),
        default_includes,
        resource_options.includes,
    )
    resolved_context = {"user": user, "include": includes}
    if resource_context:
        resolved_context.update(resource_context)
    payload = DiscussionOutSchema.model_validate(discussion).model_dump()
    payload.update(
        get_resource_registry().serialize(
            "discussion",
            discussion,
            resolved_context,
            only=resource_options.fields,
            include=includes,
        )
    )
    return payload


def serialize_discussion_list_payload(
    discussion,
    user=None,
    resource_options=None,
    default_includes=(),
    resource_context=None,
):
    resource_options = resource_options or ResourceQueryOptions()
    includes = merge_resource_includes(
        ("user", "last_posted_user"),
        default_includes,
        resource_options.includes,
    )
    payload = {
        field: getattr(discussion, field)
        for field in DISCUSSION_LIST_BASE_FIELDS
        if hasattr(discussion, field)
    }
    resolved_context = {
        "user": user,
        "include": includes,
        "require_prefetched_discussion_posts": True,
        "plain_related_fields": {
            "discussion": (),
            "post": ("user",),
        },
    }
    if resource_context:
        resolved_context.update(resource_context)
    payload.update(
        get_resource_registry().serialize(
            "discussion",
            discussion,
            resolved_context,
            only=resource_options.fields,
            include=includes,
        )
    )
    return payload


def serialize_anonymous_discussion_list_payload(discussion) -> dict:
    payload = {
        field: getattr(discussion, field)
        for field in DISCUSSION_LIST_BASE_FIELDS
        if hasattr(discussion, field)
    }
    payload.update(
        {
            "user": _serialize_anonymous_discussion_user(getattr(discussion, "user", None)),
            "last_posted_user": _serialize_anonymous_discussion_user(
                getattr(discussion, "last_posted_user", None),
            ),
            "tags": _serialize_anonymous_discussion_tags(discussion),
        }
    )
    return payload


def serialize_authenticated_default_discussion_list_payload(discussion) -> dict:
    payload = serialize_anonymous_discussion_list_payload(discussion)
    payload.update(
        {
            "is_subscribed": bool(getattr(discussion, "is_subscribed", False)),
            "is_unread": bool(getattr(discussion, "is_unread", False)),
            "unread_count": int(getattr(discussion, "unread_count", 0) or 0),
            "last_read_at": getattr(discussion, "last_read_at", None),
            "last_read_post_number": int(getattr(discussion, "last_read_post_number", 0) or 0),
        }
    )
    return payload


def _serialize_anonymous_discussion_user(user) -> dict | None:
    if user is None:
        return None
    display_name = getattr(user, "display_name", "") or getattr(user, "username", "")
    return {
        "id": getattr(user, "id", None),
        "username": getattr(user, "username", ""),
        "display_name": display_name,
        "avatar_url": getattr(user, "avatar_url", None),
    }


def _serialize_anonymous_discussion_tags(discussion) -> list[dict]:
    links = _prefetched_discussion_tag_links(discussion)
    if not links:
        return []
    tags = [
        getattr(link, "tag", None)
        for link in links
        if getattr(link, "tag", None) is not None
    ]
    return [
        {
            field: getattr(tag, field, "")
            for field in ANONYMOUS_DISCUSSION_LIST_TAG_FIELDS
        }
        for tag in sorted(
            tags,
            key=lambda item: (
                getattr(item, "position", None) is None,
                getattr(item, "position", 0) or 0,
                getattr(item, "name", ""),
            ),
        )
    ]


def _prefetched_discussion_tag_links(discussion) -> list:
    prefetched = getattr(discussion, "_prefetched_objects_cache", {}) or {}
    if "discussion_tags" in prefetched:
        return list(prefetched["discussion_tags"] or [])
    return []


def apply_discussion_resource_preloads(queryset, user=None, resource_options=None, default_includes=()):
    resource_options = resource_options or ResourceQueryOptions()
    includes = merge_resource_includes(
        ("user", "last_posted_user"),
        default_includes,
        resource_options.includes,
    )
    planned = get_resource_registry().apply_preload_plan(
        queryset,
        "discussion",
        {"user": user, "include": includes},
        only=resource_options.fields,
        include=includes,
    )
    planned = _filter_invalid_discussion_prefetches(planned)
    return _dedupe_discussion_user_group_prefetches(planned, includes)


def apply_discussion_list_resource_preloads(queryset, user=None, resource_options=None, default_includes=()):
    resource_options = resource_options or ResourceQueryOptions()
    includes = merge_resource_includes(
        ("user", "last_posted_user"),
        default_includes,
        resource_options.includes,
    )
    queryset = _apply_discussion_user_resource_preloads(queryset, user=user)
    planned = get_resource_registry().apply_preload_plan(
        queryset,
        "discussion",
        {"user": user, "include": includes, "defer_discussion_post_preload": True},
        only=resource_options.fields,
        include=includes,
    )
    return _filter_invalid_discussion_prefetches(planned)


def apply_anonymous_discussion_list_preloads(queryset):
    preloads = []
    for relation in ("discussion_tags__tag",):
        try:
            queryset.model._meta.get_field(relation.split("__", 1)[0])
        except Exception:
            continue
        preloads.append(relation)
    if preloads:
        queryset = queryset.prefetch_related(*preloads)
    return queryset


def _apply_discussion_user_resource_preloads(queryset, *, user=None):
    plan = get_resource_registry().build_preload_plan("discussion_user", {"user": user})
    select_related = []
    prefetch_related = []
    for relation in ("user", "last_posted_user"):
        for item in plan.select_related:
            select_related.append(f"{relation}__{item}")
        for item in plan.prefetch_related:
            if isinstance(item, str):
                prefetch_related.append(f"{relation}__{item}")
    if select_related:
        queryset = queryset.select_related(*select_related)
    if prefetch_related:
        queryset = queryset.prefetch_related(*prefetch_related)
    return queryset


def _filter_invalid_discussion_prefetches(queryset):
    select_related = getattr(queryset.query, "select_related", None)
    if isinstance(select_related, dict):
        valid_selects = []
        for lookup in _flatten_select_related(select_related):
            first_part = str(lookup or "").split("__", 1)[0]
            if not first_part:
                continue
            try:
                queryset.model._meta.get_field(first_part)
            except Exception:
                continue
            valid_selects.append(lookup)
        if len(valid_selects) != len(_flatten_select_related(select_related)):
            queryset = queryset.select_related(None)
            if valid_selects:
                queryset = queryset.select_related(*valid_selects)

    prefetches = tuple(getattr(queryset, "_prefetch_related_lookups", ()) or ())
    if not prefetches:
        return queryset
    valid_prefetches = []
    for item in prefetches:
        lookup = getattr(item, "prefetch_through", item)
        first_part = str(lookup or "").split("__", 1)[0]
        if not first_part:
            continue
        try:
            queryset.model._meta.get_field(first_part)
        except Exception:
            continue
        valid_prefetches.append(item)
    if len(valid_prefetches) == len(prefetches):
        return queryset
    return queryset.prefetch_related(None).prefetch_related(*valid_prefetches)


def _dedupe_discussion_user_group_prefetches(queryset, includes):
    include_set = set(str(item or "").strip() for item in includes or () if str(item or "").strip())
    redundant_prefetches = set()
    if "first_post.user" in include_set:
        redundant_prefetches.add("user__user_groups")
    if "last_post.user" in include_set:
        redundant_prefetches.add("last_posted_user__user_groups")
    if not redundant_prefetches:
        return queryset

    prefetches = tuple(getattr(queryset, "_prefetch_related_lookups", ()) or ())
    if not prefetches:
        return queryset

    kept_prefetches = []
    for item in prefetches:
        lookup = str(getattr(item, "prefetch_through", item) or "")
        if lookup in redundant_prefetches:
            continue
        kept_prefetches.append(item)
    if len(kept_prefetches) == len(prefetches):
        return queryset
    return queryset.prefetch_related(None).prefetch_related(*kept_prefetches)


def _flatten_select_related(tree, prefix=""):
    output = []
    for key, value in dict(tree or {}).items():
        path = f"{prefix}__{key}" if prefix else str(key)
        output.append(path)
        if isinstance(value, dict):
            output.extend(_flatten_select_related(value, path))
    return output


def serialize_discussion_sort(definition):
    list_resource_context = {
        "_discussion_permission_results": {},
        "discussion_tag_visibility_cache": {},
    }
    return {
        "code": definition.code,
        "label": definition.label,
        "module_id": definition.module_id,
        "description": definition.description,
        "icon": definition.icon,
        "is_default": definition.is_default,
        "toolbar_visible": definition.toolbar_visible,
    }


def serialize_discussion_list_filter(definition):
    return {
        "code": definition.code,
        "label": definition.label,
        "module_id": definition.module_id,
        "description": definition.description,
        "icon": definition.icon,
        "is_default": definition.is_default,
        "requires_authenticated_user": definition.requires_authenticated_user,
        "sidebar_visible": definition.sidebar_visible,
        "route_path": definition.route_path,
    }


def discussion_resource_endpoints():
    endpoints = []

    def add(definition):
        endpoints.append(definition)

    add(
        ResourceEndpointDefinition(
            resource="discussion",
            endpoint="create",
            module_id="discussions",
            handler=dispatch_discussion_create,
            methods=("POST",),
            path="discussions/",
            absolute_path=True,
            auth_required=True,
        )
    )
    add(
        ResourceEndpointDefinition(
            resource="discussion",
            endpoint="index",
            module_id="discussions",
            handler=dispatch_discussion_index,
            methods=("GET",),
            path="discussions/",
            absolute_path=True,
            default_include=("most_relevant_post", "most_relevant_post.user"),
        )
    )
    add(
        ResourceEndpointDefinition(
            resource="discussion",
            endpoint="read-all",
            module_id="discussions",
            handler=dispatch_discussion_mark_all_read,
            methods=("POST",),
            path="discussions/read-all",
            absolute_path=True,
            auth_required=True,
        )
    )
    add(
        ResourceEndpointDefinition(
            resource="discussion",
            endpoint="read",
            module_id="discussions",
            handler=dispatch_discussion_update_read_state,
            methods=("POST",),
            path="discussions/{object_id}/read",
            absolute_path=True,
            auth_required=True,
        )
    )
    add(
        ResourceEndpointDefinition(
            resource="discussion",
            endpoint="show",
            module_id="discussions",
            handler=dispatch_discussion_show,
            methods=("GET",),
            path="discussions/{object_id}",
            absolute_path=True,
        )
    )
    add(
        ResourceEndpointDefinition(
            resource="discussion",
            endpoint="update",
            module_id="discussions",
            handler=dispatch_discussion_update,
            methods=("PATCH",),
            path="discussions/{object_id}",
            absolute_path=True,
            auth_required=True,
        )
    )
    add(
        ResourceEndpointDefinition(
            resource="discussion",
            endpoint="delete",
            module_id="discussions",
            handler=dispatch_discussion_delete,
            methods=("DELETE",),
            path="discussions/{object_id}",
            absolute_path=True,
            auth_required=True,
        )
    )
    add(
        ResourceEndpointDefinition(
            resource="discussion",
            endpoint="pin",
            module_id="discussions",
            handler=dispatch_discussion_toggle_pin,
            methods=("POST",),
            path="discussions/{object_id}/pin",
            absolute_path=True,
            auth_required=True,
        )
    )
    add(
        ResourceEndpointDefinition(
            resource="discussion",
            endpoint="lock",
            module_id="discussions",
            handler=dispatch_discussion_toggle_lock,
            methods=("POST",),
            path="discussions/{object_id}/lock",
            absolute_path=True,
            auth_required=True,
        )
    )
    add(
        ResourceEndpointDefinition(
            resource="discussion",
            endpoint="hide",
            module_id="discussions",
            handler=dispatch_discussion_toggle_hide,
            methods=("POST",),
            path="discussions/{object_id}/hide",
            absolute_path=True,
            auth_required=True,
        )
    )
    return tuple(endpoints)


def _discussion_object_id(context) -> int:
    try:
        return int(context.get("object_id") or 0)
    except (TypeError, ValueError):
        return 0


def _discussion_default_includes(context) -> tuple[str, ...]:
    return tuple(context.get("default_include") or ())


def _discussion_index_default_includes(context, q: str | None = None) -> tuple[str, ...]:
    default_includes = _discussion_default_includes(context)
    if q:
        return default_includes
    return tuple(
        item
        for item in default_includes
        if str(item or "").strip().split(".", 1)[0] != "most_relevant_post"
    )


def _discussion_payload(context) -> dict:
    payload = context.get("payload")
    return payload if isinstance(payload, dict) else {}


def _discussion_attributes(payload: dict) -> dict:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict) and isinstance(data.get("attributes"), dict):
        return dict(data["attributes"])
    return dict(payload or {})


def _discussion_query_value(context, key: str, default=None):
    return dict(context.get("query") or {}).get(key, default)


def _discussion_query_params(context) -> dict:
    return dict(context.get("query") or {})


def _discussion_list_query_params(context, *, skip_total: bool = False) -> dict:
    params = _discussion_query_params(context)
    if skip_total:
        params["__skip_total"] = True
    return params


def dispatch_discussion_create(context):
    raw_payload = _discussion_payload(context)
    payload = DiscussionCreateSchema(**_discussion_attributes(raw_payload))
    try:
        discussion = DiscussionService.create_discussion(
            title=payload.title,
            content=payload.content,
            user=context["user"],
            extension_payload=raw_payload,
        )
        return serialize_discussion_payload(
            discussion,
            user=context["user"],
            resource_options=context.get("resource_options"),
            default_includes=_discussion_default_includes(context),
        )
    except PermissionDenied as e:
        return api_error(str(e), status=403)
    except ValueError as e:
        return api_error(str(e), status=400)


def dispatch_discussion_index(context):
    request = context["request"]
    user = context.get("user")
    q = _discussion_query_value(context, "q")
    author = _discussion_query_value(context, "author")
    filter_code = _discussion_query_value(context, "filter", "all")
    sort = _discussion_query_value(context, "sort", "latest")
    page, limit = PaginationService.normalize(
        _discussion_query_value(context, "page", 1),
        _discussion_query_value(context, "limit", 20),
    )
    resource_options = context.get("resource_options") or parse_resource_query_options(request, "discussion")
    default_includes = _discussion_index_default_includes(context, q)
    anonymous_default_list = _is_anonymous_default_discussion_list_request(
        context,
        request=request,
        user=user,
        q=q,
        author=author,
        filter_code=filter_code,
        sort=sort,
        page=page,
        limit=limit,
        resource_options=resource_options,
        default_includes=default_includes,
    )
    authenticated_default_list = _is_authenticated_default_discussion_list_request(
        context,
        request=request,
        user=user,
        q=q,
        author=author,
        filter_code=filter_code,
        sort=sort,
        page=page,
        limit=limit,
        resource_options=resource_options,
        default_includes=default_includes,
    )
    lightweight_default_list = anonymous_default_list or authenticated_default_list

    discussions, total = DiscussionService.get_discussion_list(
        q=q,
        author=author,
        list_filter=filter_code,
        sort=sort,
        page=page,
        limit=limit,
        user=user,
        query_params=_discussion_list_query_params(
            context,
            skip_total=authenticated_default_list,
        ),
        preload=(
            apply_anonymous_discussion_list_preloads
            if lightweight_default_list
            else lambda queryset: apply_discussion_list_resource_preloads(
                queryset,
                user=user,
                resource_options=resource_options,
                default_includes=default_includes,
            )
        ),
    )
    if not lightweight_default_list:
        attach_discussion_resource_posts(
            discussions,
            context={
                "user": user,
                "include": merge_resource_includes(
                    ("user", "last_posted_user"),
                    default_includes,
                    resource_options.includes,
                ),
                "require_prefetched_discussion_posts": True,
            },
        )
    active_filter = DiscussionService.normalize_discussion_list_filter(filter_code)
    active_sort = DiscussionService.normalize_discussion_sort(sort)
    list_resource_context = {
        "_discussion_permission_results": {},
        "discussion_tag_visibility_cache": {},
    }
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "filter": active_filter,
        "available_filters": [
            serialize_discussion_list_filter(item)
            for item in DiscussionService.get_discussion_list_filter_catalog()
        ],
        "sort": active_sort,
        "available_sorts": [
            serialize_discussion_sort(item)
            for item in DiscussionService.get_discussion_sort_catalog()
        ],
        "data": (
            [
                serialize_anonymous_discussion_list_payload(discussion)
                for discussion in discussions
            ]
            if anonymous_default_list
            else [
                serialize_authenticated_default_discussion_list_payload(discussion)
                for discussion in discussions
            ]
            if authenticated_default_list
            else [
                serialize_discussion_list_payload(
                    discussion,
                    user=user,
                    resource_options=resource_options,
                    default_includes=default_includes,
                    resource_context=list_resource_context,
                )
                for discussion in discussions
            ]
        ),
    }


def _is_anonymous_default_discussion_list_request(
    context,
    *,
    request,
    user,
    q,
    author,
    filter_code,
    sort,
    page,
    limit,
    resource_options,
    default_includes,
) -> bool:
    if user and getattr(user, "is_authenticated", False):
        return False
    if wants_jsonapi_response(request):
        return False
    if q or author:
        return False
    if str(filter_code or "all").strip().lower() != "all":
        return False
    if str(sort or "latest").strip().lower() != "latest":
        return False
    if page != 1 or limit != 20:
        return False
    if resource_options.fields or resource_options.includes:
        return False
    if any(
        item not in {"tags", "tags.parent"}
        for item in tuple(default_includes or ())
    ):
        return False
    query_params = _discussion_query_params(context)
    allowed = {"page", "limit", "filter", "sort"}
    return all(
        str(key or "").strip() in allowed or not _has_query_value(value)
        for key, value in query_params.items()
    )


def _is_authenticated_default_discussion_list_request(
    context,
    *,
    request,
    user,
    q,
    author,
    filter_code,
    sort,
    page,
    limit,
    resource_options,
    default_includes,
) -> bool:
    if not (user and getattr(user, "is_authenticated", False)):
        return False
    if wants_jsonapi_response(request):
        return False
    if q or author:
        return False
    if str(filter_code or "all").strip().lower() not in {"my", "unread"}:
        return False
    if str(sort or "latest").strip().lower() != "latest":
        return False
    if page != 1 or limit != 20:
        return False
    if resource_options.fields or resource_options.includes:
        return False
    if any(
        item not in {"tags", "tags.parent"}
        for item in tuple(default_includes or ())
    ):
        return False
    query_params = _discussion_query_params(context)
    allowed = {"page", "limit", "filter", "sort"}
    return all(
        str(key or "").strip() in allowed or not _has_query_value(value)
        for key, value in query_params.items()
    )


def _has_query_value(value) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_has_query_value(item) for item in value)
    return bool(str(value or "").strip())


def dispatch_discussion_show(context):
    request = context["request"]
    user = context.get("user")
    try:
        discussion_id = int(context.get("object_id") or 0)
    except (TypeError, ValueError):
        return api_error("讨论不存在", status=404)

    resource_options = context.get("resource_options") or parse_resource_query_options(request, "discussion")
    default_includes = _discussion_default_includes(context)
    discussion = DiscussionService.get_discussion_by_id(
        discussion_id,
        user,
        preload=lambda queryset: apply_discussion_resource_preloads(
            queryset,
            user=user,
            resource_options=resource_options,
            default_includes=default_includes,
        ),
    )
    if not discussion:
        return api_error("讨论不存在", status=404)

    _reuse_discussion_user_group_cache_from_resource_posts(discussion)

    first_post = None
    if discussion.first_post_id:
        post = _get_prefetched_discussion_post(discussion, discussion.first_post_id)
        if post is None:
            post = content_posts.get_first_post(discussion)
        if post is not None:
            first_post = {
                "id": post.id,
                "number": post.number,
                "content": post.content,
                "content_html": content_posts.resolve_discussion_post_content_html(post),
                "user": serialize_user(post.user, resource="user_summary"),
                "created_at": post.created_at,
                "updated_at": post.updated_at,
                "approval_status": post.approval_status,
                "approval_note": post.approval_note,
            }

    resource_context = {
        "post_visibility_checked": True,
        "discussion_tag_visibility_cache": {},
        "plain_related_fields": {
            "post": ("user",),
        },
    }
    response_data = serialize_discussion_payload(
        discussion,
        user=user,
        resource_options=resource_options,
        default_includes=default_includes,
        resource_context=resource_context,
    )
    response_data["first_post"] = first_post
    return response_data


def _get_prefetched_discussion_post(discussion, post_id):
    if not post_id:
        return None
    for post in getattr(discussion, "resource_posts", None) or ():
        if getattr(post, "id", None) == post_id:
            return post
    return None


def _reuse_discussion_user_group_cache_from_resource_posts(discussion):
    posts_by_user_id = {}
    for post in getattr(discussion, "resource_posts", None) or ():
        post_user = getattr(post, "user", None)
        if post_user is not None:
            posts_by_user_id[getattr(post_user, "id", None)] = post_user

    for relation in ("user", "last_posted_user"):
        discussion_user = getattr(discussion, relation, None)
        if discussion_user is None:
            continue
        post_user = posts_by_user_id.get(getattr(discussion_user, "id", None))
        if post_user is None:
            continue
        group_cache = getattr(post_user, "_prefetched_objects_cache", {}).get("user_groups")
        if group_cache is None:
            continue
        discussion_cache = getattr(discussion_user, "_prefetched_objects_cache", None)
        if discussion_cache is None:
            discussion_cache = {}
            setattr(discussion_user, "_prefetched_objects_cache", discussion_cache)
        discussion_cache.setdefault("user_groups", group_cache)


def dispatch_discussion_mark_all_read(context):
    marked_at = DiscussionService.mark_all_as_read(context["user"])
    return {
        "message": "已全部标记为已读",
        "marked_all_as_read_at": marked_at,
    }


def dispatch_discussion_update_read_state(context):
    discussion_id = _discussion_object_id(context)
    payload = DiscussionReadStateSchema(**_discussion_payload(context))
    try:
        state = DiscussionService.update_read_state(
            discussion_id=discussion_id,
            user=context["user"],
            last_read_post_number=payload.last_read_post_number,
        )
        return {
            "message": "阅读状态已更新",
            "last_read_at": state.last_read_at,
            "last_read_post_number": state.last_read_post_number,
        }
    except Discussion.DoesNotExist:
        return api_error("讨论不存在", status=404)
    except PermissionDenied as e:
        return api_error(str(e), status=403)


def dispatch_discussion_update(context):
    discussion_id = _discussion_object_id(context)
    raw_payload = _discussion_payload(context)
    payload = DiscussionUpdateSchema(**_discussion_attributes(raw_payload))
    try:
        discussion = DiscussionService.update_discussion(
            discussion_id=discussion_id,
            user=context["user"],
            title=payload.title,
            content=payload.content,
            extension_payload=raw_payload,
            is_locked=payload.is_locked,
            is_sticky=payload.is_sticky,
            is_hidden=payload.is_hidden,
        )
        return serialize_discussion_payload(
            discussion,
            user=context["user"],
            resource_options=context.get("resource_options"),
            default_includes=_discussion_default_includes(context),
        )
    except Discussion.DoesNotExist:
        return api_error("讨论不存在", status=404)
    except PermissionDenied as e:
        return api_error(str(e), status=403)
    except ValueError as e:
        return api_error(str(e), status=400)


def dispatch_discussion_delete(context):
    request = context["request"]
    user = context["user"]
    discussion_id = _discussion_object_id(context)
    try:
        discussion = Discussion.objects.select_related("user").get(id=discussion_id)
        snapshot = {
            "title": discussion.title,
            "author_id": discussion.user_id,
            "deleted_by_owner": discussion.user_id == user.id,
        }
        DiscussionService.delete_discussion(discussion_id, user)
        if user.is_staff or not snapshot["deleted_by_owner"]:
            log_admin_action(
                request,
                "admin.discussion.delete",
                target_type="discussion",
                target_id=discussion_id,
                data=snapshot,
            )
        return {"message": "讨论已删除"}
    except Discussion.DoesNotExist:
        return api_error("讨论不存在", status=404)
    except PermissionDenied as e:
        return api_error(str(e), status=403)


def dispatch_discussion_toggle_pin(context):
    request = context["request"]
    user = context["user"]
    discussion_id = _discussion_object_id(context)

    try:
        discussion = Discussion.objects.get(id=discussion_id)
        DiscussionService.set_sticky_state(discussion, user, not discussion.is_sticky)
        discussion.refresh_from_db()
        log_admin_action(
            request,
            "admin.discussion.sticky" if discussion.is_sticky else "admin.discussion.unsticky",
            target_type="discussion",
            target_id=discussion.id,
            data={"title": discussion.title, "is_sticky": discussion.is_sticky},
        )
        return {"message": "操作成功", "is_sticky": discussion.is_sticky}
    except Discussion.DoesNotExist:
        return api_error("讨论不存在", status=404)
    except PermissionDenied as e:
        return api_error(str(e), status=403)


def dispatch_discussion_toggle_lock(context):
    request = context["request"]
    user = context["user"]
    discussion_id = _discussion_object_id(context)

    try:
        discussion = Discussion.objects.get(id=discussion_id)
        DiscussionService.set_locked_state(discussion, user, not discussion.is_locked)
        discussion.refresh_from_db()
        log_admin_action(
            request,
            "admin.discussion.lock" if discussion.is_locked else "admin.discussion.unlock",
            target_type="discussion",
            target_id=discussion.id,
            data={"title": discussion.title, "is_locked": discussion.is_locked},
        )
        return {"message": "操作成功", "is_locked": discussion.is_locked}
    except Discussion.DoesNotExist:
        return api_error("讨论不存在", status=404)
    except PermissionDenied as e:
        return api_error(str(e), status=403)


def dispatch_discussion_toggle_hide(context):
    request = context["request"]
    user = context["user"]
    discussion_id = _discussion_object_id(context)

    try:
        discussion = Discussion.objects.get(id=discussion_id)
        next_hidden = not discussion.is_hidden
        DiscussionService.set_hidden_state(discussion, user, next_hidden)
        discussion.refresh_from_db()
        if has_forum_permission(user, "discussion.hide"):
            log_admin_action(
                request,
                "admin.discussion.hide" if discussion.is_hidden else "admin.discussion.restore",
                target_type="discussion",
                target_id=discussion.id,
                data={"title": discussion.title, "is_hidden": discussion.is_hidden},
            )
        return {"message": "操作成功", "is_hidden": discussion.is_hidden}
    except Discussion.DoesNotExist:
        return api_error("讨论不存在", status=404)
    except PermissionDenied as e:
        return api_error(str(e), status=403)

