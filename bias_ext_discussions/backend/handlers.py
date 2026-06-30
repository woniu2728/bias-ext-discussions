from __future__ import annotations

from django.core.exceptions import PermissionDenied

from bias_core.extensions.platform import api_error
from bias_core.extensions.platform import log_admin_action
from bias_core.extensions.platform import ResourceQueryOptions, merge_resource_includes, parse_resource_query_options
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


def get_runtime_resource_registry(*args, **kwargs):
    from bias_core.extensions.runtime import get_runtime_resource_registry as runtime_get_resource_registry

    return runtime_get_resource_registry(*args, **kwargs)


def has_runtime_forum_permission(*args, **kwargs):
    from bias_core.extensions.runtime import has_runtime_forum_permission as runtime_has_forum_permission

    return runtime_has_forum_permission(*args, **kwargs)


def serialize_runtime_user(*args, **kwargs):
    from bias_core.extensions.runtime import serialize_runtime_user as runtime_serialize_user

    return runtime_serialize_user(*args, **kwargs)


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


def serialize_discussion_list_payload(discussion, user=None, resource_options=None, default_includes=()):
    resource_options = resource_options or ResourceQueryOptions()
    includes = merge_resource_includes(
        ("user", "last_posted_user"),
        default_includes,
        resource_options.includes,
    )
    payload = DiscussionOutSchema.model_validate(discussion).model_dump()
    payload.update(
        get_resource_registry().serialize(
            "discussion",
            discussion,
            {
                "user": user,
                "include": includes,
                "require_prefetched_discussion_posts": True,
                "plain_related_fields": {
                    "post": ("user",),
                },
            },
            only=resource_options.fields,
            include=includes,
        )
    )
    return payload


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
    default_includes = _discussion_default_includes(context)

    discussions, total = DiscussionService.get_discussion_list(
        q=q,
        author=author,
        list_filter=filter_code,
        sort=sort,
        page=page,
        limit=limit,
        user=user,
        query_params=_discussion_query_params(context),
        preload=lambda queryset: apply_discussion_list_resource_preloads(
            queryset,
            user=user,
            resource_options=resource_options,
            default_includes=default_includes,
        ),
    )
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
        "data": [
            serialize_discussion_list_payload(
                discussion,
                user=user,
                resource_options=resource_options,
                default_includes=default_includes,
            )
            for discussion in discussions
        ],
    }


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
                "user": serialize_runtime_user(post.user, resource="user_summary"),
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
        if has_runtime_forum_permission(user, "discussion.hide"):
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

