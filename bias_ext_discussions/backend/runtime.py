from __future__ import annotations

def discussion_service_provider() -> dict:
    from bias_ext_discussions.backend.models import Discussion, DiscussionUser
    from bias_ext_discussions.backend.services import DiscussionService

    return {
        "model": Discussion,
        "state_model": DiscussionUser,
        "approval_approved": Discussion.APPROVAL_APPROVED,
        "event_types": discussion_event_type_aliases(),
        "create": DiscussionService.create_discussion,
        "update": DiscussionService.update_discussion,
        "delete": DiscussionService.delete_discussion,
        "set_hidden_state": DiscussionService.set_hidden_state,
        "list": DiscussionService.get_discussion_list,
        "get_visible_ids": _get_visible_discussion_ids,
        "has_visibility": _has_discussion_visibility,
        "approve": DiscussionService.approve_discussion,
        "reject": DiscussionService.reject_discussion,
        "list_approval_queue": _list_approval_queue,
        "count_pending_approvals": _count_pending_approvals,
        "pending_first_post_ids": _pending_first_post_ids,
        "process_approval": _process_approval,
        "can_edit": DiscussionService.can_edit_discussion,
        "can_delete": DiscussionService.can_delete_discussion,
        "can_reply": DiscussionService.can_reply_discussion,
        "validate_replyable": _validate_replyable,
        "lock_for_post_number": _lock_for_post_number,
        "apply_counted_filter": _apply_counted_filter,
        "refresh_approved_stats": _refresh_approved_stats,
        "reply_notification_context": _reply_notification_context,
        "is_subscribed": _is_subscribed,
        "set_subscription": DiscussionService.set_subscription,
        "follow_if_enabled": DiscussionService.follow_discussion,
        "mark_read": _mark_read,
        "clamp_read_states": DiscussionService.clamp_read_states,
    }


def discussion_event_type_aliases() -> dict[str, type]:
    from bias_ext_discussions.backend.events import (
        DiscussionApprovedEvent,
        DiscussionCreatedEvent,
        DiscussionHiddenEvent,
        DiscussionLockedEvent,
        DiscussionRejectedEvent,
        DiscussionRenamedEvent,
        DiscussionResubmittedEvent,
        DiscussionStickyChangedEvent,
        DiscussionUserReadEvent,
    )

    return {
        "discussions.discussion.created": DiscussionCreatedEvent,
        "discussions.discussion.approved": DiscussionApprovedEvent,
        "discussions.discussion.renamed": DiscussionRenamedEvent,
        "discussions.discussion.locked": DiscussionLockedEvent,
        "discussions.discussion.sticky_changed": DiscussionStickyChangedEvent,
        "discussions.discussion.hidden": DiscussionHiddenEvent,
        "discussions.discussion.rejected": DiscussionRejectedEvent,
        "discussions.discussion.resubmitted": DiscussionResubmittedEvent,
        "discussions.discussion.user_read": DiscussionUserReadEvent,
    }


discussion_service_provider.event_types = discussion_event_type_aliases


def discussion_timeline_provider() -> dict:
    return {
        "create_from_builder": create_timeline_from_builder,
    }


def _list_approval_queue() -> list[dict]:
    from bias_ext_discussions.backend.models import Discussion

    discussions = Discussion.objects.filter(
        approval_status=Discussion.APPROVAL_PENDING,
    ).select_related("user").order_by("-created_at")
    return [_serialize_approval_item(discussion) for discussion in discussions]


def _count_pending_approvals() -> int:
    from bias_ext_discussions.backend.models import Discussion

    return Discussion.objects.filter(approval_status=Discussion.APPROVAL_PENDING).count()


def _pending_first_post_ids() -> list[int]:
    from bias_ext_discussions.backend.models import Discussion

    return list(
        Discussion.objects.filter(approval_status=Discussion.APPROVAL_PENDING)
        .exclude(first_post_id__isnull=True)
        .values_list("first_post_id", flat=True)
    )


def _get_visible_discussion_ids(user=None, *, ability: str = "view", context: dict | None = None):
    from bias_core.extensions.platform import apply_model_visibility_scope
    from bias_ext_discussions.backend.models import Discussion

    resolved_context = dict(context or {})
    return apply_model_visibility_scope(
        Discussion,
        Discussion.objects.all(),
        user=user,
        ability=str(ability or "view"),
        context=resolved_context,
    ).values("id")


def _has_discussion_visibility(*, ability: str | None = None) -> bool:
    from bias_core.extensions.runtime import has_runtime_model_visibility
    from bias_ext_discussions.backend.models import Discussion

    return has_runtime_model_visibility(Discussion, ability=ability)


def _process_approval(*, content_id: int, action: str, actor, note: str = "") -> dict:
    from django.core.exceptions import ValidationError
    from django.shortcuts import get_object_or_404
    from bias_ext_discussions.backend.models import Discussion
    from bias_ext_discussions.backend.services import DiscussionService

    discussion = get_object_or_404(
        Discussion.objects.select_related("user"),
        id=content_id,
        approval_status=Discussion.APPROVAL_PENDING,
    )
    if action == "approve":
        processed = DiscussionService.approve_discussion(discussion, actor, note=note)
    elif action == "reject":
        processed = DiscussionService.reject_discussion(discussion, actor, note=note)
    else:
        raise ValidationError("无效的审核动作")
    return _serialize_approval_item(processed)


def _serialize_approval_item(discussion) -> dict:
    from bias_core.extensions.runtime import get_runtime_first_post

    first_post = get_runtime_first_post(discussion)
    return {
        "type": "discussion",
        "id": discussion.id,
        "title": discussion.title,
        "content": first_post.content if first_post else "",
        "created_at": discussion.created_at,
        "approval_status": discussion.approval_status,
        "approval_note": discussion.approval_note,
        "author": _serialize_user(getattr(discussion, "user", None)),
        "discussion": {
            "id": discussion.id,
            "title": discussion.title,
        },
        "post": {
            "id": first_post.id,
            "number": first_post.number,
        } if first_post else None,
    }


def _serialize_user(user) -> dict | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    }


def _validate_replyable(discussion_id: int, user, *, discussion=None):
    from django.core.exceptions import PermissionDenied
    from bias_core.extensions.runtime import evaluate_runtime_model_policy
    from bias_ext_discussions.backend.models import Discussion

    if discussion is None:
        try:
            discussion = Discussion.objects.get(id=discussion_id)
        except Discussion.DoesNotExist:
            raise ValueError("讨论不存在")

    if discussion.approval_status != Discussion.APPROVAL_APPROVED and not getattr(user, "is_staff", False):
        raise ValueError("讨论正在审核中，暂时无法回复")

    if discussion.is_locked and not getattr(user, "is_staff", False):
        raise ValueError("讨论已锁定，无法回复")

    if evaluate_runtime_model_policy(
        "reply",
        user=user,
        model=discussion,
        default=True,
        discussion=discussion,
    ) is False:
        raise PermissionDenied("没有权限回复此讨论")
    return discussion


def _lock_for_post_number(discussion_id: int):
    from bias_ext_discussions.backend.models import Discussion

    return Discussion.objects.select_for_update().get(id=discussion_id)


def _apply_counted_filter(queryset, *, prefix: str = ""):
    from bias_ext_discussions.backend.models import Discussion

    normalized_prefix = str(prefix or "").strip()
    field_prefix = f"{normalized_prefix}__" if normalized_prefix else ""
    return queryset.filter(
        **{
            f"{field_prefix}hidden_at__isnull": True,
            f"{field_prefix}approval_status": Discussion.APPROVAL_APPROVED,
        }
    )


def _refresh_approved_stats(discussion, *, discussion_counted_post_types):
    from bias_core.extensions.runtime import get_runtime_approved_discussion_post_stats

    stats = get_runtime_approved_discussion_post_stats(
        discussion,
        discussion_counted_post_types=discussion_counted_post_types,
    )
    discussion.comment_count = int(stats.get("comment_count") or 0)
    discussion.participant_count = int(stats.get("participant_count") or 0)
    discussion.last_post_id = stats.get("last_post_id")
    discussion.last_post_number = stats.get("last_post_number")
    discussion.last_posted_at = stats.get("last_posted_at")
    discussion.last_posted_user = stats.get("last_posted_user")

    discussion.save(update_fields=[
        "comment_count",
        "participant_count",
        "last_post_id",
        "last_post_number",
        "last_posted_at",
        "last_posted_user",
    ])
    return discussion


def _reply_notification_context(discussion_id: int, post_id: int, from_user):
    from bias_core.extensions.runtime import get_runtime_discussion_post_number
    from bias_ext_discussions.backend.models import Discussion, DiscussionUser

    try:
        discussion = Discussion.objects.select_related("user").get(id=discussion_id)
    except Discussion.DoesNotExist:
        return None
    post_number = get_runtime_discussion_post_number(post_id)
    if post_number is None:
        return None

    author = discussion.user
    excluded_user_ids = {getattr(from_user, "id", None), getattr(author, "id", None)}
    excluded_user_ids = {int(item) for item in excluded_user_ids if item}
    subscribers = [
        state.user
        for state in DiscussionUser.objects.filter(
            discussion_id=discussion_id,
            is_subscribed=True,
        ).select_related("user")
        if state.user_id not in excluded_user_ids
    ]

    return {
        "discussion": discussion,
        "discussion_author": author,
        "subscribers": subscribers,
        "payload": {
            "discussion_id": discussion_id,
            "discussion_title": discussion.title,
            "post_id": post_id,
            "post_number": post_number,
        },
    }


def _is_subscribed(discussion, user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False

    from bias_ext_discussions.backend.models import DiscussionUser

    return DiscussionUser.objects.filter(
        discussion=discussion,
        user=user,
        is_subscribed=True,
    ).exists()


def _mark_read(
    *,
    discussion_id: int,
    user,
    last_read_post_number: int,
    subscribed: bool | None = None,
    require_view: bool = True,
) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False

    from bias_ext_discussions.backend.services import DiscussionService

    state = DiscussionService.update_read_state(
        int(discussion_id),
        user,
        int(last_read_post_number or 0),
        require_view=require_view,
    )
    if subscribed is not None and state.is_subscribed != bool(subscribed):
        state.is_subscribed = bool(subscribed)
        state.save(update_fields=["is_subscribed"])
    return True


def create_timeline_from_builder(
    event,
    builder: str,
    *,
    extra: dict | None = None,
    update_discussion_last_post: bool | None = None,
):
    from bias_ext_discussions.backend import timeline

    builders = {
        "discussion_renamed": timeline.build_discussion_renamed_content,
        "discussion_tagged": timeline.build_discussion_tagged_content,
        "discussion_locked": timeline.build_discussion_locked_content,
        "discussion_sticky": timeline.build_discussion_sticky_content,
        "discussion_hidden": timeline.build_discussion_hidden_content,
        "discussion_review": timeline.build_discussion_review_content,
        "discussion_resubmitted": timeline.build_discussion_resubmitted_content,
        "post_review": timeline.build_post_review_content,
        "post_resubmitted": timeline.build_post_resubmitted_content,
        "post_hidden": timeline.build_post_hidden_content,
    }
    build_content = builders.get(str(builder or "").strip())
    if build_content is None:
        raise RuntimeError(f"讨论时间线构建器未注册: {builder}")

    context = timeline.make_timeline_context(event, **dict(extra or {}))
    return timeline.create_timeline_from_builder(
        context,
        build_content,
        update_discussion_last_post=update_discussion_last_post,
    )

