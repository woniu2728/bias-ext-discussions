from __future__ import annotations

from bias_core.extensions import FrontendExtender


def frontend_extender():
    return (
        FrontendExtender(
            admin_entry="extensions/discussions/frontend/admin/index.js",
            forum_entry="extensions/discussions/frontend/forum/index.js",
        )
        .route(
            "/",
            "home",
            "./DiscussionListView.vue",
            title="全部讨论",
            description="浏览论坛最新讨论、热门主题和社区回复。",
            order=0,
        )
        .route(
            "/d/:id",
            "discussion-detail",
            "./DiscussionDetailView.vue",
            title="讨论详情",
            description="查看讨论内容和回复。",
            order=1,
        )
        .route(
            "/discussions/create",
            "discussion-create",
            "./DiscussionCreateView.vue",
            title="发起讨论",
            description="创建新的论坛讨论。",
            requires_auth=True,
            order=2,
        )
    )
