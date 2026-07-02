from __future__ import annotations

from django.db import models
from django.db.models.functions import Coalesce


def apply_discussion_latest_sort(queryset, context: dict):
    return queryset.order_by("-is_sticky", "-last_posted_at", "-id")


def apply_discussion_top_sort(queryset, context: dict):
    return queryset.order_by("-is_sticky", "-comment_count", "-view_count", "-last_posted_at", "-id")


def apply_discussion_oldest_sort(queryset, context: dict):
    return queryset.order_by("-is_sticky", "created_at", "id")


def apply_discussion_newest_sort(queryset, context: dict):
    return queryset.order_by("-is_sticky", "-created_at", "-id")


def apply_discussion_unanswered_sort(queryset, context: dict):
    return queryset.order_by("-is_sticky", "comment_count", "-created_at", "-id")


def apply_all_discussion_list_filter(queryset, context: dict):
    return queryset


def apply_my_discussions_list_filter(queryset, context: dict):
    user = context.get("user")
    if not user or not getattr(user, "is_authenticated", False):
        return queryset.none()
    return queryset.filter(user=user)


def apply_unread_discussions_list_filter(queryset, context: dict):
    user = context.get("user")
    if not user or not getattr(user, "is_authenticated", False):
        return queryset.none()

    queryset = queryset.filter(last_post_number__gt=0)
    marked_all_as_read_at = getattr(user, "marked_all_as_read_at", None)
    if marked_all_as_read_at is not None:
        queryset = queryset.filter(last_posted_at__gt=marked_all_as_read_at)

    state_model = queryset.model._meta.get_field("user_states").related_model
    last_read_subquery = state_model.objects.filter(
        user=user,
        discussion_id=models.OuterRef("pk"),
    ).values("last_read_post_number")[:1]
    return queryset.annotate(
        current_user_last_read_post_number=Coalesce(
            models.Subquery(last_read_subquery, output_field=models.IntegerField()),
            models.Value(0),
        ),
    ).filter(last_post_number__gt=models.F("current_user_last_read_post_number"))

