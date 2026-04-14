"""Shared outbound message actions for API and operator UI."""

from apps.messages.models import OutboundMessage, OutboundStatus
from apps.messages.tasks import dispatch_message_task


def retry_outbound_message(msg: OutboundMessage) -> OutboundMessage:
    if msg.status not in (OutboundStatus.FAILED, OutboundStatus.DEFERRED):
        raise ValueError("Not retryable")
    msg.status = OutboundStatus.QUEUED
    msg.next_retry_at = None
    msg.save(update_fields=["status", "next_retry_at", "updated_at"])
    dispatch_message_task.delay(str(msg.id))
    return msg


def cancel_outbound_message(msg: OutboundMessage) -> None:
    if msg.status not in (
        OutboundStatus.QUEUED,
        OutboundStatus.RENDERED,
        OutboundStatus.DEFERRED,
    ):
        raise ValueError("Cannot cancel")
    msg.status = OutboundStatus.CANCELLED
    msg.save(update_fields=["status", "updated_at"])
