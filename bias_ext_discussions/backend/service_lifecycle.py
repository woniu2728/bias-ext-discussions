from typing import Optional

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from bias_core.extensions.platform import dispatch_forum_event_after_commit
from bias_ext_discussions.backend.events import (
    DiscussionApprovedEvent,
    DiscussionCreatedEvent,
    DiscussionHiddenEvent,
    DiscussionLockedEvent,
    DiscussionRejectedEvent,
    DiscussionRenamedEvent,
    DiscussionResubmittedEvent,
    DiscussionStickyChangedEvent,
)
from bias_ext_discussions.backend import content_posts
from bias_ext_discussions.backend.models import Discussion, DiscussionUser


def get_runtime_discussion_lifecycle_service(*args, **kwargs):
    from bias_core.extensions.runtime import get_runtime_discussion_lifecycle_service as runtime_get_discussion_lifecycle_service

    return runtime_get_discussion_lifecycle_service(*args, **kwargs)


def get_runtime_resource_registry(*args, **kwargs):
    from bias_core.extensions.runtime import get_runtime_resource_registry as runtime_get_resource_registry

    return runtime_get_resource_registry(*args, **kwargs)


def refresh_runtime_model_private(*args, **kwargs):
    from bias_core.extensions.runtime import refresh_runtime_model_private as runtime_refresh_model_private

    return runtime_refresh_model_private(*args, **kwargs)


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


def apply_user_comment_count_deltas(*args, **kwargs):
    return _service_method(get_runtime_service("users.service"), "apply_comment_count_deltas")(*args, **kwargs)


def ensure_forum_permission(*args, **kwargs):
    return _service_method(get_runtime_service("users.service"), "ensure_forum_permission")(*args, **kwargs)


def has_forum_permission(user, permission_names) -> bool:
    return bool(_service_method(get_runtime_service("users.service"), "has_forum_permission")(user, permission_names))


def ensure_user_email_confirmed(*args, **kwargs):
    return _service_method(get_runtime_service("users.service"), "ensure_email_confirmed")(*args, **kwargs)


def ensure_user_not_suspended(*args, **kwargs):
    return _service_method(get_runtime_service("users.service"), "ensure_not_suspended")(*args, **kwargs)


def increment_user_discussion_count(*args, **kwargs):
    return _service_method(get_runtime_service("users.service"), "increment_discussion_count")(*args, **kwargs)


def requires_content_approval(*args, **kwargs):
    return _service_method(get_runtime_service("users.service"), "requires_content_approval")(*args, **kwargs)


def _prepare_discussion_create_extensions(discussion_lifecycle, *, user, payload: dict) -> dict:
    if discussion_lifecycle is None:
        return {}
    return discussion_lifecycle.prepare_create(user=user, payload=payload)


def _apply_discussion_create_extensions(discussion_lifecycle, *, discussion, states: dict, context: dict) -> dict:
    if discussion_lifecycle is None:
        return {}
    return discussion_lifecycle.apply_create(discussion=discussion, states=states, context=context)


def _prepare_discussion_update_extensions(discussion_lifecycle, *, discussion, user, payload: dict) -> dict:
    if discussion_lifecycle is None:
        return {}
    return discussion_lifecycle.prepare_update(discussion=discussion, user=user, payload=payload)


def _apply_discussion_update_extensions(discussion_lifecycle, *, discussion, states: dict, context: dict) -> dict:
    if discussion_lifecycle is None:
        return {}
    return discussion_lifecycle.apply_update(discussion=discussion, states=states, context=context)


def _prepare_discussion_delete_extensions(discussion_lifecycle, *, discussion, user, context: dict) -> dict:
    if discussion_lifecycle is None:
        return {}
    return discussion_lifecycle.prepare_delete(discussion=discussion, user=user, context=context)


def _apply_discussion_delete_extensions(discussion_lifecycle, *, states: dict, context: dict) -> dict:
    if discussion_lifecycle is None:
        return {}
    return discussion_lifecycle.apply_delete(states=states, context=context)


def _apply_discussion_hidden_extensions(discussion_lifecycle, *, discussion, context: dict) -> dict:
    if discussion_lifecycle is None:
        return {}
    return discussion_lifecycle.apply_hidden(discussion=discussion, context=context)


def _apply_discussion_approved_extensions(discussion_lifecycle, *, discussion, context: dict) -> dict:
    if discussion_lifecycle is None:
        return {}
    return discussion_lifecycle.apply_approved(discussion=discussion, context=context)


def _apply_discussion_rejected_extensions(discussion_lifecycle, *, discussion, context: dict) -> dict:
    if discussion_lifecycle is None:
        return {}
    return discussion_lifecycle.apply_rejected(discussion=discussion, context=context)


def _apply_post_created_extensions(post, *, context: dict) -> dict:
    post_lifecycle = content_posts.get_post_lifecycle_service()
    if post_lifecycle is None:
        return {}
    return post_lifecycle.apply_created(post=post, context=context)


def _apply_post_updated_extensions(post, *, context: dict) -> dict:
    post_lifecycle = content_posts.get_post_lifecycle_service()
    if post_lifecycle is None:
        return {}
    return post_lifecycle.apply_updated(post=post, context=context)


def _apply_post_approved_extensions(post, *, context: dict) -> dict:
    post_lifecycle = content_posts.get_post_lifecycle_service()
    if post_lifecycle is None:
        return {}
    return post_lifecycle.apply_approved(post=post, context=context)


def _apply_post_deleted_extensions(*, context: dict) -> dict:
    post_lifecycle = content_posts.get_post_lifecycle_service()
    if post_lifecycle is None:
        return {}
    return post_lifecycle.apply_deleted(context=context)


def _apply_discussion_resource_relationships(
    discussion: Discussion,
    *,
    payload: dict,
    user,
    creating: bool,
    actor_user_id: int,
) -> dict:
    context = {
        "user": user,
        "actor_user_id": actor_user_id,
    }
    registry = get_runtime_resource_registry()
    relationship_payload = _discussion_relationship_payload(payload)
    registry.validate_required_resource_payload(
        "discussion",
        discussion,
        {},
        {**context, "payload": relationship_payload},
        creating=creating,
    )
    if not relationship_payload:
        return context
    context["payload"] = relationship_payload
    registry.apply_resource_payload(
        "discussion",
        discussion,
        {},
        context,
        creating=creating,
    )
    return context


def _discussion_relationship_payload(payload: dict) -> dict:
    payload = dict(payload or {})
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("relationships"), dict):
        return {"data": {"relationships": dict(data["relationships"])}}
    return {}


def _refresh_discussion_private_state(discussion: Discussion, *, first_post=None) -> None:
    refresh_runtime_model_private(discussion)
    if first_post is not None:
        first_post.is_private = discussion.is_private or refresh_runtime_model_private(first_post)


def create_discussion(
    title: str,
    content: str,
    user,
    *,
    extension_payload: Optional[dict] = None,
    default_post_type,
    render_markdown_cb,
) -> Discussion:
    ensure_user_not_suspended(user, "发布讨论")
    ensure_user_email_confirmed(user, "发布讨论")
    ensure_forum_permission(user, "startDiscussion", "没有权限发起讨论")
    requires_approval = requires_content_approval(user, "startDiscussionWithoutApproval")
    approval_status = Discussion.APPROVAL_PENDING if requires_approval else Discussion.APPROVAL_APPROVED
    approved_at = None if requires_approval else timezone.now()
    approved_by = None if requires_approval else user
    extension_payload = dict(extension_payload or {})
    discussion_lifecycle = get_runtime_discussion_lifecycle_service()
    extension_states = _prepare_discussion_create_extensions(
        discussion_lifecycle,
        user=user,
        payload=extension_payload,
    )

    with transaction.atomic():
        discussion = Discussion.objects.create(
            title=title,
            user=user,
            last_posted_at=timezone.now(),
            last_posted_user=user,
            approval_status=approval_status,
            approved_at=approved_at,
            approved_by=approved_by,
        )

        first_post = content_posts.create_first_post(
            discussion=discussion,
            user=user,
            content=content,
            content_html=render_markdown_cb(content),
            post_type=default_post_type,
            requires_approval=requires_approval,
            approved_at=approved_at,
            approved_by=approved_by,
        )

        discussion.first_post_id = first_post.id
        discussion.last_post_id = first_post.id
        discussion.last_post_number = 1
        discussion.comment_count = 1
        discussion.participant_count = 1
        discussion.save()

        _apply_discussion_resource_relationships(
            discussion,
            payload=extension_payload,
            user=user,
            creating=True,
            actor_user_id=user.id,
        )
        _refresh_discussion_private_state(discussion, first_post=first_post)
        discussion.save(update_fields=["is_private"])
        first_post.save(update_fields=["is_private"])

        _apply_discussion_create_extensions(
            discussion_lifecycle,
            discussion=discussion,
            states=extension_states,
            context={
                "actor_user_id": user.id,
                "payload": extension_payload,
                "is_approved": not requires_approval,
                "is_counted": (not requires_approval and not discussion.is_private),
            },
        )

        if not requires_approval:
            _apply_post_created_extensions(
                first_post,
                context={
                    "content": content,
                    "actor": user,
                    "discussion": discussion,
                    "is_first_post": True,
                    "is_approved": True,
                },
            )
            increment_user_discussion_count(user.id, 1)

        DiscussionUser.objects.create(
            discussion=discussion,
            user=user,
            last_read_at=timezone.now(),
            last_read_post_number=1,
            is_subscribed=False,
        )

        dispatch_forum_event_after_commit(
            DiscussionCreatedEvent(
                discussion_id=discussion.id,
                actor_user_id=user.id,
                is_approved=not requires_approval,
            )
        )
        return discussion


def update_discussion(
    discussion_id: int,
    user,
    *,
    title: Optional[str] = None,
    content: Optional[str] = None,
    extension_payload: Optional[dict] = None,
    is_locked: Optional[bool] = None,
    is_sticky: Optional[bool] = None,
    is_hidden: Optional[bool] = None,
    can_rename_discussion_cb,
    can_edit_discussion_cb,
    can_hide_discussion_cb,
    render_markdown_cb,
    set_locked_state_cb,
    set_sticky_state_cb,
    set_hidden_state_cb,
) -> Discussion:
    ensure_user_not_suspended(user, "编辑讨论")
    discussion = Discussion.objects.get(id=discussion_id)

    if title is not None and title != discussion.title and not can_rename_discussion_cb(discussion, user):
        raise PermissionDenied("没有权限修改讨论标题")

    if content is not None and not can_edit_discussion_cb(discussion, user):
        raise PermissionDenied("没有权限编辑此讨论")

    if is_hidden is not None and not can_hide_discussion_cb(discussion, user):
        raise PermissionDenied("没有权限隐藏/显示讨论")

    extension_payload = dict(extension_payload or {})

    with transaction.atomic():
        discussion_lifecycle = get_runtime_discussion_lifecycle_service()
        extension_states = _prepare_discussion_update_extensions(
            discussion_lifecycle,
            discussion=discussion,
            user=user,
            payload=extension_payload,
        )
        previous_title = discussion.title
        was_counted = (
            discussion.approval_status == Discussion.APPROVAL_APPROVED
            and discussion.hidden_at is None
            and not discussion.is_private
        )
        first_post = None

        if content is not None:
            first_post = content_posts.update_first_post_content(
                discussion,
                content=content,
                content_html=render_markdown_cb(content),
                editor=user,
            )

        if title is not None:
            discussion.title = title

        relationship_context = _apply_discussion_resource_relationships(
            discussion,
            payload=extension_payload,
            user=user,
            creating=False,
            actor_user_id=user.id,
        )
        if first_post is None and discussion.first_post_id:
            first_post = content_posts.get_first_post(discussion)
        _refresh_discussion_private_state(discussion, first_post=first_post)
        is_counted = (
            discussion.approval_status == Discussion.APPROVAL_APPROVED
            and discussion.hidden_at is None
            and not discussion.is_private
        )
        _apply_discussion_update_extensions(
            discussion_lifecycle,
            discussion=discussion,
            states=extension_states,
            context={
                **relationship_context,
                "payload": extension_payload,
                "was_counted": was_counted,
                "is_counted": is_counted,
            },
        )
        if first_post is not None:
            first_post.save(update_fields=["is_private"])
            if content is not None:
                _apply_post_updated_extensions(
                    first_post,
                    context={
                        "content": content,
                        "actor": user,
                        "discussion": discussion,
                        "is_first_post": True,
                    },
                )

        if is_locked is not None:
            if not has_forum_permission(user, "discussion.lock"):
                raise PermissionDenied("没有权限锁定/解锁讨论")
            set_locked_state_cb(discussion, user, is_locked)

        if is_sticky is not None:
            if not has_forum_permission(user, "discussion.sticky"):
                raise PermissionDenied("没有权限置顶/取消置顶讨论")
            set_sticky_state_cb(discussion, user, is_sticky)

        if is_hidden is not None:
            set_hidden_state_cb(discussion, user, is_hidden)

        if (
            discussion.approval_status == Discussion.APPROVAL_REJECTED
            and not user.is_staff
            and discussion.user_id == user.id
        ):
            previous_approval_status = discussion.approval_status
            discussion.approval_status = Discussion.APPROVAL_PENDING
            discussion.approved_at = None
            discussion.approved_by = None
            discussion.approval_note = ""
            discussion.hidden_at = None
            discussion.hidden_user = None

            if first_post is None:
                first_post = content_posts.resubmit_first_post(discussion)
            else:
                content_posts.resubmit_first_post(discussion)
            dispatch_forum_event_after_commit(
                DiscussionResubmittedEvent(
                    discussion_id=discussion.id,
                    actor_user_id=user.id,
                    previous_status=previous_approval_status,
                    discussion_title=discussion.title,
                )
            )

        discussion.save()

        if title is not None and title != previous_title:
            dispatch_forum_event_after_commit(
                DiscussionRenamedEvent(
                    discussion_id=discussion.id,
                    actor_user_id=user.id,
                    old_title=previous_title,
                    new_title=title,
                )
            )

        return discussion


def set_hidden_state(
    discussion: Discussion,
    user,
    is_hidden: bool,
    *,
    approved_reply_counts_by_author_cb,
) -> Discussion:
    was_hidden = discussion.hidden_at is not None
    if was_hidden == is_hidden:
        return discussion

    should_adjust_counts = discussion.approval_status == Discussion.APPROVAL_APPROVED
    approved_reply_counts = {}
    if should_adjust_counts:
        approved_reply_counts = approved_reply_counts_by_author_cb(discussion)

    discussion.hidden_at = timezone.now() if is_hidden else None
    discussion.hidden_user = user if is_hidden else None
    refresh_runtime_model_private(discussion)

    with transaction.atomic():
        discussion.save(update_fields=["hidden_at", "hidden_user", "is_private"])
        if should_adjust_counts:
            discussion_delta = -1 if is_hidden else 1
            reply_delta = -1 if is_hidden else 1
            if discussion.user:
                increment_user_discussion_count(discussion.user_id, discussion_delta)
            apply_user_comment_count_deltas({
                user_id: reply_delta * total
                for user_id, total in approved_reply_counts.items()
            })

        dispatch_forum_event_after_commit(
            DiscussionHiddenEvent(
                discussion_id=discussion.id,
                actor_user_id=user.id,
                is_hidden=is_hidden,
            )
        )
        _apply_discussion_hidden_extensions(
            get_runtime_discussion_lifecycle_service(),
            discussion=discussion,
            context={
                "actor_user_id": user.id,
                "is_hidden": is_hidden,
                "was_counted": should_adjust_counts,
            },
        )
    return discussion


def approve_discussion(
    discussion: Discussion,
    admin_user,
    note: str = "",
    *,
    approved_reply_counts_by_author_cb,
) -> Discussion:
    previous_status = discussion.approval_status
    was_counted = discussion.approval_status == Discussion.APPROVAL_APPROVED
    approved_reply_counts = {}
    if not was_counted:
        approved_reply_counts = approved_reply_counts_by_author_cb(discussion)

    with transaction.atomic():
        discussion.approval_status = Discussion.APPROVAL_APPROVED
        discussion.approved_at = timezone.now()
        discussion.approved_by = admin_user
        discussion.approval_note = note
        discussion.hidden_at = None
        discussion.hidden_user = None
        refresh_runtime_model_private(discussion)
        discussion.save(update_fields=[
            "approval_status",
            "approved_at",
            "approved_by",
            "approval_note",
            "hidden_at",
            "hidden_user",
            "is_private",
        ])

        first_post = content_posts.approve_first_post(
            discussion,
            approved_at=discussion.approved_at,
            approved_by=admin_user,
            note=note,
        )

        if not was_counted:
            if discussion.user:
                increment_user_discussion_count(discussion.user_id, 1)
            apply_user_comment_count_deltas(approved_reply_counts)
            if first_post is not None:
                _apply_post_approved_extensions(
                    first_post,
                    context={
                        "content": first_post.content,
                        "actor": admin_user,
                        "discussion": discussion,
                        "is_first_post": True,
                        "previous_status": previous_status,
                    },
                )

        if not was_counted:
            dispatch_forum_event_after_commit(
                DiscussionApprovedEvent(
                    discussion_id=discussion.id,
                    admin_user_id=admin_user.id,
                    note=note,
                    actor_user_id=getattr(discussion, "user_id", None),
                    discussion_title=discussion.title,
                )
            )
        _apply_discussion_approved_extensions(
            get_runtime_discussion_lifecycle_service(),
            discussion=discussion,
            context={
                "admin_user_id": admin_user.id,
                "was_counted": was_counted,
                "previous_status": previous_status,
            },
        )

    discussion.refresh_from_db()
    return discussion


def reject_discussion(
    discussion: Discussion,
    admin_user,
    note: str = "",
    *,
    approved_reply_counts_by_author_cb,
) -> Discussion:
    rejected_at = timezone.now()
    previous_status = discussion.approval_status
    was_counted = discussion.approval_status == Discussion.APPROVAL_APPROVED
    approved_reply_counts = {}
    if was_counted:
        approved_reply_counts = approved_reply_counts_by_author_cb(discussion)

    with transaction.atomic():
        discussion.approval_status = Discussion.APPROVAL_REJECTED
        discussion.approved_at = rejected_at
        discussion.approved_by = admin_user
        discussion.approval_note = note
        discussion.hidden_at = rejected_at
        discussion.hidden_user = admin_user
        refresh_runtime_model_private(discussion)
        discussion.save(update_fields=[
            "approval_status",
            "approved_at",
            "approved_by",
            "approval_note",
            "hidden_at",
            "hidden_user",
            "is_private",
        ])

        content_posts.reject_first_post(
            discussion,
            rejected_at=rejected_at,
            rejected_by=admin_user,
            note=note,
        )

        if was_counted:
            if discussion.user:
                increment_user_discussion_count(discussion.user_id, -1)
            apply_user_comment_count_deltas({
                user_id: -total
                for user_id, total in approved_reply_counts.items()
            })

        if previous_status != Discussion.APPROVAL_REJECTED:
            dispatch_forum_event_after_commit(
                DiscussionRejectedEvent(
                    discussion_id=discussion.id,
                    admin_user_id=admin_user.id,
                    note=note,
                    previous_status=previous_status,
                    actor_user_id=getattr(discussion, "user_id", None),
                    discussion_title=discussion.title,
                )
            )
        _apply_discussion_rejected_extensions(
            get_runtime_discussion_lifecycle_service(),
            discussion=discussion,
            context={
                "admin_user_id": admin_user.id,
                "previous_status": previous_status,
                "was_counted": was_counted,
            },
        )

    discussion.refresh_from_db()
    return discussion


def approved_reply_counts_by_author(discussion: Discussion, *, user_counted_post_types) -> dict:
    return content_posts.get_approved_reply_counts_by_author(
        discussion,
        user_counted_post_types=user_counted_post_types,
    )


def delete_discussion(
    discussion_id: int,
    user,
    *,
    can_delete_discussion_cb,
    approved_reply_counts_by_author_cb,
) -> bool:
    ensure_user_not_suspended(user, "删除讨论")
    discussion = Discussion.objects.get(id=discussion_id)

    if not can_delete_discussion_cb(discussion, user):
        raise PermissionDenied("没有权限删除此讨论")

    with transaction.atomic():
        discussion_lifecycle = get_runtime_discussion_lifecycle_service()
        extension_states = _prepare_discussion_delete_extensions(
            discussion_lifecycle,
            discussion=discussion,
            user=user,
            context={"actor_user_id": user.id},
        )
        counted_discussion = (
            discussion.approval_status == Discussion.APPROVAL_APPROVED
            and discussion.hidden_at is None
        )
        approved_reply_counts = {}
        if counted_discussion:
            approved_reply_counts = approved_reply_counts_by_author_cb(discussion)

        deleted_posts = content_posts.delete_discussion_posts(discussion)
        for deleted_post in deleted_posts:
            _apply_post_deleted_extensions(
                context={
                    "post_id": deleted_post["id"],
                    "discussion_id": discussion.id,
                    "actor": user,
                    "post_number": deleted_post["number"],
                    "is_first_post": deleted_post["number"] == 1,
                    "approval_status": deleted_post["approval_status"],
                    "was_hidden": deleted_post["hidden_at"] is not None,
                },
            )
        discussion.delete()

        _apply_discussion_delete_extensions(
            discussion_lifecycle,
            states=extension_states,
            context={
                "actor_user_id": user.id,
                "was_counted": counted_discussion,
            },
        )

        if counted_discussion and discussion.user:
            increment_user_discussion_count(discussion.user_id, -1)

        apply_user_comment_count_deltas({
            user_id: -total
            for user_id, total in approved_reply_counts.items()
        })

    return True


def set_locked_state(discussion: Discussion, actor, is_locked: bool) -> Discussion:
    if not has_forum_permission(actor, "discussion.lock"):
        raise PermissionDenied("没有权限锁定/解锁讨论")

    if discussion.is_locked == is_locked:
        return discussion

    with transaction.atomic():
        discussion.is_locked = is_locked
        discussion.save(update_fields=["is_locked"])
        dispatch_forum_event_after_commit(
            DiscussionLockedEvent(
                discussion_id=discussion.id,
                actor_user_id=actor.id,
                is_locked=is_locked,
            )
        )
    return discussion


def set_sticky_state(discussion: Discussion, actor, is_sticky: bool) -> Discussion:
    if not has_forum_permission(actor, "discussion.sticky"):
        raise PermissionDenied("没有权限置顶/取消置顶讨论")

    if discussion.is_sticky == is_sticky:
        return discussion

    with transaction.atomic():
        discussion.is_sticky = is_sticky
        discussion.save(update_fields=["is_sticky"])
        dispatch_forum_event_after_commit(
            DiscussionStickyChangedEvent(
                discussion_id=discussion.id,
                actor_user_id=actor.id,
                is_sticky=is_sticky,
            )
        )
    return discussion

