import logging

from apps.messages.models import MessageEvent, MessageEventType, OutboundMessage, OutboundStatus
from apps.providers.base import EmailMessageDTO
from apps.providers.registry import get_email_provider
from apps.tenants.services.domain_verification import dispatch_should_block_unverified_managed_domain

logger = logging.getLogger(__name__)


class EmailDispatchService:
    """Provider-facing send — called only from Celery (deterministic)."""

    def dispatch(self, message: OutboundMessage) -> None:
        tenant = message.tenant
        profile = message.sender_profile
        from_email = profile.from_email if profile else tenant.default_sender_email
        from_name = profile.from_name if profile else tenant.default_sender_name
        reply_to = profile.reply_to if profile and profile.reply_to else tenant.reply_to

        blocked, block_reason = dispatch_should_block_unverified_managed_domain(message)
        if blocked:
            message.status = OutboundStatus.FAILED
            message.last_error = block_reason
            message.retry_count += 1
            message.save(
                update_fields=["status", "last_error", "retry_count", "updated_at"]
            )
            MessageEvent.objects.create(
                message=message,
                event_type=MessageEventType.FAILED,
                payload={"code": "unverified_sending_domain", "detail": block_reason},
            )
            return

        dto = EmailMessageDTO(
            to_email=message.to_email,
            to_name=message.to_name,
            from_email=from_email or "noreply@localhost",
            from_name=from_name or tenant.name,
            reply_to=reply_to or "",
            subject=message.subject_rendered,
            html_body=message.html_rendered,
            text_body=message.text_rendered,
            cc=message.cc or [],
            bcc=message.bcc or [],
        )

        provider = get_email_provider()
        message.provider_name = provider.name
        message.status = OutboundStatus.SENDING
        message.save(update_fields=["provider_name", "status", "updated_at"])

        result = provider.send_message(dto)
        if result.success:
            message.status = OutboundStatus.SENT
            message.provider_message_id = result.provider_message_id
            message.save(
                update_fields=["status", "provider_message_id", "updated_at"]
            )
            MessageEvent.objects.create(
                message=message,
                event_type=MessageEventType.SENT,
                payload=result.raw_response,
            )
        else:
            message.status = OutboundStatus.FAILED
            message.last_error = result.error_detail or result.error_code
            message.retry_count += 1
            message.save(
                update_fields=[
                    "status",
                    "last_error",
                    "retry_count",
                    "updated_at",
                ]
            )
            MessageEvent.objects.create(
                message=message,
                event_type=MessageEventType.FAILED,
                payload={"code": result.error_code, "detail": result.error_detail},
            )


class ProviderRouter:
    """Explicit hook for future multi-provider routing."""

    def get(self):
        return get_email_provider()
