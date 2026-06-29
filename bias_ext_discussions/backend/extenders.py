from bias_core.extensions import (
    AdminSurfaceExtender,
    ApiResourceExtender,
    EventListenersExtender,
    ForumCapabilitiesExtender,
    LifecycleExtender,
    ModelExtender,
    ModelVisibilityExtender,
    RealtimeExtender,
    SearchIndexExtender,
    ServiceProviderExtender,
    SettingsExtender,
    RuntimeModel,
)

from bias_ext_discussions.backend.admin_surface import permission_definitions
from bias_ext_discussions.backend.events import (
    DiscussionCreatedEvent,
    DiscussionHiddenEvent,
    DiscussionLockedEvent,
    DiscussionRenamedEvent,
    DiscussionStickyChangedEvent,
)
from bias_ext_discussions.backend.forum_contracts import (
    discussion_list_filter_definitions,
    discussion_sort_definitions,
    post_type_definitions,
)
from bias_ext_discussions.backend.frontend import frontend_extender
from bias_ext_discussions.backend.handlers import discussion_resource_endpoints
from bias_ext_discussions.backend.listener_contracts import event_listener_definitions
from bias_ext_discussions.backend.model_contracts import owned_models
from bias_ext_discussions.backend.models import Discussion
from bias_ext_discussions.backend.realtime import (
    discussion_realtime_broadcaster_provider,
    resolve_visible_discussion_ids,
)
from bias_ext_discussions.backend.resources import (
    admin_stats_resource_field_definitions,
    discussion_resource_definitions,
    discussion_resource_field_definitions,
    discussion_resource_relationship_definitions,
)
from bias_ext_discussions.backend.runtime import (
    discussion_service_provider,
    discussion_timeline_provider,
)
from bias_ext_discussions.backend.search_contracts import search_index_definitions
from bias_ext_discussions.backend.search_targets import (
    discussion_search_target_provider,
)
from bias_ext_discussions.backend.settings import setting_field_definitions
from bias_ext_discussions.backend.visibility import scope_discussion_view


def frontend_extenders():
    return (frontend_extender(),)


def admin_extenders():
    return (
        AdminSurfaceExtender(
            permissions=permission_definitions(),
            permissions_pages=("/admin/extensions/discussions/permissions",),
            generated_permissions_page=True,
        ),
        SettingsExtender(
            fields=setting_field_definitions(),
            expose_to_forum=("allow_renaming",),
        ),
    )


def forum_extenders():
    return (
        ForumCapabilitiesExtender(
            post_types=post_type_definitions(),
            discussion_sorts=discussion_sort_definitions(),
            discussion_list_filters=discussion_list_filter_definitions(),
        ),
    )


def event_extenders():
    return (
        EventListenersExtender(
            listeners=event_listener_definitions(),
        ),
    )


def realtime_extenders():
    return (
        RealtimeExtender()
        .discussion_visibility(
            resolve_visible_discussion_ids,
            description="根据讨论可见性规则解析实时订阅可见讨论。",
        )
        .broadcast_discussion_event(
            DiscussionCreatedEvent,
            "discussion.created",
            include_discussion=True,
            include_post=True,
            post_id_getter=lambda discussion: discussion.first_post_id,
            condition=lambda event: event.is_approved,
            description="审核通过的讨论创建后广播实时讨论和首帖资源。",
        )
        .broadcast_discussion_event(
            DiscussionRenamedEvent,
            "discussion.renamed",
            include_discussion=True,
            description="讨论重命名后广播实时讨论资源。",
        )
        .broadcast_discussion_event(
            DiscussionLockedEvent,
            "discussion.locked",
            include_discussion=True,
            description="讨论锁定状态变化后广播实时讨论资源。",
        )
        .broadcast_discussion_event(
            DiscussionStickyChangedEvent,
            "discussion.sticky_changed",
            include_discussion=True,
            description="讨论置顶状态变化后广播实时讨论资源。",
        )
        .broadcast_discussion_event(
            DiscussionHiddenEvent,
            "discussion.hidden",
            description="讨论隐藏状态变化后广播实时事件。",
        ),
    )


def resource_extenders():
    return (
        ApiResourceExtender("discussion")
        .endpoints_with(*discussion_resource_endpoints())
        .fields(discussion_resource_field_definitions)
        .relationships(discussion_resource_relationship_definitions),
        ApiResourceExtender("admin_stats").fields(admin_stats_resource_field_definitions),
        *(
            ApiResourceExtender(definition)
            for definition in discussion_resource_definitions()
        ),
    )


def model_extenders():
    return (
        _model_extender(),
        ModelVisibilityExtender().scope(
            Discussion,
            scope_discussion_view,
            description="限制当前用户只能查看有权限访问的讨论。",
        ).scope(
            RuntimeModel("content.discussions", description="content 基础包提供的讨论模型。"),
            scope_discussion_view,
            description="限制当前用户只能查看有权限访问的讨论。",
        ),
    )


def service_extenders():
    return (
        ServiceProviderExtender(
            key="discussions.service",
            provider=discussion_service_provider,
        ),
        ServiceProviderExtender(
            key="discussions.timeline",
            provider=discussion_timeline_provider,
        ),
        ServiceProviderExtender(
            key="search.target.discussion",
            provider=discussion_search_target_provider,
        ),
        ServiceProviderExtender(
            key="realtime.discussion_broadcaster",
            provider=discussion_realtime_broadcaster_provider,
        ),
        LifecycleExtender(),
    )


def search_extenders():
    return (_search_index_extender(),)


def _model_extender():
    extender = ModelExtender()
    for model, description in owned_models():
        extender = extender.owns(model, description=description)
    return extender


def _search_index_extender():
    extender = SearchIndexExtender()
    for definition in search_index_definitions():
        extender = extender.postgres_index(
            definition["name"],
            drop=definition["drop"],
            create=definition["create"],
            description=definition["description"],
        )
    return extender
