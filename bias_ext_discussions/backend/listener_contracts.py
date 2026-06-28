from __future__ import annotations

from bias_core.extensions import ExtensionEventListenerDefinition

from bias_ext_discussions.backend.events import (
    DiscussionHiddenEvent,
    DiscussionLockedEvent,
    DiscussionRenamedEvent,
    DiscussionStickyChangedEvent,
)
from bias_ext_discussions.backend.listeners import (
    handle_discussion_hidden,
    handle_discussion_locked,
    handle_discussion_renamed,
    handle_discussion_sticky_changed,
)


def event_listener_definitions():
    return (
        ExtensionEventListenerDefinition(
            event_type=DiscussionRenamedEvent,
            handler=handle_discussion_renamed,
            description="讨论重命名后写入时间线事件帖。",
        ),
        ExtensionEventListenerDefinition(
            event_type=DiscussionLockedEvent,
            handler=handle_discussion_locked,
            description="讨论锁定状态变化后写入时间线事件帖。",
        ),
        ExtensionEventListenerDefinition(
            event_type=DiscussionStickyChangedEvent,
            handler=handle_discussion_sticky_changed,
            description="讨论置顶状态变化后写入时间线事件帖。",
        ),
        ExtensionEventListenerDefinition(
            event_type=DiscussionHiddenEvent,
            handler=handle_discussion_hidden,
            description="讨论隐藏状态变化后写入时间线事件帖。",
        ),
    )
