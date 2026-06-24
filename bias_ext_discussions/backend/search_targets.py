from __future__ import annotations


def discussion_search_target_provider() -> dict:
    from bias_core.extensions.runtime import get_runtime_post_model
    from bias_ext_discussions.backend.models import Discussion
    from bias_ext_discussions.backend.visibility import apply_discussion_visibility_scope

    return {
        "model": Discussion,
        "first_post_model": get_runtime_post_model(),
        "apply_visibility": apply_discussion_visibility_scope,
    }


def post_search_target_provider() -> dict:
    from bias_core.extensions.runtime import get_runtime_post_model
    from bias_ext_discussions.backend.visibility import apply_post_visibility_scope

    return {
        "model": get_runtime_post_model(),
        "apply_visibility": apply_post_visibility_scope,
    }


