from __future__ import annotations

from django.db.models import Prefetch

from bias_core.extensions import ResourceDefinition, ResourceFieldDefinition, ResourceRelationshipDefinition


def discussion_resource_definitions():
    return (
        ResourceDefinition(
            resource="search_discussion",
            module_id="discussions",
            resolver=serialize_search_discussion_base,
            description="搜索讨论结果资源。",
        ),
    )


def discussion_resource_field_definitions():
    return (
        ResourceFieldDefinition(
            resource="discussion",
            field="can_edit",
            module_id="discussions",
            resolver=resolve_discussion_can_edit,
            description="当前用户是否可以编辑讨论。",
        ),
        ResourceFieldDefinition(
            resource="discussion",
            field="can_delete",
            module_id="discussions",
            resolver=resolve_discussion_can_delete,
            description="当前用户是否可以删除讨论。",
        ),
        ResourceFieldDefinition(
            resource="discussion",
            field="can_reply",
            module_id="discussions",
            resolver=resolve_discussion_can_reply,
            description="当前用户是否可以回复讨论。",
        ),
        ResourceFieldDefinition(
            resource="discussion",
            field="can_rename",
            module_id="discussions",
            resolver=resolve_discussion_can_rename,
            description="当前用户是否可以修改讨论标题。",
        ),
        ResourceFieldDefinition(
            resource="discussion",
            field="can_hide",
            module_id="discussions",
            resolver=resolve_discussion_can_hide,
            description="当前用户是否可以隐藏或恢复讨论。",
        ),
    )


def discussion_resource_relationship_definitions():
    return (
        ResourceRelationshipDefinition(
            resource="discussion",
            relationship="first_post",
            module_id="discussions",
            resolver=resolve_discussion_first_post,
            description="讨论首帖资源。",
            resource_type="post",
            preload_resolver=discussion_post_preload_resolver,
        ),
        ResourceRelationshipDefinition(
            resource="discussion",
            relationship="last_post",
            module_id="discussions",
            resolver=resolve_discussion_last_post,
            description="讨论最后一条帖子资源。",
            resource_type="post",
            preload_resolver=discussion_post_preload_resolver,
        ),
        ResourceRelationshipDefinition(
            resource="discussion",
            relationship="most_relevant_post",
            module_id="discussions",
            resolver=resolve_discussion_most_relevant_post,
            description="讨论列表搜索最相关帖子资源。",
            resource_type="post",
            preload_resolver=discussion_post_preload_resolver,
        ),
    )


def admin_stats_resource_field_definitions():
    return (
        ResourceFieldDefinition(
            resource="admin_stats",
            field="totalDiscussions",
            module_id="discussions",
            resolver=resolve_admin_total_discussions,
            description="后台统计中的讨论总数。",
        ),
    )


def resolve_admin_total_discussions(stats, context: dict) -> int:
    from bias_ext_discussions.backend.models import Discussion

    return Discussion.objects.count()


def serialize_search_discussion_base(discussion, context: dict) -> dict:
    return {
        "id": discussion.id,
        "title": discussion.title,
        "slug": discussion.slug,
        "comment_count": discussion.comment_count,
        "view_count": discussion.view_count,
        "is_sticky": discussion.is_sticky,
        "is_locked": discussion.is_locked,
        "created_at": discussion.created_at,
        "last_posted_at": discussion.last_posted_at,
        "excerpt": discussion.excerpt,
    }


def resolve_discussion_can_edit(discussion, context: dict) -> bool:
    from bias_ext_discussions.backend.services import DiscussionService

    user = context.get("user")
    return bool(user and DiscussionService.can_edit_discussion(discussion, user))


def resolve_discussion_can_delete(discussion, context: dict) -> bool:
    from bias_ext_discussions.backend.services import DiscussionService

    user = context.get("user")
    return bool(user and DiscussionService.can_delete_discussion(discussion, user))


def resolve_discussion_can_reply(discussion, context: dict) -> bool:
    from bias_ext_discussions.backend.services import DiscussionService

    user = context.get("user")
    return bool(user and DiscussionService.can_reply_discussion(discussion, user))


def resolve_discussion_can_rename(discussion, context: dict) -> bool:
    from bias_ext_discussions.backend.services import DiscussionService

    user = context.get("user")
    return bool(user and DiscussionService.can_rename_discussion(discussion, user))


def resolve_discussion_can_hide(discussion, context: dict) -> bool:
    from bias_ext_discussions.backend.services import DiscussionService

    user = context.get("user")
    return bool(user and DiscussionService.can_hide_discussion(discussion, user))


def discussion_post_preload_resolver(context: dict):
    Post = _runtime_post_model()
    if Post is None:
        return (), ()
    if context.get("defer_discussion_post_preload"):
        return (), ()
    nested_includes = _discussion_post_nested_includes(context)
    select_related = ["discussion"]
    prefetch_related = []
    if "user" in nested_includes:
        select_related.append("user")
        prefetch_related.append("user__user_groups")
    if "edited_user" in nested_includes:
        select_related.append("edited_user")
        prefetch_related.append("edited_user__user_groups")
    post_queryset = Post.objects.select_related(*select_related).filter(
        _discussion_post_include_filter(context),
    )
    if prefetch_related:
        post_queryset = post_queryset.prefetch_related(*prefetch_related)
    return (), (
        Prefetch("posts", queryset=post_queryset, to_attr="resource_posts"),
    )


def attach_discussion_resource_posts(discussions, *, context: dict | None = None):
    Post = _runtime_post_model()
    if Post is None:
        return
    resolved_context = context or {}
    includes = _discussion_post_includes(resolved_context)
    if not includes:
        return
    post_ids: set[int] = set()
    for discussion in discussions:
        if "first_post" in includes:
            post_ids.add(getattr(discussion, "first_post_id", None) or 0)
        if "last_post" in includes:
            post_ids.add(getattr(discussion, "last_post_id", None) or 0)
        if "most_relevant_post" in includes:
            post_ids.add(
                getattr(discussion, "most_relevant_post_id", None)
                or getattr(discussion, "first_post_id", None)
                or 0
            )
    post_ids.discard(0)
    if not post_ids:
        return

    nested_includes = _discussion_post_nested_includes(resolved_context)
    select_related = ["discussion"]
    prefetch_related = []
    if "user" in nested_includes:
        select_related.append("user")
        prefetch_related.append("user__user_groups")
    if "edited_user" in nested_includes:
        select_related.append("edited_user")
        prefetch_related.append("edited_user__user_groups")

    post_queryset = Post.objects.filter(id__in=post_ids).select_related(*select_related)
    if prefetch_related:
        post_queryset = post_queryset.prefetch_related(*prefetch_related)
    posts_by_id = {post.id: post for post in post_queryset}

    for discussion in discussions:
        resource_posts = []
        for post_id in (
            getattr(discussion, "first_post_id", None),
            getattr(discussion, "last_post_id", None),
            getattr(discussion, "most_relevant_post_id", None),
        ):
            post = posts_by_id.get(post_id)
            if post is not None and post not in resource_posts:
                resource_posts.append(post)
        fallback_post = posts_by_id.get(getattr(discussion, "first_post_id", None))
        if fallback_post is not None and fallback_post not in resource_posts:
            resource_posts.append(fallback_post)
        setattr(discussion, "resource_posts", resource_posts)


def resolve_discussion_first_post(discussion, context: dict):
    return _resolve_discussion_post_by_id(discussion, getattr(discussion, "first_post_id", None))


def resolve_discussion_last_post(discussion, context: dict):
    return _resolve_discussion_post_by_id(discussion, getattr(discussion, "last_post_id", None))


def resolve_discussion_most_relevant_post(discussion, context: dict):
    post_id = getattr(discussion, "most_relevant_post_id", None)
    if not post_id:
        post_id = getattr(discussion, "first_post_id", None)
    return _resolve_discussion_post_by_id(
        discussion,
        post_id,
        allow_query=not context.get("require_prefetched_discussion_posts"),
    )


def _resolve_discussion_post_by_id(discussion, post_id: int | None, *, allow_query: bool = True):
    if not post_id:
        return None
    prefetched_posts = getattr(discussion, "resource_posts", None)
    if prefetched_posts is not None:
        for post in prefetched_posts:
            if getattr(post, "id", None) == post_id:
                return post
        return None
    if not allow_query:
        return None
    Post = _runtime_post_model()
    if Post is None:
        return None
    return Post.objects.select_related("user", "edited_user", "discussion").filter(id=post_id).first()


def _runtime_post_model():
    from bias_ext_discussions.backend import content_posts

    return content_posts.get_post_model_or_none()


def _discussion_post_nested_includes(context: dict) -> set[str]:
    includes = tuple(context.get("include") or ())
    output: set[str] = set()
    for item in includes:
        normalized = str(item or "").strip()
        if not normalized:
            continue
        for prefix in ("first_post.", "last_post.", "most_relevant_post."):
            if normalized.startswith(prefix):
                nested = normalized.removeprefix(prefix).split(".", 1)[0].strip()
                if nested:
                    output.add(nested)
    return output


def _discussion_post_includes(context: dict) -> set[str]:
    return set(
        str(item or "").strip().split(".", 1)[0]
        for item in context.get("include") or ()
        if str(item or "").strip()
    )


def _discussion_post_include_filter(context: dict):
    from django.db.models import F, Q

    includes = _discussion_post_includes(context)
    post_filter = Q(pk__isnull=True)
    if "first_post" in includes:
        post_filter |= Q(id=F("discussion__first_post_id"))
    if "last_post" in includes:
        post_filter |= Q(id=F("discussion__last_post_id"))
    if "most_relevant_post" in includes:
        post_filter |= Q(id=F("discussion__first_post_id"))
    return post_filter

