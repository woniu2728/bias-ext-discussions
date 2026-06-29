from __future__ import annotations

from bias_core.extensions.runtime import (
    approve_runtime_first_post,
    create_runtime_first_post,
    create_runtime_post_event,
    delete_runtime_discussion_posts,
    get_runtime_approved_discussion_post_stats,
    get_runtime_approved_reply_counts_by_author,
    get_runtime_discussion_post_number,
    get_runtime_first_post,
    get_runtime_post_lifecycle_service,
    get_runtime_post_model_or_none,
    reject_runtime_first_post,
    resolve_runtime_discussion_post_content_html,
    resubmit_runtime_first_post,
    serialize_runtime_realtime_post_by_id,
    update_runtime_first_post_content,
)


def get_first_post(discussion):
    return get_runtime_first_post(discussion)


def create_first_post(**kwargs):
    return create_runtime_first_post(**kwargs)


def update_first_post_content(**kwargs):
    return update_runtime_first_post_content(**kwargs)


def approve_first_post(**kwargs):
    return approve_runtime_first_post(**kwargs)


def reject_first_post(**kwargs):
    return reject_runtime_first_post(**kwargs)


def resubmit_first_post(discussion):
    return resubmit_runtime_first_post(discussion)


def delete_discussion_posts(discussion):
    return delete_runtime_discussion_posts(discussion)


def get_post_lifecycle_service():
    return get_runtime_post_lifecycle_service()


def get_approved_reply_counts_by_author(*args, **kwargs):
    return get_runtime_approved_reply_counts_by_author(*args, **kwargs)


def get_approved_discussion_post_stats(*args, **kwargs):
    return get_runtime_approved_discussion_post_stats(*args, **kwargs)


def get_discussion_post_number(post_id):
    return get_runtime_discussion_post_number(post_id)


def get_post_model_or_none():
    return get_runtime_post_model_or_none()


def resolve_discussion_post_content_html(post):
    return resolve_runtime_discussion_post_content_html(post)


def serialize_realtime_post_by_id(post_id, *, user=None):
    return serialize_runtime_realtime_post_by_id(post_id, user=user)


def create_post_event(**kwargs):
    return create_runtime_post_event(**kwargs)
