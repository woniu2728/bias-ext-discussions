from __future__ import annotations

from bias_ext_discussions.backend.models import Discussion, DiscussionUser


def owned_models():
    return (
        (
            Discussion,
            "讨论主题由 discussions 扩展拥有。",
        ),
        (
            DiscussionUser,
            "讨论用户阅读和订阅状态由 discussions 扩展拥有。",
        ),
    )
