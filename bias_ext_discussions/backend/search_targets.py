from __future__ import annotations


def discussion_search_target_provider() -> dict:
    from bias_ext_discussions.backend.models import Discussion
    from bias_ext_discussions.backend.visibility import apply_discussion_visibility_scope

    return {
        "model": Discussion,
        "apply_visibility": apply_discussion_visibility_scope,
    }

