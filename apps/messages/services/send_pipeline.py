import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.email_templates.models import EmailTemplate, TemplateCategory
from apps.email_templates.services.render_service import render_email_version, TemplateRenderError
from apps.email_templates.services.validation_service import TemplateValidationService
from apps.messages.models import (
    MessageEvent,
    MessageEventType,
    MessagePriority,
    MessageType,
    OutboundMessage,
    OutboundStatus,
)
from apps.accounts.services.enforcement import assert_send_allowed
from apps.subscriptions.services.suppression import SuppressionService
from apps.tenants.models import SenderProfile, Tenant

logger = logging.getLogger(__name__)


def _queue_dispatch_if_ready(msg: OutboundMessage) -> None:
    """Enqueue Celery dispatch for messages ready to send (API, UI, workflows)."""
    if msg.status != OutboundStatus.QUEUED:
        return
    # Local import avoids import cycles (tasks may import this module).
    from apps.messages.tasks import dispatch_message_task

    dispatch_message_task.delay(str(msg.id))


def _priority_for(message_type: str) -> int:
    mapping = {
        MessageType.TRANSACTIONAL.value: MessagePriority.NORMAL_TX,
        MessageType.SYSTEM.value: MessagePriority.CRITICAL_TX,
        MessageType.LIFECYCLE.value: MessagePriority.LIFECYCLE,
        MessageType.MARKETING.value: MessagePriority.MARKETING,
    }
    return mapping.get(message_type, MessagePriority.NORMAL_TX)


def should_suppress(tenant: Tenant, to_email: str, message_type: str) -> tuple[bool, str]:
    if SuppressionService.is_globally_suppressed(to_email):
        return True, "global_suppression"
    marketing = message_type in (
        MessageType.MARKETING.value,
        MessageType.LIFECYCLE.value,
    )
    if marketing:
        if SuppressionService.is_unsubscribed_marketing(tenant, to_email):
            return True, "unsubscribed_marketing"
        if SuppressionService.is_tenant_suppressed(tenant, to_email, marketing=True):
            return True, "suppressed_marketing"
    else:
        if SuppressionService.is_tenant_suppressed(tenant, to_email, marketing=False):
            return True, "suppressed_transactional"
    return False, ""


def render_message_body(
    template: EmailTemplate, context: dict[str, Any]
) -> dict[str, str]:
    TemplateValidationService.validate_context(template, context)
    version = template.current_approved_version
    if not version:
        raise ValueError("Template has no approved version")
    footer = ""
    if template.category in (
        TemplateCategory.MARKETING,
        TemplateCategory.LIFECYCLE,
    ):
        footer = (template.tenant.compliance_footer_html or "").strip()
    html = version.html_template
    if footer and "</body>" in html.lower():
        html = html.replace("</body>", f"{footer}</body>", 1)
    elif footer:
        html = html + footer
    return render_email_version(
        subject_template=version.subject_template,
        preview_template=version.preview_text_template,
        html_template=html,
        text_template=version.text_template,
        context=context,
        sanitize=True,
    )


@transaction.atomic
def create_templated_message(
    *,
    tenant: Tenant,
    template: EmailTemplate,
    source_app: str,
    message_type: str,
    to_email: str,
    to_name: str,
    context: dict[str, Any],
    metadata: dict[str, Any] | None,
    tags: dict[str, Any] | None,
    idempotency_key: str | None,
    scheduled_for=None,
    sender_profile: SenderProfile | None = None,
    workflow_execution=None,
    bypass_quota: bool = False,
    bypass_suspension: bool = False,
    bypass_sending_pause: bool = False,
    bypass_domain_verification: bool = False,
) -> OutboundMessage:
    assert_send_allowed(
        tenant,
        message_type=message_type,
        bypass_quota=bypass_quota,
        bypass_suspension=bypass_suspension,
        bypass_sending_pause=bypass_sending_pause,
    )
    suppressed, reason = should_suppress(tenant, to_email, message_type)
    status = OutboundStatus.SUPPRESSED if suppressed else OutboundStatus.QUEUED
    version = template.current_approved_version
    if not version:
        raise ValueError("Template has no approved active version")

    meta = dict(metadata or {})
    if bypass_domain_verification:
        meta["bypass_domain_verification"] = True

    msg = OutboundMessage.objects.create(
        tenant=tenant,
        source_app=source_app,
        message_type=message_type,
        template=template,
        template_version=version,
        sender_profile=sender_profile,
        to_email=to_email,
        to_name=to_name or "",
        metadata=meta,
        tags=tags or {},
        priority=_priority_for(message_type),
        scheduled_for=scheduled_for,
        status=status,
        idempotency_key=idempotency_key or "",
        workflow_execution=workflow_execution,
    )
    if suppressed:
        MessageEvent.objects.create(
            message=msg,
            event_type=MessageEventType.SUPPRESSED,
            payload={"reason": reason},
        )
        return msg

    try:
        rendered = render_message_body(template, context)
    except (TemplateRenderError, ValueError) as e:
        msg.status = OutboundStatus.FAILED
        msg.last_error = str(e)
        msg.save(update_fields=["status", "last_error", "updated_at"])
        MessageEvent.objects.create(
            message=msg,
            event_type=MessageEventType.FAILED,
            payload={"error": str(e)},
        )
        # Do not re-raise: @transaction.atomic would roll back the FAILED row and break idempotency.

    if msg.status == OutboundStatus.FAILED:
        return msg

    msg.subject_rendered = rendered["subject"]
    msg.html_rendered = rendered["html"]
    msg.text_rendered = rendered["text"]
    msg.status = OutboundStatus.RENDERED
    msg.save(
        update_fields=[
            "subject_rendered",
            "html_rendered",
            "text_rendered",
            "status",
            "updated_at",
        ]
    )
    MessageEvent.objects.create(
        message=msg,
        event_type=MessageEventType.RENDERED,
        payload={"preview": rendered.get("preview", "")},
    )
    apply_send_schedule(msg)
    _queue_dispatch_if_ready(msg)
    return msg


def apply_send_schedule(msg: OutboundMessage) -> None:
    """Move RENDERED -> QUEUED when ready to enter Celery dispatch."""
    when = msg.scheduled_for or timezone.now()
    if msg.status != OutboundStatus.RENDERED:
        return
    msg.scheduled_for = when
    msg.status = OutboundStatus.QUEUED
    msg.send_after = when
    msg.save(update_fields=["scheduled_for", "send_after", "status", "updated_at"])
    MessageEvent.objects.create(message=msg, event_type=MessageEventType.QUEUED, payload={})


@transaction.atomic
def create_raw_message(
    *,
    tenant: Tenant,
    source_app: str,
    message_type: str,
    to_email: str,
    to_name: str,
    subject: str,
    html_body: str,
    text_body: str,
    metadata: dict[str, Any] | None,
    idempotency_key: str | None,
    scheduled_for=None,
    sender_profile: SenderProfile | None = None,
    bypass_quota: bool = False,
    bypass_suspension: bool = False,
    bypass_sending_pause: bool = False,
    bypass_domain_verification: bool = False,
) -> OutboundMessage:
    from apps.email_templates.services.render_service import sanitize_html

    assert_send_allowed(
        tenant,
        message_type=message_type,
        bypass_quota=bypass_quota,
        bypass_suspension=bypass_suspension,
        bypass_sending_pause=bypass_sending_pause,
    )
    suppressed, reason = should_suppress(tenant, to_email, message_type)
    status = OutboundStatus.SUPPRESSED if suppressed else OutboundStatus.QUEUED
    meta = dict(metadata or {})
    if bypass_domain_verification:
        meta["bypass_domain_verification"] = True

    msg = OutboundMessage.objects.create(
        tenant=tenant,
        source_app=source_app,
        message_type=message_type,
        template=None,
        template_version=None,
        sender_profile=sender_profile,
        to_email=to_email,
        to_name=to_name or "",
        metadata=meta,
        tags={},
        priority=_priority_for(message_type),
        scheduled_for=scheduled_for,
        status=status,
        idempotency_key=idempotency_key or "",
    )
    if suppressed:
        MessageEvent.objects.create(
            message=msg,
            event_type=MessageEventType.SUPPRESSED,
            payload={"reason": reason},
        )
        return msg
    msg.subject_rendered = subject
    msg.html_rendered = sanitize_html(html_body)
    msg.text_rendered = text_body or ""
    msg.status = OutboundStatus.RENDERED
    msg.save(
        update_fields=[
            "subject_rendered",
            "html_rendered",
            "text_rendered",
            "status",
            "updated_at",
        ]
    )
    MessageEvent.objects.create(message=msg, event_type=MessageEventType.RENDERED, payload={})
    apply_send_schedule(msg)
    _queue_dispatch_if_ready(msg)
    return msg
