from __future__ import annotations

from bias_ext_discussions.backend.extenders import (
    admin_extenders,
    event_extenders,
    forum_extenders,
    frontend_extenders,
    model_extenders,
    realtime_extenders,
    resource_extenders,
    search_extenders,
    service_extenders,
)


def extend():
    return [
        *frontend_extenders(),
        *admin_extenders(),
        *forum_extenders(),
        *event_extenders(),
        *realtime_extenders(),
        *resource_extenders(),
        *model_extenders(),
        *service_extenders(),
        *search_extenders(),
    ]
