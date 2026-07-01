"""讨论系统业务逻辑层。"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.utils import timezone

from bias_core.extensions.platform import sqlite_write_retry
from bias_core.extensions.platform import get_extension_settings
from bias_core.extensions.platform import get_forum_event_bus
from bias_core.extensions.platform import evaluate_extension_policy
from bias_core.extensions.platform import get_forum_registry
from bias_ext_discussions.backend import discussion_tracking, service_lifecycle
from bias_ext_discussions.backend.models import Discussion, DiscussionUser
from bias_core.extensions.platform import PaginationService


# Keep discussions independent from the users extension at runtime.
User = Any


def evaluate_runtime_model_policy(*args, **kwargs):
    from bias_core.extensions.runtime import evaluate_runtime_model_policy as runtime_evaluate_model_policy

    return runtime_evaluate_model_policy(*args, **kwargs)


def get_extension_host_service(*args, **kwargs):
    from bias_core.extensions.runtime import get_extension_host_service as runtime_get_extension_host_service

    return runtime_get_extension_host_service(*args, **kwargs)


def get_runtime_resource_registry(*args, **kwargs):
    from bias_core.extensions.runtime import get_runtime_resource_registry as runtime_get_resource_registry

    return runtime_get_resource_registry(*args, **kwargs)


def get_runtime_service(service_key: str, default=None):
    from bias_core.extensions.runtime import get_runtime_service as runtime_get_service

    return runtime_get_service(service_key, default)


def _service_method(service, name: str):
    if isinstance(service, dict):
        method = service.get(name)
    else:
        method = getattr(service, name, None)
    if not callable(method):
        raise RuntimeError(f"Discussions 扩展运行时服务缺少方法: {name}")
    return method


def has_forum_permission(user, permission_names) -> bool:
    return bool(_service_method(get_runtime_service("users.service"), "has_forum_permission")(user, permission_names))


def _get_forum_registry():
    return get_forum_registry()


def _get_default_post_type() -> str:
    return _get_forum_registry().get_default_post_type_code()


def _get_discussion_counted_post_types() -> tuple[str, ...]:
    return _get_forum_registry().get_discussion_counted_post_type_codes()


def _get_user_counted_post_types() -> tuple[str, ...]:
    return _get_forum_registry().get_user_counted_post_type_codes()


def _get_content_discussions_service():
    return get_extension_host_service("content.discussions", None)


def _content_discussions_method(name: str):
    service = _get_content_discussions_service()
    if isinstance(service, dict):
        method = service.get(name)
    else:
        method = getattr(service, name, None)
    return method if callable(method) else None


def _reload_discussion_for_extension(discussion):
    discussion_id = getattr(discussion, "id", discussion)
    return Discussion.objects.get(id=discussion_id)


class DiscussionService:
    """讨论服务"""

    VIEW_COUNT_THROTTLE_SECONDS = 60 * 15
    VIEW_COUNT_FLUSH_DELAY_SECONDS = 60
    VIEW_COUNT_CACHE_TIMEOUT = 60 * 60 * 24
    VIEW_COUNT_PENDING_IDS_CACHE_KEY = "discussion.view_count.pending.ids"

    @staticmethod
    def normalize_discussion_sort(sort: str | None) -> str:
        return _get_forum_registry().get_discussion_sort(sort or "").code

    @staticmethod
    def get_discussion_sort_catalog():
        return get_runtime_resource_registry().apply_sort_definitions(
            "discussion",
            _get_forum_registry().get_discussion_sorts(),
        )

    @staticmethod
    def normalize_discussion_list_filter(filter_code: str | None) -> str:
        return _get_forum_registry().get_discussion_list_filter(filter_code or "").code

    @staticmethod
    def get_discussion_list_filter_catalog():
        return _get_forum_registry().get_discussion_list_filters()

    @staticmethod
    def _viewer_cache_identity(user: Optional[User]) -> str:
        content_discussions = _get_content_discussions_service()
        if content_discussions is not None:
            from bias_content.backend.runtime import viewer_cache_identity

            return viewer_cache_identity(user)
        return discussion_tracking.viewer_cache_identity(user)

    @staticmethod
    def _view_count_cache_key(discussion_id: int, user: Optional[User]) -> str:
        content_discussions = _get_content_discussions_service()
        if content_discussions is not None:
            from bias_content.backend.runtime import view_count_cache_key

            return view_count_cache_key(discussion_id, user)
        return discussion_tracking.view_count_cache_key(discussion_id, user)

    @staticmethod
    def _view_count_pending_cache_key(discussion_id: int) -> str:
        content_discussions = _get_content_discussions_service()
        if content_discussions is not None:
            from bias_content.backend.runtime import view_count_pending_cache_key

            return view_count_pending_cache_key(discussion_id)
        return discussion_tracking.view_count_pending_cache_key(discussion_id)

    @staticmethod
    def _view_count_flush_lock_cache_key(discussion_id: int) -> str:
        content_discussions = _get_content_discussions_service()
        if content_discussions is not None:
            from bias_content.backend.runtime import view_count_flush_lock_cache_key

            return view_count_flush_lock_cache_key(discussion_id)
        return discussion_tracking.view_count_flush_lock_cache_key(discussion_id)

    @staticmethod
    def record_view(discussion: Discussion, user: Optional[User] = None) -> bool:
        content_record_view = _content_discussions_method("record_view")
        if content_record_view is not None:
            return bool(content_record_view(discussion, user))
        return discussion_tracking.record_view(
            discussion,
            user=user,
            throttle_seconds=DiscussionService.VIEW_COUNT_THROTTLE_SECONDS,
            cache_timeout=DiscussionService.VIEW_COUNT_CACHE_TIMEOUT,
            pending_ids_cache_key=DiscussionService.VIEW_COUNT_PENDING_IDS_CACHE_KEY,
            flush_delay_seconds=DiscussionService.VIEW_COUNT_FLUSH_DELAY_SECONDS,
        )

    @staticmethod
    def _increment_pending_view_count(discussion_id: int) -> int:
        content_discussions = _get_content_discussions_service()
        if content_discussions is not None:
            from bias_content.backend.runtime import increment_pending_view_count

            return increment_pending_view_count(discussion_id)
        return discussion_tracking.increment_pending_view_count(
            discussion_id,
            cache_timeout=DiscussionService.VIEW_COUNT_CACHE_TIMEOUT,
            pending_ids_cache_key=DiscussionService.VIEW_COUNT_PENDING_IDS_CACHE_KEY,
        )

    @staticmethod
    def _remember_pending_view_discussion(discussion_id: int) -> None:
        content_discussions = _get_content_discussions_service()
        if content_discussions is not None:
            from bias_content.backend.runtime import remember_pending_view_discussion

            return remember_pending_view_discussion(discussion_id)
        discussion_tracking.remember_pending_view_discussion(
            discussion_id,
            cache_timeout=DiscussionService.VIEW_COUNT_CACHE_TIMEOUT,
            pending_ids_cache_key=DiscussionService.VIEW_COUNT_PENDING_IDS_CACHE_KEY,
        )

    @staticmethod
    def dispatch_view_count_flush(discussion_id: int, pending_count: int = 0):
        content_discussions = _get_content_discussions_service()
        if content_discussions is not None:
            from bias_content.backend.runtime import dispatch_view_count_flush

            return dispatch_view_count_flush(discussion_id, pending_count=pending_count)
        return discussion_tracking.dispatch_view_count_flush(
            discussion_id,
            pending_count=pending_count,
            cache_timeout=DiscussionService.VIEW_COUNT_CACHE_TIMEOUT,
            flush_delay_seconds=DiscussionService.VIEW_COUNT_FLUSH_DELAY_SECONDS,
        )

    @staticmethod
    def flush_pending_view_count(discussion_id: int) -> int:
        content_discussions = _get_content_discussions_service()
        if content_discussions is not None:
            from bias_content.backend.runtime import flush_pending_view_count

            return flush_pending_view_count(discussion_id)
        return discussion_tracking.flush_pending_view_count(
            discussion_id,
            cache_timeout=DiscussionService.VIEW_COUNT_CACHE_TIMEOUT,
            flush_delay_seconds=DiscussionService.VIEW_COUNT_FLUSH_DELAY_SECONDS,
        )

    @staticmethod
    def flush_all_pending_view_counts() -> int:
        content_discussions = _get_content_discussions_service()
        if content_discussions is not None:
            from bias_content.backend.runtime import flush_all_pending_view_counts

            return flush_all_pending_view_counts()
        return discussion_tracking.flush_all_pending_view_counts(
            cache_timeout=DiscussionService.VIEW_COUNT_CACHE_TIMEOUT,
            pending_ids_cache_key=DiscussionService.VIEW_COUNT_PENDING_IDS_CACHE_KEY,
            flush_delay_seconds=DiscussionService.VIEW_COUNT_FLUSH_DELAY_SECONDS,
        )

    @staticmethod
    def _can_view_discussion(discussion: Discussion, user: Optional[User]) -> bool:
        can_view = _content_discussions_method("can_view")
        if can_view is not None:
            return bool(can_view(discussion, user))
        return discussion_tracking.can_view_discussion(discussion, user)

    @staticmethod
    def apply_visibility_filters(queryset, user: Optional[User] = None):
        apply_visibility = _content_discussions_method("apply_visibility")
        if apply_visibility is not None:
            return apply_visibility(queryset, user)
        return discussion_tracking.apply_visibility_filters(queryset, user)

    @staticmethod
    @sqlite_write_retry()
    def create_discussion(
        title: str,
        content: str,
        user: User,
        extension_payload: Optional[dict[str, Any]] = None,
    ) -> Discussion:
        """
        创建讨论

        Args:
            title: 讨论标题
            content: 第一条帖子内容
            user: 创建者

        Returns:
            Discussion: 创建的讨论对象
        """
        create = _content_discussions_method("create")
        if create is not None:
            return _reload_discussion_for_extension(create(
                title=title,
                content=content,
                user=user,
                extension_payload=extension_payload,
                default_post_type=_get_default_post_type(),
                runtime_model=Discussion,
            ))
        return service_lifecycle.create_discussion(
            title,
            content,
            user,
            extension_payload=extension_payload,
            default_post_type=_get_default_post_type(),
            render_markdown_cb=DiscussionService._render_markdown,
        )

    @staticmethod
    def get_discussion_list(
        q: Optional[str] = None,
        author: Optional[str] = None,
        list_filter: str = 'all',
        sort: str = 'latest',
        page: int = 1,
        limit: int = 20,
        user: Optional[User] = None,
        preload=None,
        query_params: Optional[dict] = None,
    ) -> Tuple[List[Discussion], int]:
        """
        获取讨论列表

        Args:
            q: 搜索关键词
            author: 作者用户名
            sort: 排序方式
            page: 页码
            limit: 每页数量

        Returns:
            Tuple[List[Discussion], int]: (讨论列表, 总数)
        """
        content_list = _content_discussions_method("list")
        if content_list is not None:
            return content_list(
                q=q,
                author=author,
                list_filter=list_filter,
                sort=sort,
                page=page,
                limit=limit,
                user=user,
                preload=preload,
                query_params=query_params,
            )

        page, limit = PaginationService.normalize(page, limit)
        queryset = Discussion.objects.all()
        if preload is not None:
            queryset = preload(queryset)

        queryset = DiscussionService.apply_visibility_filters(queryset, user)

        # 搜索
        if q:
            queryset = _apply_optional_discussion_search(queryset, q, user=user)

        # 按作者过滤
        if author:
            queryset = queryset.filter(user__username=author)

        normalized_query_params = dict(query_params or {})
        active_filters = DiscussionService._discussion_list_active_filters(
            q=q,
            author=author,
            list_filter=list_filter,
            query_params=normalized_query_params,
        )
        query_context = {
            "user": user,
            "query": q,
            "author": author,
            "filter": list_filter,
            "params": normalized_query_params,
            "active_filters": active_filters,
        }
        for query_definition in _get_forum_registry().get_discussion_list_queries():
            queryset = query_definition.applier(
                queryset,
                {
                    **query_context,
                    "key": query_definition.key,
                },
            )

        filter_definition = _get_forum_registry().get_discussion_list_filter(list_filter)
        queryset = filter_definition.applier(
            queryset,
            {
                "user": user,
                "filter": filter_definition.code,
                "query": q,
                "author": author,
                "params": normalized_query_params,
                "active_filters": active_filters,
            },
        )

        # 排序
        sort_definition = _get_forum_registry().get_discussion_sort(sort)
        queryset = sort_definition.applier(
            queryset,
            {
                "user": user,
                "sort": sort_definition.code,
                "query": q,
                "author": author,
                "filter": filter_definition.code,
                "params": normalized_query_params,
                "active_filters": active_filters,
            },
        )
        queryset = get_runtime_resource_registry().apply_named_sort(
            "discussion",
            queryset,
            sort_definition.code,
            {
                "user": user,
                "sort": sort_definition.code,
                "query": q,
                "author": author,
                "filter": filter_definition.code,
                "params": normalized_query_params,
                "active_filters": active_filters,
            },
        )

        # 分页
        queryset = queryset.distinct()
        total = queryset.count()
        offset = (page - 1) * limit
        discussions = list(queryset[offset:offset + limit])

        DiscussionService._attach_user_read_state(discussions, user)

        return discussions, total

    @staticmethod
    def _discussion_list_active_filters(
        *,
        q: Optional[str] = None,
        author: Optional[str] = None,
        list_filter: str = "all",
        query_params: Optional[dict] = None,
    ) -> tuple[str, ...]:
        active: list[str] = []
        params = query_params or {}

        if _has_value(author):
            active.append("author")

        if str(list_filter or "all").strip().lower() != "all":
            active.append("filter")

        active_query_keys = {
            definition.key
            for definition in _get_forum_registry().get_discussion_list_queries()
        }
        for key, value in params.items():
            normalized_key = str(key or "").strip()
            if normalized_key in {"q", "author", "filter", "sort", "page", "limit"}:
                continue
            if normalized_key in active_query_keys and _has_value(value):
                active.append(normalized_key)

        for definition, _parsed_value in _discussion_search_filter_tokens(q):
            code = str(getattr(definition, "code", "") or "").strip()
            active.append(code or "search")

        return tuple(dict.fromkeys(item for item in active if item))

    @staticmethod
    def get_discussion_by_id(
        discussion_id: int,
        user: Optional[User] = None,
        preload=None,
    ) -> Optional[Discussion]:
        """
        获取讨论详情

        Args:
            discussion_id: 讨论ID
            user: 当前用户（用于更新阅读状态）

        Returns:
            Optional[Discussion]: 讨论对象
        """
        content_get_by_id = _content_discussions_method("get_by_id")
        if content_get_by_id is not None:
            return content_get_by_id(
                discussion_id,
                user,
                preload=preload,
                record_view=True,
            )

        try:
            queryset = Discussion.objects.all()
            if preload is not None:
                queryset = preload(queryset)
            discussion = queryset.get(id=discussion_id)

            if not DiscussionService._can_view_discussion(discussion, user):
                return None

            # 增加浏览次数，同一访问者短时间内只计一次，减少热门讨论写压力。
            DiscussionService.record_view(discussion, user)

            # 仅附加当前阅读状态，不在进入讨论页时直接清空未读
            if user and user.is_authenticated:
                state, _ = DiscussionUser.objects.get_or_create(
                    discussion=discussion,
                    user=user,
                    defaults={
                        'last_read_at': timezone.now(),
                        'last_read_post_number': 1 if discussion.last_post_number else 0,
                    }
                )
                DiscussionService._apply_user_read_state(discussion, user, state)
            else:
                discussion.is_subscribed = False
                discussion.last_read_at = None
                discussion.last_read_post_number = 0
                discussion.unread_count = discussion.last_post_number or 0
                discussion.is_unread = discussion.unread_count > 0

            return discussion
        except Discussion.DoesNotExist:
            return None

    @staticmethod
    def _attach_user_read_state(discussions: List[Discussion], user: Optional[User]) -> None:
        attach_read_state = _content_discussions_method("attach_read_state")
        if attach_read_state is not None:
            attach_read_state(discussions, user)
            return
        discussion_tracking.attach_user_read_state(discussions, user)

    @staticmethod
    def _apply_user_read_state(discussion: Discussion, user: User, state: DiscussionUser | None) -> None:
        marked_all_as_read_at = getattr(user, "marked_all_as_read_at", None)
        last_read_at = state.last_read_at if state else None
        last_read_post_number = state.last_read_post_number if state else 0

        if (
            marked_all_as_read_at
            and discussion.last_posted_at
            and discussion.last_posted_at <= marked_all_as_read_at
        ):
            last_read_at = marked_all_as_read_at
            last_read_post_number = max(last_read_post_number, discussion.last_post_number or 0)

        discussion.is_subscribed = bool(state and state.is_subscribed)
        discussion.last_read_at = last_read_at
        discussion.last_read_post_number = last_read_post_number
        discussion.unread_count = max((discussion.last_post_number or 0) - last_read_post_number, 0)
        discussion.is_unread = discussion.unread_count > 0

    @staticmethod
    def mark_all_as_read(user: User):
        mark_all_read = _content_discussions_method("mark_all_read")
        if mark_all_read is not None:
            return mark_all_read(user)
        return discussion_tracking.mark_all_as_read(user)

    @staticmethod
    def update_read_state(
        discussion_id: int,
        user: User,
        last_read_post_number: int,
        *,
        require_view: bool = True,
    ) -> DiscussionUser:
        mark_read = _content_discussions_method("mark_read")
        if mark_read is not None:
            mark_read(
                discussion_id=discussion_id,
                user=user,
                last_read_post_number=last_read_post_number,
                require_view=require_view,
            )
            return DiscussionUser.objects.get(discussion_id=discussion_id, user=user)
        return discussion_tracking.update_read_state(
            discussion_id,
            user,
            last_read_post_number,
            require_view=require_view,
        )

    @staticmethod
    def clamp_read_states(discussion_id: int, last_post_number: int | None = None) -> int:
        clamp = _content_discussions_method("clamp_read_states")
        if clamp is not None:
            return clamp(discussion_id=discussion_id, last_post_number=last_post_number)
        return discussion_tracking.clamp_read_states(discussion_id, last_post_number)

    @staticmethod
    def follow_discussion(
        *,
        discussion_id: int,
        user_id: int,
        last_read_post_number: int | None = None,
    ) -> bool:
        follow = _content_discussions_method("follow_if_enabled")
        if follow is not None:
            return bool(follow(
                discussion_id=discussion_id,
                user_id=user_id,
                last_read_post_number=last_read_post_number,
            ))
        return discussion_tracking.follow_discussion(
            discussion_id=discussion_id,
            user_id=user_id,
            last_read_post_number=last_read_post_number,
        )

    @staticmethod
    def set_subscription(discussion_id: int, user: User, subscribed: bool) -> bool:
        set_subscription = _content_discussions_method("set_subscription")
        if set_subscription is not None:
            return bool(set_subscription(discussion_id, user, subscribed))
        return discussion_tracking.set_subscription(discussion_id, user, subscribed)

    @staticmethod
    def update_discussion(
        discussion_id: int,
        user: User,
        title: Optional[str] = None,
        content: Optional[str] = None,
        extension_payload: Optional[dict[str, Any]] = None,
        is_locked: Optional[bool] = None,
        is_sticky: Optional[bool] = None,
        is_hidden: Optional[bool] = None,
    ) -> Discussion:
        """
        更新讨论

        Args:
            discussion_id: 讨论ID
            user: 操作用户
            title: 新标题
            is_locked: 是否锁定
            is_sticky: 是否置顶
            is_hidden: 是否隐藏

        Returns:
            Discussion: 更新后的讨论对象

        Raises:
            PermissionDenied: 权限不足
        """
        update = _content_discussions_method("update")
        if update is not None:
            return _reload_discussion_for_extension(update(
                discussion_id,
                user,
                title=title,
                content=content,
                extension_payload=extension_payload,
                is_locked=is_locked,
                is_sticky=is_sticky,
                is_hidden=is_hidden,
                can_rename_discussion_cb=DiscussionService.can_rename_discussion,
                can_edit_discussion_cb=DiscussionService.can_edit_discussion,
                can_hide_discussion_cb=DiscussionService.can_hide_discussion,
                runtime_model=Discussion,
            ))
        return service_lifecycle.update_discussion(
            discussion_id,
            user,
            title=title,
            content=content,
            extension_payload=extension_payload,
            is_locked=is_locked,
            is_sticky=is_sticky,
            is_hidden=is_hidden,
            can_rename_discussion_cb=DiscussionService.can_rename_discussion,
            can_edit_discussion_cb=DiscussionService.can_edit_discussion,
            can_hide_discussion_cb=DiscussionService.can_hide_discussion,
            render_markdown_cb=DiscussionService._render_markdown,
            set_locked_state_cb=DiscussionService.set_locked_state,
            set_sticky_state_cb=DiscussionService.set_sticky_state,
            set_hidden_state_cb=DiscussionService.set_hidden_state,
        )

    @staticmethod
    def set_hidden_state(discussion: Discussion, user: User, is_hidden: bool) -> Discussion:
        if not DiscussionService.can_hide_discussion(discussion, user):
            raise PermissionDenied("没有权限隐藏/显示讨论")
        set_hidden = _content_discussions_method("set_hidden_state")
        if set_hidden is not None:
            return _reload_discussion_for_extension(set_hidden(
                discussion,
                user,
                is_hidden,
                user_counted_post_types=_get_user_counted_post_types(),
                runtime_model=Discussion,
            ))
        return service_lifecycle.set_hidden_state(
            discussion,
            user,
            is_hidden,
            approved_reply_counts_by_author_cb=DiscussionService._approved_reply_counts_by_author,
        )

    @staticmethod
    def approve_discussion(discussion: Discussion, admin_user: User, note: str = "") -> Discussion:
        approve = _content_discussions_method("approve")
        if approve is not None:
            return _reload_discussion_for_extension(approve(
                discussion.id,
                admin_user,
                note=note,
                user_counted_post_types=_get_user_counted_post_types(),
                runtime_model=Discussion,
            ))
        return service_lifecycle.approve_discussion(
            discussion,
            admin_user,
            note=note,
            approved_reply_counts_by_author_cb=DiscussionService._approved_reply_counts_by_author,
        )

    @staticmethod
    def reject_discussion(discussion: Discussion, admin_user: User, note: str = "") -> Discussion:
        reject = _content_discussions_method("reject")
        if reject is not None:
            return _reload_discussion_for_extension(reject(
                discussion.id,
                admin_user,
                note=note,
                user_counted_post_types=_get_user_counted_post_types(),
                runtime_model=Discussion,
            ))
        return service_lifecycle.reject_discussion(
            discussion,
            admin_user,
            note=note,
            approved_reply_counts_by_author_cb=DiscussionService._approved_reply_counts_by_author,
        )

    @staticmethod
    def _approved_reply_counts_by_author(discussion: Discussion) -> dict:
        return service_lifecycle.approved_reply_counts_by_author(
            discussion,
            user_counted_post_types=_get_user_counted_post_types(),
        )

    @staticmethod
    def delete_discussion(discussion_id: int, user: User) -> bool:
        """
        删除讨论

        Args:
            discussion_id: 讨论ID
            user: 操作用户

        Returns:
            bool: 是否删除成功

        Raises:
            PermissionDenied: 权限不足
        """
        delete = _content_discussions_method("delete")
        if delete is not None:
            return bool(delete(
                discussion_id,
                user,
                can_delete_discussion_cb=DiscussionService.can_delete_discussion,
                user_counted_post_types=_get_user_counted_post_types(),
            ))
        return service_lifecycle.delete_discussion(
            discussion_id,
            user,
            can_delete_discussion_cb=DiscussionService.can_delete_discussion,
            approved_reply_counts_by_author_cb=DiscussionService._approved_reply_counts_by_author,
        )

    @staticmethod
    def set_locked_state(discussion: Discussion, actor: User, is_locked: bool) -> Discussion:
        return service_lifecycle.set_locked_state(discussion, actor, is_locked)

    @staticmethod
    def set_sticky_state(discussion: Discussion, actor: User, is_sticky: bool) -> Discussion:
        return service_lifecycle.set_sticky_state(discussion, actor, is_sticky)

    @staticmethod
    def can_edit_discussion(discussion: Discussion, user: User) -> bool:
        """检查用户是否可以编辑讨论"""
        if not user or not user.is_authenticated:
            return False
        if user.is_suspended:
            return False
        allowed = False
        if has_forum_permission(user, "discussion.edit"):
            allowed = True
        elif discussion.user_id == user.id:
            allowed = (
                discussion.approval_status == Discussion.APPROVAL_REJECTED
                or has_forum_permission(user, "discussion.editOwn")
            )
        model_policy = evaluate_runtime_model_policy(
            "edit",
            user=user,
            model=discussion,
            default=allowed,
            discussion=discussion,
        )
        if model_policy is False:
            return False
        allowed = bool(model_policy)
        return bool(evaluate_extension_policy(
            "discussion.edit",
            default=allowed,
            user=user,
            discussion=discussion,
        ))

    @staticmethod
    def can_rename_discussion(discussion: Discussion, user: User) -> bool:
        """检查用户是否可以修改讨论标题"""
        if not user or not user.is_authenticated:
            return False
        if user.is_suspended:
            return False
        allowed = False
        if has_forum_permission(user, "discussion.rename"):
            allowed = True
        elif discussion.user_id == user.id:
            allowed = (
                has_forum_permission(user, "discussion.reply")
                and DiscussionService._author_can_rename_discussion(discussion)
            )
        model_policy = evaluate_runtime_model_policy(
            "rename",
            user=user,
            model=discussion,
            default=allowed,
            discussion=discussion,
        )
        if model_policy is False:
            return False
        allowed = bool(model_policy)
        return bool(evaluate_extension_policy(
            "discussion.rename",
            default=allowed,
            user=user,
            discussion=discussion,
        ))

    @staticmethod
    def can_hide_discussion(discussion: Discussion, user: User) -> bool:
        """检查用户是否可以隐藏或恢复讨论"""
        if not user or not user.is_authenticated:
            return False
        if user.is_suspended:
            return False
        allowed = False
        if has_forum_permission(user, "discussion.hide"):
            allowed = True
        elif discussion.user_id == user.id:
            allowed = (
                has_forum_permission(user, "discussion.reply")
                and DiscussionService._author_can_hide_discussion(discussion, user)
            )
        model_policy = evaluate_runtime_model_policy(
            "hide",
            user=user,
            model=discussion,
            default=allowed,
            discussion=discussion,
        )
        if model_policy is False:
            return False
        allowed = bool(model_policy)
        return bool(evaluate_extension_policy(
            "discussion.hide",
            default=allowed,
            user=user,
            discussion=discussion,
        ))

    @staticmethod
    def _author_can_rename_discussion(discussion: Discussion) -> bool:
        allow_renaming = str(
            get_extension_settings("discussions").get("allow_renaming", "reply") or "reply"
        ).strip()
        if allow_renaming == "-1":
            return True
        if allow_renaming == "reply":
            return getattr(discussion, "participant_count", 0) <= 1
        try:
            allowed_minutes = int(allow_renaming)
        except (TypeError, ValueError):
            return False
        created_at = getattr(discussion, "created_at", None)
        if created_at is None:
            return False
        return timezone.now() - created_at < timezone.timedelta(minutes=allowed_minutes)

    @staticmethod
    def _author_can_hide_discussion(discussion: Discussion, user: User) -> bool:
        if getattr(discussion, "participant_count", 0) > 1:
            return False
        hidden_user_id = getattr(discussion, "hidden_user_id", None)
        if getattr(discussion, "hidden_at", None) is not None and hidden_user_id != getattr(user, "id", None):
            return False
        return True

    @staticmethod
    def can_delete_discussion(discussion: Discussion, user: User) -> bool:
        """检查用户是否可以删除讨论"""
        if not user or not user.is_authenticated:
            return False
        if user.is_suspended:
            return False
        allowed = False
        if has_forum_permission(user, "discussion.delete"):
            allowed = True
        elif discussion.user_id == user.id:
            allowed = has_forum_permission(user, "discussion.deleteOwn")
        model_policy = evaluate_runtime_model_policy(
            "delete",
            user=user,
            model=discussion,
            default=allowed,
            discussion=discussion,
        )
        if model_policy is False:
            return False
        allowed = bool(model_policy)
        return bool(evaluate_extension_policy(
            "discussion.delete",
            default=allowed,
            user=user,
            discussion=discussion,
        ))

    @staticmethod
    def can_reply_discussion(discussion: Discussion, user: User) -> bool:
        """检查用户是否可以回复讨论"""
        if not user or not user.is_authenticated:
            return False
        if user.is_suspended:
            return False
        if not has_forum_permission(user, "discussion.reply"):
            return False
        if (
            discussion.approval_status != Discussion.APPROVAL_APPROVED
            and not has_forum_permission(user, ("discussion.lock", "discussion.sticky"))
        ):
            return False
        if discussion.is_locked and not has_forum_permission(user, "discussion.lock"):
            return False
        if evaluate_runtime_model_policy(
            "reply",
            user=user,
            model=discussion,
            default=True,
            discussion=discussion,
        ) is False:
            return False
        return bool(evaluate_extension_policy(
            "discussion.reply",
            default=True,
            user=user,
            discussion=discussion,
        ))

    @staticmethod
    def _render_markdown(content: str) -> str:
        """
        渲染Markdown为HTML

        Args:
            content: Markdown内容

        Returns:
            str: HTML内容
        """
        from bias_core.extensions.platform import MarkdownService
        return MarkdownService.render(content, sanitize=True)


def _discussion_search_filter_tokens(query: str | None) -> tuple[tuple[Any, Any], ...]:
    if not _has_value(query):
        return ()
    search_service = get_extension_host_service("search")
    extractor = getattr(search_service, "extract_filter_tokens", None)
    if not callable(extractor):
        return ()
    try:
        _text_query, filters = extractor(query, targets=("discussion",))
    except Exception:
        return ()
    return tuple(filters.get("discussion", ()) or ())


def _apply_optional_discussion_search(queryset, query: str, *, user: Any = None):
    search_service = get_extension_host_service("search.service")
    applier = None
    if isinstance(search_service, dict):
        applier = search_service.get("apply_discussion_search")
    else:
        applier = getattr(search_service, "apply_discussion_search", None)
    if callable(applier):
        try:
            return applier(queryset, query, user=user)
        except Exception:
            return queryset.filter(title__icontains=query)
    return queryset.filter(title__icontains=query)


def _has_value(value) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_has_value(item) for item in value)
    return bool(str(value or "").strip())
