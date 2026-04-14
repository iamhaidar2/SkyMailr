import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.messages.models import OutboundMessage, OutboundStatus
from apps.messages.services.dispatch import EmailDispatchService

logger = logging.getLogger(__name__)

TRANSIENT_RETRY_MAX = 8


@shared_task(bind=True, max_retries=TRANSIENT_RETRY_MAX)
def dispatch_message_task(self, message_id: str):
    """Send a single outbound message via the configured provider."""
    try:
        msg = OutboundMessage.objects.select_related("tenant", "sender_profile").get(
            pk=message_id
        )
    except OutboundMessage.DoesNotExist:
        logger.warning("dispatch_message_task: missing message %s", message_id)
        return

    if msg.status not in (OutboundStatus.QUEUED, OutboundStatus.DEFERRED):
        return

    if msg.send_after and msg.send_after > timezone.now():
        dispatch_message_task.apply_async(
            args=[str(msg.id)], eta=msg.send_after
        )
        return

    try:
        EmailDispatchService().dispatch(msg)
    except Exception as exc:
        logger.exception("dispatch failed for %s", message_id)
        msg.retry_count += 1
        msg.status = OutboundStatus.DEFERRED
        delay = min(300, 2 ** min(msg.retry_count, 8))
        msg.next_retry_at = timezone.now() + timedelta(seconds=delay)
        msg.last_error = str(exc)[:2000]
        msg.save(
            update_fields=[
                "retry_count",
                "status",
                "next_retry_at",
                "last_error",
                "updated_at",
            ]
        )
        raise self.retry(exc=exc, countdown=delay)


@shared_task
def sweep_dispatch_queue():
    """Pick up queued messages that are due."""
    now = timezone.now()
    qs = OutboundMessage.objects.filter(
        status=OutboundStatus.QUEUED,
        send_after__lte=now,
    ).order_by("send_after")[:200]
    for msg in qs:
        dispatch_message_task.delay(str(msg.id))


@shared_task
def retry_due_deferred():
    now = timezone.now()
    for msg in OutboundMessage.objects.filter(
        status=OutboundStatus.DEFERRED,
        next_retry_at__lte=now,
    )[:100]:
        msg.status = OutboundStatus.QUEUED
        msg.save(update_fields=["status", "updated_at"])
        dispatch_message_task.delay(str(msg.id))
