"""Tenant sending pause, automated risk rules, and enforcement."""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.policy import PolicyError
from apps.accounts.services.enforcement import assert_send_allowed
from apps.messages.models import MessageType, OutboundMessage, OutboundStatus
from apps.messages.services.dispatch import EmailDispatchService
from apps.messages.services.send_pipeline import create_templated_message
from apps.tenants.models import SendingPauseScope, SendingPauseSource, Tenant
from apps.tenants.services.sending_risk import apply_automated_risk_pause, message_type_blocked_by_sending_pause


def _seed_sent_path_messages(
    tenant: Tenant,
    *,
    delivered: int = 0,
    bounced: int = 0,
    complained: int = 0,
    failed: int = 0,
    sent: int = 0,
):
    """Messages counted in 24h deliverability / risk denominator (updated_at in window)."""
    now = timezone.now()
    idx = 0

    def one(status: str):
        nonlocal idx
        idx += 1
        m = OutboundMessage.objects.create(
            tenant=tenant,
            source_app="risk_test",
            message_type=MessageType.TRANSACTIONAL.value,
            to_email=f"risk{idx}@example.com",
            status=status,
            subject_rendered="s",
            html_rendered="<p>x</p>",
            text_rendered="x",
        )
        OutboundMessage.objects.filter(pk=m.pk).update(updated_at=now)
        return m

    for _ in range(sent):
        one(OutboundStatus.SENT.value)
    for _ in range(delivered):
        one(OutboundStatus.DELIVERED.value)
    for _ in range(bounced):
        one(OutboundStatus.BOUNCED.value)
    for _ in range(complained):
        one(OutboundStatus.COMPLAINED.value)
    for _ in range(failed):
        one(OutboundStatus.FAILED.value)


@pytest.mark.django_db
def test_high_bounce_rate_triggers_auto_pause_marketing_scope(tenant):
    # 30 bounced / 100 sent-path = 30% > 5% threshold
    _seed_sent_path_messages(tenant, delivered=70, bounced=30)
    out = apply_automated_risk_pause(tenant)
    tenant.refresh_from_db()
    assert out["updated"] == "paused"
    assert tenant.sending_paused is True
    assert tenant.sending_pause_scope == SendingPauseScope.MARKETING_LIFECYCLE
    assert tenant.sending_pause_source == SendingPauseSource.AUTO


@pytest.mark.django_db
def test_severe_complaint_triggers_non_critical_pause(tenant):
    _seed_sent_path_messages(tenant, delivered=185, complained=15)
    apply_automated_risk_pause(tenant)
    tenant.refresh_from_db()
    assert tenant.sending_paused is True
    assert tenant.sending_pause_scope == SendingPauseScope.NON_CRITICAL


@pytest.mark.django_db
def test_high_complaint_rate_triggers_auto_pause(tenant):
    # 5 complaints / 1000 = 0.5% > 0.3% marketing threshold
    _seed_sent_path_messages(tenant, delivered=995, complained=5)
    apply_automated_risk_pause(tenant)
    tenant.refresh_from_db()
    assert tenant.sending_paused is True
    assert tenant.sending_pause_source == SendingPauseSource.AUTO


@pytest.mark.django_db
def test_paused_tenant_api_send_blocked(api_key, tenant, approved_template):
    tpl, _ = approved_template
    tenant.sending_paused = True
    tenant.sending_pause_scope = SendingPauseScope.MARKETING_LIFECYCLE
    tenant.sending_pause_source = SendingPauseSource.MANUAL
    tenant.sending_pause_reason = "test pause"
    tenant.save()

    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r = c.post(
        "/api/v1/messages/send-template/",
        {
            "template_key": "email_verification",
            "to_email": "u@example.com",
            "context": {"user_name": "Bob"},
            "source_app": "tests",
            "message_type": "marketing",
        },
        format="json",
    )
    assert r.status_code == 403
    assert r.json().get("code") == "sending_paused_marketing"


@pytest.mark.django_db
def test_marketing_pause_allows_transactional_api(api_key, tenant, approved_template):
    from apps.email_templates.models import TemplateVariable

    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=False)
    tenant.sending_paused = True
    tenant.sending_pause_scope = SendingPauseScope.MARKETING_LIFECYCLE
    tenant.sending_pause_source = SendingPauseSource.MANUAL
    tenant.save()

    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r = c.post(
        "/api/v1/messages/send-template/",
        {
            "template_key": "email_verification",
            "to_email": "tx@example.com",
            "context": {"user_name": "Bob"},
            "source_app": "tests",
            "message_type": "transactional",
        },
        format="json",
    )
    assert r.status_code == 201


@pytest.mark.django_db
def test_staff_bypass_sending_pause(tenant, approved_template):
    from apps.email_templates.models import TemplateVariable

    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=False)
    tenant.sending_paused = True
    tenant.sending_pause_scope = SendingPauseScope.MARKETING_LIFECYCLE
    tenant.sending_pause_source = SendingPauseSource.MANUAL
    tenant.sending_pause_reason = "hold"
    tenant.save()
    msg = create_templated_message(
        tenant=tenant,
        template=tpl,
        source_app="t",
        message_type=MessageType.MARKETING.value,
        to_email="m@example.com",
        to_name="",
        context={"user_name": "A"},
        metadata={},
        tags={},
        idempotency_key=None,
        bypass_sending_pause=True,
    )
    assert msg.status != OutboundStatus.SUPPRESSED


@pytest.mark.django_db
def test_resume_allows_send(api_key, tenant, approved_template):
    from apps.email_templates.models import TemplateVariable

    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=False)
    tenant.sending_paused = True
    tenant.sending_pause_scope = SendingPauseScope.MARKETING_LIFECYCLE
    tenant.sending_pause_source = SendingPauseSource.MANUAL
    tenant.save()

    Tenant.objects.filter(pk=tenant.pk).update(
        sending_paused=False,
        sending_pause_reason="",
        sending_pause_source=None,
        sending_pause_scope=SendingPauseScope.MARKETING_LIFECYCLE,
    )

    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r = c.post(
        "/api/v1/messages/send-template/",
        {
            "template_key": "email_verification",
            "to_email": "u2@example.com",
            "context": {"user_name": "Bob"},
            "source_app": "tests",
            "message_type": "marketing",
        },
        format="json",
    )
    assert r.status_code == 201


@pytest.mark.django_db
def test_non_critical_pause_blocks_transactional_not_system(tenant):
    tenant.sending_paused = True
    tenant.sending_pause_scope = SendingPauseScope.NON_CRITICAL
    tenant.sending_pause_source = SendingPauseSource.MANUAL
    tenant.save()

    assert message_type_blocked_by_sending_pause(tenant, MessageType.TRANSACTIONAL.value)[0] is True
    assert message_type_blocked_by_sending_pause(tenant, MessageType.SYSTEM.value)[0] is False


@pytest.mark.django_db
def test_dispatch_fails_when_non_critical_paused(tenant):
    tenant.default_sender_email = "noreply@example.com"
    tenant.sending_paused = True
    tenant.sending_pause_scope = SendingPauseScope.NON_CRITICAL
    tenant.sending_pause_source = SendingPauseSource.MANUAL
    tenant.save()

    msg = OutboundMessage.objects.create(
        tenant=tenant,
        source_app="t",
        message_type=MessageType.TRANSACTIONAL.value,
        to_email="x@example.com",
        status=OutboundStatus.QUEUED,
        subject_rendered="Hi",
        html_rendered="<p>Hi</p>",
        text_rendered="Hi",
    )
    EmailDispatchService().dispatch(msg)
    msg.refresh_from_db()
    assert msg.status == OutboundStatus.FAILED
    assert "sending_paused" in (msg.last_error or "")


@pytest.mark.django_db
def test_assert_send_allowed_raises_for_pause(tenant):
    tenant.sending_paused = True
    tenant.sending_pause_scope = SendingPauseScope.MARKETING_LIFECYCLE
    tenant.sending_pause_source = SendingPauseSource.MANUAL
    tenant.sending_pause_reason = "bad list"
    tenant.save()
    with pytest.raises(PolicyError) as ei:
        assert_send_allowed(tenant, message_type=MessageType.MARKETING.value)
    assert ei.value.code == "sending_paused_marketing"
