from __future__ import annotations

from bias_core.extensions.runtime import (
    get_extension_host_service,
    get_runtime_post_lifecycle_service,
    runtime_service_method,
)


def _content_posts_service():
    return get_extension_host_service("content.posts", None)


def _content_posts_method(name: str):
    service = _content_posts_service()
    if isinstance(service, dict):
        method = service.get(name)
    else:
        method = getattr(service, name, None)
    if callable(method):
        return method
    raise RuntimeError(f"Content foundation posts service missing method: {name}")


def get_first_post(discussion):
    return _content_posts_method("get_first_post")(discussion)


def create_first_post(**kwargs):
    return _content_posts_method("create_first_post")(**kwargs)


def update_first_post_content(**kwargs):
    return _content_posts_method("update_first_post_content")(**kwargs)


def approve_first_post(**kwargs):
    return _content_posts_method("approve_first_post")(**kwargs)


def reject_first_post(**kwargs):
    return _content_posts_method("reject_first_post")(**kwargs)


def resubmit_first_post(discussion):
    return _content_posts_method("resubmit_first_post")(discussion)


def delete_discussion_posts(discussion):
    return _content_posts_method("delete_discussion_posts")(discussion)


def get_post_lifecycle_service():
    return get_runtime_post_lifecycle_service()


def get_approved_reply_counts_by_author(*args, **kwargs):
    return _content_posts_method("approved_reply_counts_by_author")(*args, **kwargs)


def get_approved_discussion_post_stats(*args, **kwargs):
    return _content_posts_method("approved_discussion_stats")(*args, **kwargs)


def get_discussion_post_number(post_id):
    return _content_posts_method("get_post_number")(post_id)


def get_post_model_or_none():
    service = _content_posts_service()
    if isinstance(service, dict):
        return service.get("model")
    return getattr(service, "model", None)


def resolve_discussion_post_content_html(post):
    return _content_posts_method("resolve_content_html")(post)


def serialize_realtime_post_by_id(post_id, *, user=None):
    service = get_extension_host_service("realtime.post_payload", None)
    if service is None:
        return None
    return runtime_service_method(service, "serialize_by_id")(post_id, user=user)


def create_post_event(**kwargs):
    return _content_posts_method("create_event_post")(**kwargs)
