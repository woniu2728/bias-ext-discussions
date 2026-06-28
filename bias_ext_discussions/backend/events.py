from __future__ import annotations

from dataclasses import dataclass

from bias_core.extensions.platform import DomainEvent


@dataclass(frozen=True)
class DiscussionCreatedEvent(DomainEvent):
    discussion_id: int
    actor_user_id: int
    is_approved: bool = True


@dataclass(frozen=True)
class DiscussionApprovedEvent(DomainEvent):
    discussion_id: int
    admin_user_id: int
    note: str = ""
    actor_user_id: int | None = None
    discussion_title: str = ""


@dataclass(frozen=True)
class DiscussionRenamedEvent(DomainEvent):
    discussion_id: int
    actor_user_id: int
    old_title: str
    new_title: str


@dataclass(frozen=True)
class DiscussionLockedEvent(DomainEvent):
    discussion_id: int
    actor_user_id: int
    is_locked: bool


@dataclass(frozen=True)
class DiscussionStickyChangedEvent(DomainEvent):
    discussion_id: int
    actor_user_id: int
    is_sticky: bool


@dataclass(frozen=True)
class DiscussionHiddenEvent(DomainEvent):
    discussion_id: int
    actor_user_id: int
    is_hidden: bool


@dataclass(frozen=True)
class DiscussionRejectedEvent(DomainEvent):
    discussion_id: int
    admin_user_id: int
    note: str = ""
    previous_status: str = ""
    actor_user_id: int | None = None
    discussion_title: str = ""


@dataclass(frozen=True)
class DiscussionResubmittedEvent(DomainEvent):
    discussion_id: int
    actor_user_id: int
    previous_status: str = ""
    discussion_title: str = ""


@dataclass(frozen=True)
class DiscussionUserReadEvent(DomainEvent):
    discussion_id: int
    user_id: int
    last_read_post_number: int

