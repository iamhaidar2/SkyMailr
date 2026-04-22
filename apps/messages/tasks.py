import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.messages.models import MessageEvent, MessageEventType, OutboundMessage, OutboundStatus
from apps.messages.services.dispatch import EmailDispatchService
from apps.messages.services.throttling import (
    calculate_next_send_time,
    can_send_now,
    record_send_attempt,
)

logger = logging.getLogger(__name__)

TRANSIENT_RETRY_MAX = 8


@shared_task(bind=True, max_retries=TRANSIENT_RETRY_MAX)
def dispatch_message_task(self, message_id: str):
    """Send a single outbound message via the configured provider."""
    try:
        msg = OutboundMessage.objects.select_related("tenant", "sender_profile").prefetch_related(
            "tenant__domains"
        ).get(pk=message_id)
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

    with transaction.atomic():
        allowed, next_when, reason = can_send_now(msg)
        if not allowed:
            when = next_when or calculate_next_send_time(msg)
            msg.status = OutboundStatus.DEFERRED
            msg.next_retry_at = when
            msg.last_error = reason[:2000]
            msg.save(update_fields=["status", "next_retry_at", "last_error", "updated_at"])
            MessageEvent.objects.create(
                message=msg,
                event_type=MessageEventType.DEFERRED,
                payload={"reason": reason, "next_retry_at": when.isoformat()},
            )
            return
        if not record_send_attempt(msg):
            when = calculate_next_send_time(msg)
            msg.status = OutboundStatus.DEFERRED
            msg.next_retry_at = when
            msg.last_error = "rate_limited: capacity race; retry later"
            msg.save(update_fields=["status", "next_retry_at", "last_error", "updated_at"])
            MessageEvent.objects.create(
                message=msg,
                event_type=MessageEventType.DEFERRED,
                payload={"reason": "rate_limited: capacity race", "next_retry_at": when.isoformat()},
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
    ).order_by("priority", "send_after", "created_at")[:200]
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
