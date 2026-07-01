from __future__ import annotations

from bias_core.extensions import (
    DiscussionListFilterDefinition,
    PostTypeDefinition,
)

from bias_ext_discussions.backend.constants import EXTENSION_ID
from bias_ext_discussions.backend.registry import (
    apply_my_discussions_list_filter,
    apply_unread_discussions_list_filter,
)


def post_type_definitions():
    return (
        PostTypeDefinition(
            code="discussionRenamed",
            label="讨论改标题",
            module_id=EXTENSION_ID,
            description="记录讨论标题被修改的系统事件帖，不计入回复统计和全文搜索。",
            icon="fas fa-heading",
            is_default=False,
            is_stream_visible=True,
            counts_toward_discussion=False,
            counts_toward_user=False,
            searchable=False,
        ),
        PostTypeDefinition(
            code="discussionLocked",
            label="讨论锁定状态变更",
            module_id=EXTENSION_ID,
            description="记录讨论被锁定或解除锁定的系统事件帖，不计入回复统计和全文搜索。",
            icon="fas fa-lock",
            is_default=False,
            is_stream_visible=True,
            counts_toward_discussion=False,
            counts_toward_user=False,
            searchable=False,
        ),
        PostTypeDefinition(
            code="discussionSticky",
            label="讨论置顶状态变更",
            module_id=EXTENSION_ID,
            description="记录讨论被置顶或取消置顶的系统事件帖，不计入回复统计和全文搜索。",
            icon="fas fa-thumbtack",
            is_default=False,
            is_stream_visible=True,
            counts_toward_discussion=False,
            counts_toward_user=False,
            searchable=False,
        ),
        PostTypeDefinition(
            code="discussionHidden",
            label="讨论隐藏状态变更",
            module_id=EXTENSION_ID,
            description="记录讨论被隐藏或恢复显示的系统事件帖，不计入回复统计和全文搜索。",
            icon="fas fa-eye-slash",
            is_default=False,
            is_stream_visible=True,
            counts_toward_discussion=False,
            counts_toward_user=False,
            searchable=False,
        ),
    )


def discussion_list_filter_definitions():
    return (
        DiscussionListFilterDefinition(
            code="my",
            label="我发起的",
            module_id=EXTENSION_ID,
            applier=apply_my_discussions_list_filter,
            description="仅显示当前用户自己发起的讨论。",
            icon="fas fa-user",
            requires_authenticated_user=True,
            order=30,
            sidebar_visible=False,
        ),
        DiscussionListFilterDefinition(
            code="unread",
            label="未读",
            module_id=EXTENSION_ID,
            applier=apply_unread_discussions_list_filter,
            description="仅显示当前用户仍有未读回复的讨论。",
            icon="fas fa-circle",
            requires_authenticated_user=True,
            order=40,
            sidebar_visible=False,
        ),
    )
