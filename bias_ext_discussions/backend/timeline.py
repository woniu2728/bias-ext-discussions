from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Callable

from django.utils import timezone

from bias_ext_discussions.backend import content_posts
from bias_ext_discussions.backend.models import Discussion


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


def get_user_by_id(*args, **kwargs):
    return _service_method(get_runtime_service("users.service"), "get_by_id")(*args, **kwargs)


TimelineContentBuilder = Callable[[object], tuple[str, str] | None]


@dataclass(frozen=True)
class TimelineEventDefinition:
    event_type: type
    post_type: str
    build_content: TimelineContentBuilder


def make_timeline_context(event, **extra):
    payload = dict(getattr(event, "__dict__", {}))
    payload.update(extra)
    return SimpleNamespace(**payload)


def create_timeline_from_builder(
    event,
    builder,
    *,
    update_discussion_last_post: bool | None = None,
    merge_strategy: str = "",
) -> None:
    built = builder(event)
    if not built:
        return

    post_type, content = built
    create_timeline_event_post(
        discussion_id=event.discussion_id,
        actor_user_id=event.actor_user_id,
        post_type=post_type,
        content=content,
        update_discussion_last_post=update_discussion_last_post,
        merge_strategy=merge_strategy,
    )


def create_timeline_event_post(
    *,
    discussion_id: int,
    actor_user_id: int,
    post_type: str,
    content: str,
    update_discussion_last_post: bool | None = None,
    merge_strategy: str = "",
) -> object | None:
    try:
        actor = get_user_by_id(actor_user_id)
        discussion = Discussion.objects.get(id=discussion_id)
    except Discussion.DoesNotExist:
        return None
    except Exception:
        return None

    merged_post = _merge_timeline_event_post(
        discussion=discussion,
        actor=actor,
        post_type=post_type,
        content=content,
        merge_strategy=merge_strategy,
    )
    if merged_post is not None:
        return merged_post

    event_post = content_posts.create_post_event(
        discussion=discussion,
        actor=actor,
        post_type=post_type,
        content=content,
        content_html="",
        approved_at=timezone.now(),
    )

    should_update_discussion_last_post = (
        _post_type_counts_toward_discussion(post_type)
        if update_discussion_last_post is None
        else bool(update_discussion_last_post)
    )

    if should_update_discussion_last_post:
        locked_discussion = event_post.discussion
        locked_discussion.last_post_id = event_post.id
        locked_discussion.last_post_number = event_post.number
        locked_discussion.last_posted_at = event_post.created_at
        locked_discussion.last_posted_user = actor
        locked_discussion.save(update_fields=[
            "last_post_id",
            "last_post_number",
            "last_posted_at",
            "last_posted_user",
        ])
    return event_post


def _merge_timeline_event_post(
    *,
    discussion,
    actor,
    post_type: str,
    content: str,
    merge_strategy: str,
) -> object | None:
    if str(merge_strategy or "").strip() != "same_actor_reversible":
        return None

    previous = content_posts.get_latest_event_post(discussion=discussion, post_type=post_type)
    if previous is None or getattr(previous, "user_id", None) != getattr(actor, "id", None):
        return None

    previous_parts = _parse_tagged_event_content(getattr(previous, "content", ""))
    current_parts = _parse_tagged_event_content(content)
    if previous_parts is None or current_parts is None:
        return None

    if previous_parts[1] == current_parts[0]:
        content_posts.delete_event_post(previous)
        return previous

    merged_content = _build_tagged_event_content(current_parts[0], previous_parts[1])
    return content_posts.update_event_post_content(previous, content=merged_content, content_html="")


def _parse_tagged_event_content(content: str | None) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    added = None
    removed = None
    for line in str(content or "").splitlines():
        normalized = line.strip()
        if normalized.startswith("added:"):
            added = tuple(item for item in normalized.removeprefix("added:").split("|") if item)
        elif normalized.startswith("removed:"):
            removed = tuple(item for item in normalized.removeprefix("removed:").split("|") if item)
    if added is None or removed is None:
        return None
    return added, removed


def _build_tagged_event_content(added: tuple[str, ...], removed: tuple[str, ...]) -> str:
    return (
        f"added:{'|'.join(added)}\n"
        f"removed:{'|'.join(removed)}"
    )


def _post_type_counts_toward_discussion(post_type: str) -> bool:
    try:
        from bias_core.extensions.platform import get_forum_registry

        definition = get_forum_registry().get_post_type(str(post_type or "").strip())
    except Exception:
        definition = None
    if definition is None:
        return False
    return bool(definition.counts_toward_discussion)


def build_discussion_renamed_content(event) -> tuple[str, str] | None:
    return event.post_type, f"from: {event.old_title}\nto: {event.new_title}"


def build_discussion_tagged_content(event) -> tuple[str, str] | None:
    return event.post_type, (
        f"added:{'|'.join(event.added_tags)}\n"
        f"removed:{'|'.join(event.removed_tags)}"
    )


def build_discussion_locked_content(event) -> tuple[str, str] | None:
    return event.post_type, ("locked" if event.is_locked else "unlocked")


def build_discussion_sticky_content(event) -> tuple[str, str] | None:
    return event.post_type, ("sticky" if event.is_sticky else "unsticky")


def build_discussion_hidden_content(event) -> tuple[str, str] | None:
    return event.post_type, ("hidden" if event.is_hidden else "restored")


def build_discussion_review_content(event) -> tuple[str, str] | None:
    return event.post_type, (
        f"previous_status: {event.previous_status}\n"
        f"note: {event.note}"
    )


def build_discussion_resubmitted_content(event) -> tuple[str, str] | None:
    return event.post_type, (
        f"previous_status: {event.previous_status}\n"
        "note:"
    )


def build_post_review_content(event) -> tuple[str, str] | None:
    return event.post_type, (
        f"target_post_id: {event.post_id}\n"
        f"target_post_number: {event.post_number}\n"
        f"previous_status: {event.previous_status}\n"
        f"note: {event.note}"
    )


def build_post_resubmitted_content(event) -> tuple[str, str] | None:
    return event.post_type, (
        f"target_post_id: {event.post_id}\n"
        f"target_post_number: {event.post_number}\n"
        f"previous_status: {event.previous_status}\n"
        "note:"
    )


def build_post_hidden_content(event) -> tuple[str, str] | None:
    return event.post_type, (
        f"state: {'hidden' if event.is_hidden else 'restored'}\n"
        f"target_post_id: {event.post_id}\n"
        f"target_post_number: {event.post_number}"
    )
