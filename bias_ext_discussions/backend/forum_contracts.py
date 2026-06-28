from __future__ import annotations

from bias_core.extensions import (
    DiscussionListFilterDefinition,
    DiscussionSortDefinition,
    PostTypeDefinition,
)

from bias_ext_discussions.backend.constants import EXTENSION_ID
from bias_ext_discussions.backend.registry import (
    apply_all_discussion_list_filter,
    apply_discussion_latest_sort,
    apply_discussion_newest_sort,
    apply_discussion_oldest_sort,
    apply_discussion_top_sort,
    apply_discussion_unanswered_sort,
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


def discussion_sort_definitions():
    return (
        DiscussionSortDefinition(
            code="latest",
            label="最新活跃",
            module_id=EXTENSION_ID,
            applier=apply_discussion_latest_sort,
            description="按最后活跃时间排序，优先展示最近有新回复的讨论。",
            icon="fas fa-clock",
            is_default=True,
            order=10,
            toolbar_visible=True,
        ),
        DiscussionSortDefinition(
            code="newest",
            label="新主题",
            module_id=EXTENSION_ID,
            applier=apply_discussion_newest_sort,
            description="按讨论创建时间倒序，优先展示最新发布的主题。",
            icon="fas fa-file-alt",
            order=20,
            toolbar_visible=True,
        ),
        DiscussionSortDefinition(
            code="top",
            label="热门",
            module_id=EXTENSION_ID,
            applier=apply_discussion_top_sort,
            description="按回复数和浏览量综合排序，优先展示热门讨论。",
            icon="fas fa-fire",
            order=30,
            toolbar_visible=True,
        ),
        DiscussionSortDefinition(
            code="unanswered",
            label="零回复",
            module_id=EXTENSION_ID,
            applier=apply_discussion_unanswered_sort,
            description="优先展示还没有收到其他回复的讨论，便于发现待回应主题。",
            icon="fas fa-comment-slash",
            order=40,
            toolbar_visible=False,
        ),
        DiscussionSortDefinition(
            code="oldest",
            label="最早发布",
            module_id=EXTENSION_ID,
            applier=apply_discussion_oldest_sort,
            description="按讨论创建时间正序排序。",
            icon="fas fa-hourglass-start",
            order=50,
            toolbar_visible=False,
        ),
    )


def discussion_list_filter_definitions():
    return (
        DiscussionListFilterDefinition(
            code="all",
            label="全部讨论",
            module_id=EXTENSION_ID,
            applier=apply_all_discussion_list_filter,
            description="显示当前可见的全部讨论。",
            icon="far fa-comments",
            is_default=True,
            order=10,
            route_path="/",
        ),
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
