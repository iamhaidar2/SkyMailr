"""Operator tenant deliverability page: metrics, isolation, thresholds, test-send."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from freezegun import freeze_time

from apps.messages.models import (
    MessageType,
    OutboundMessage,
    OutboundStatus,
    ProviderWebhookEvent,
)
from apps.tenants.models import TenantDomain
from apps.ui.forms import TenantTestSendForm
from apps.ui.services.tenant_deliverability import build_tenant_deliverability_context

User = get_user_model()


def _outbound(tenant, *, status: str, provider_message_id: str = "", last_error: str = "") -> OutboundMessage:
    return OutboundMessage.objects.create(
        tenant=tenant,
        source_app="test_seed",
        message_type=MessageType.TRANSACTIONAL,
        to_email="r@example.com",
        status=status,
        provider_message_id=provider_message_id,
        last_error=last_error,
    )


@freeze_time("2026-04-14 12:00:00")
@pytest.mark.django_db
def test_tenant_deliverability_get_200(staff_client, tenant):
    url = reverse("ui:tenant_deliverability", kwargs={"tenant_id": tenant.id})
    r = staff_client.get(url)
    assert r.status_code == 200
    assert b"Deliverability" in r.content
    assert b"updated_at" in r.content


@freeze_time("2026-04-14 12:00:00")
@pytest.mark.django_db
def test_tenant_detail_has_deliverability_link(staff_client, tenant):
    url = reverse("ui:tenant_detail", kwargs={"tenant_id": tenant.id})
    r = staff_client.get(url)
    assert r.status_code == 200
    assert reverse("ui:tenant_deliverability", kwargs={"tenant_id": tenant.id}).encode() in r.content


@freeze_time("2026-04-14 12:00:00")
@pytest.mark.django_db
def test_deliverability_rates_and_bounce_level_warning(staff_client, tenant):
    for _ in range(97):
        _outbound(tenant, status=OutboundStatus.DELIVERED)
    for _ in range(3):
        _outbound(tenant, status=OutboundStatus.BOUNCED)

    ctx = build_tenant_deliverability_context(tenant)
    m = ctx["metrics"]
    assert m["sent_path"] == 100
    assert m["delivered"] == 97
    assert m["bounced"] == 3
    assert abs(m["bounce_rate"] - 0.03) < 1e-9
    assert abs(m["delivery_rate"] - 0.97) < 1e-9
    assert ctx["bounce_level"] == "warning"
    assert ctx["complaint_level"] == "ok"

    url = reverse("ui:tenant_deliverability", kwargs={"tenant_id": tenant.id})
    r = staff_client.get(url)
    assert r.status_code == 200
    assert b"(warning)" in r.content


@freeze_time("2026-04-14 12:00:00")
@pytest.mark.django_db
def test_deliverability_bounce_level_danger(staff_client, tenant):
    for _ in range(94):
        _outbound(tenant, status=OutboundStatus.DELIVERED)
    for _ in range(6):
        _outbound(tenant, status=OutboundStatus.BOUNCED)
    ctx = build_tenant_deliverability_context(tenant)
    assert ctx["bounce_level"] == "danger"


@freeze_time("2026-04-14 12:00:00")
@pytest.mark.django_db
def test_deliverability_complaint_level(staff_client, tenant):
    # Denominator 1000; 3 complaints => 0.003 = danger default
    for _ in range(997):
        _outbound(tenant, status=OutboundStatus.DELIVERED)
    for _ in range(3):
        _outbound(tenant, status=OutboundStatus.COMPLAINED)
    ctx = build_tenant_deliverability_context(tenant)
    assert ctx["metrics"]["sent_path"] == 1000
    assert ctx["complaint_level"] == "danger"


@freeze_time("2026-04-14 12:00:00")
@pytest.mark.django_db
def test_deliverability_tenant_isolation(staff_client, tenant, other_tenant):
    for _ in range(5):
        _outbound(tenant, status=OutboundStatus.DELIVERED)
    for _ in range(50):
        _outbound(other_tenant, status=OutboundStatus.BOUNCED)

    ctx_a = build_tenant_deliverability_context(tenant)
    assert ctx_a["metrics"]["delivered"] == 5
    assert ctx_a["metrics"]["bounced"] == 0

    r = staff_client.get(reverse("ui:tenant_deliverability", kwargs={"tenant_id": tenant.id}))
    assert r.status_code == 200


@freeze_time("2026-04-14 12:00:00")
@pytest.mark.django_db
def test_deliverability_webhooks_scoped_to_tenant(staff_client, tenant, other_tenant):
    _outbound(tenant, status=OutboundStatus.SENT, provider_message_id="pm-tenant-a")
    _outbound(other_tenant, status=OutboundStatus.SENT, provider_message_id="pm-tenant-b")
    ProviderWebhookEvent.objects.create(
        provider="postal",
        raw_body="{}",
        normalized={"provider_message_id": "pm-tenant-a", "event_type": "delivered"},
    )
    ProviderWebhookEvent.objects.create(
        provider="postal",
        raw_body="{}",
        normalized={"provider_message_id": "pm-tenant-b", "event_type": "bounced"},
    )

    ctx_a = build_tenant_deliverability_context(tenant)
    ids_a = {ev.normalized.get("provider_message_id") for ev in ctx_a["webhook_events"]}
    assert "pm-tenant-a" in ids_a
    assert "pm-tenant-b" not in ids_a


@freeze_time("2026-04-14 12:00:00")
@pytest.mark.django_db
def test_deliverability_top_failures(staff_client, tenant):
    for _ in range(2):
        _outbound(tenant, status=OutboundStatus.FAILED, last_error="smtp timeout")
    _outbound(tenant, status=OutboundStatus.FAILED, last_error="other")

    ctx = build_tenant_deliverability_context(tenant)
    reasons = {r["reason"]: r["count"] for r in ctx["top_failure_reasons"]}
    assert reasons.get("smtp timeout") == 2
    assert reasons.get("other") == 1


@freeze_time("2026-04-14 12:00:00")
@pytest.mark.django_db
def test_deliverability_domain_row_counts_hostname(staff_client, tenant):
    tenant.default_sender_email = "noreply@mail.example"
    tenant.save(update_fields=["default_sender_email"])
    TenantDomain.objects.create(tenant=tenant, domain="mail.example")
    _outbound(tenant, status=OutboundStatus.DELIVERED)
    _outbound(tenant, status=OutboundStatus.BOUNCED)

    ctx = build_tenant_deliverability_context(tenant)
    assert len(ctx["domain_rows"]) == 1
    row = ctx["domain_rows"][0]
    assert row["domain"].domain == "mail.example"
    assert row["sent_path_count"] == 2
    assert row["delivered"] == 1
    assert row["bounced"] == 1


@freeze_time("2026-04-14 12:00:00")
@pytest.mark.django_db
def test_deliverability_test_send_raw_redirects_to_message(staff_client, tenant):
    url = reverse("ui:tenant_deliverability_test_send", kwargs={"tenant_id": tenant.id})
    r = staff_client.post(
        url,
        {
            "mode": TenantTestSendForm.MODE_RAW,
            "to_email": "dest-deliverability@example.com",
            "subject": "Deliverability test",
            "html_body": "<p>Hi</p>",
            "text_body": "",
            "template_key": "",
            "sender_profile": "",
        },
    )
    assert r.status_code == 302
    msg = OutboundMessage.objects.filter(to_email="dest-deliverability@example.com").first()
    assert msg is not None
    assert msg.source_app == "operator_test_send"
    assert str(msg.id) in r["Location"]


@freeze_time("2026-04-14 12:00:00")
@pytest.mark.django_db
def test_deliverability_forbidden_for_non_staff(client, tenant, db):
    u = User.objects.create_user("cust", password="pass12345", is_staff=False)
    client.login(username="cust", password="pass12345")
    url = reverse("ui:tenant_deliverability", kwargs={"tenant_id": tenant.id})
    r = client.get(url)
    assert r.status_code == 403
