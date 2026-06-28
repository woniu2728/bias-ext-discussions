from celery import shared_task


@shared_task(ignore_result=True)
def flush_discussion_view_count_task(discussion_id: int):
    from bias_ext_discussions.backend.services import DiscussionService

    return DiscussionService.flush_pending_view_count(int(discussion_id))
