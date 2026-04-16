"""Operator UI: tenants, sender profiles, send-from selector."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.messages.models import OutboundMessage
from apps.tenants.models import SenderCategory, SenderProfile, Tenant, TenantStatus
from apps.ui.forms import SendRawForm
from apps.ui.services.operator import SESSION_ACTIVE_TENANT_KEY, set_active_tenant

User = get_user_model()


def _set_active_tenant_via_switch(client, tenant):
    """Match production flow so session + CSRF are consistent (not only in-memory session)."""
    client.get(reverse("ui:dashboard"))
    r = client.post(
        reverse("ui:switch_tenant"),
        {"tenant_id": str(tenant.id), "next": reverse("ui:dashboard")},
    )
    assert r.status_code == 302


@pytest.fixture
def staff_client(db, client):
    user = User.objects.create_user("ops", password="pass12345", is_staff=True)
    client.login(username="ops", password="pass12345")
    return client


def _tenant_form_data(**overrides):
    base = {
        "name": "Acme",
        "slug": "acme",
        "status": TenantStatus.ACTIVE,
        "default_sender_name": "Acme",
        "default_sender_email": "",
        "reply_to": "",
        "sending_domain": "",
        "timezone": "UTC",
        "rate_limit_per_minute": "120",
        "webhook_secret": "",
    }
    base.update(overrides)
    return base


def test_tenant_create_post_redirects_and_persists(staff_client, db):
    url = reverse("ui:tenant_create")
    r = staff_client.post(url, _tenant_form_data(slug="newco", name="NewCo"))
    assert r.status_code == 302
    t = Tenant.objects.get(slug="newco")
    assert t.name == "NewCo"


def test_tenant_edit_post_updates(staff_client, tenant):
    url = reverse("ui:tenant_edit", kwargs={"tenant_id": tenant.id})
    r = staff_client.post(
        url,
        _tenant_form_data(
            name="Renamed",
            slug=tenant.slug,
            default_sender_email=tenant.default_sender_email or "",
            default_sender_name=tenant.default_sender_name or "",
        ),
    )
    assert r.status_code == 302
    tenant.refresh_from_db()
    assert tenant.name == "Renamed"


def test_tenant_delete_post_removes_and_clears_active_session(staff_client, db, default_account):
    t = Tenant.objects.create(
        account=default_account,
        name="GoneCo",
        slug="goneco",
        status=TenantStatus.ACTIVE,
        default_sender_email="a@goneco.example",
        default_sender_name="Gone",
    )
    set_active_tenant(staff_client.session, t)
    staff_client.session.save()
    url = reverse("ui:tenant_delete", kwargs={"tenant_id": t.id})
    r = staff_client.post(url)
    assert r.status_code == 302
    assert not Tenant.objects.filter(pk=t.id).exists()
    assert SESSION_ACTIVE_TENANT_KEY not in staff_client.session


def test_sender_profile_create_rejects_wrong_domain(staff_client, tenant):
    tenant.sending_domain = "testco.example"
    tenant.save(update_fields=["sending_domain"])
    url = reverse("ui:sender_profile_create", kwargs={"tenant_id": tenant.id})
    r = staff_client.post(
        url,
        {
            "name": "Bad",
            "category": SenderCategory.TRANSACTIONAL,
            "from_name": "Bad",
            "from_email": "x@evil.com",
            "reply_to": "",
            "is_default": "",
            "is_active": "on",
        },
    )
    assert r.status_code == 200
    assert b"sending domain" in r.content.lower() or b"from address" in r.content.lower()
    assert not SenderProfile.objects.filter(tenant=tenant, name="Bad").exists()


def test_sender_profile_create_ok(staff_client, tenant):
    tenant.sending_domain = "testco.example"
    tenant.save(update_fields=["sending_domain"])
    url = reverse("ui:sender_profile_create", kwargs={"tenant_id": tenant.id})
    r = staff_client.post(
        url,
        {
            "name": "Sales",
            "category": SenderCategory.TRANSACTIONAL,
            "from_name": "Sales",
            "from_email": "sales@testco.example",
            "reply_to": "",
            "is_default": "",
            "is_active": "on",
        },
    )
    assert r.status_code == 302
    assert SenderProfile.objects.filter(tenant=tenant, from_email="sales@testco.example").exists()


def test_send_raw_with_sender_profile(staff_client, tenant):
    _set_active_tenant_via_switch(staff_client, tenant)
    sp = SenderProfile.objects.create(
        tenant=tenant,
        name="Ops",
        category=SenderCategory.TRANSACTIONAL,
        from_name="Ops",
        from_email="ops@testco.example",
    )
    url = reverse("ui:send_raw")
    r = staff_client.post(
        url,
        {
            "source_app": "operator_ui",
            "message_type": "transactional",
            "to_email": "dest@example.com",
            "to_name": "",
            "subject": "Hello",
            "html_body": "<p>Hi</p>",
            "text_body": "",
            "metadata": "{}",
            "idempotency_key": "",
            "sender_profile": str(sp.id),
        },
    )
    assert r.status_code == 302
    msg = OutboundMessage.objects.order_by("-created_at").first()
    assert msg is not None
    assert msg.sender_profile_id == sp.id


def test_send_raw_blank_sender_profile_is_null(staff_client, tenant):
    _set_active_tenant_via_switch(staff_client, tenant)
    url = reverse("ui:send_raw")
    r = staff_client.post(
        url,
        {
            "source_app": "operator_ui",
            "message_type": "transactional",
            "to_email": "dest2@example.com",
            "to_name": "",
            "subject": "Hello",
            "html_body": "<p>Hi</p>",
            "text_body": "",
            "metadata": "{}",
            "idempotency_key": "",
            "sender_profile": "",
        },
    )
    assert r.status_code == 302
    msg = OutboundMessage.objects.filter(to_email="dest2@example.com").first()
    assert msg is not None
    assert msg.sender_profile_id is None


def test_send_raw_form_invalid_for_other_tenants_profile_id(tenant, other_tenant):
    other_sp = SenderProfile.objects.create(
        tenant=other_tenant,
        name="Other",
        category=SenderCategory.TRANSACTIONAL,
        from_name="O",
        from_email="o@otherco.example",
    )
    f = SendRawForm(
        data={
            "source_app": "operator_ui",
            "message_type": "transactional",
            "to_email": "dest3@example.com",
            "to_name": "",
            "subject": "Hello",
            "html_body": "<p>Hi</p>",
            "text_body": "",
            "metadata": "{}",
            "idempotency_key": "",
            "sender_profile": str(other_sp.id),
        },
        tenant=tenant,
    )
    assert not f.is_valid()
    assert "sender_profile" in f.errors


def test_send_raw_rejects_other_tenants_sender_profile(staff_client, tenant, other_tenant):
    _set_active_tenant_via_switch(staff_client, tenant)
    other_sp = SenderProfile.objects.create(
        tenant=other_tenant,
        name="Other",
        category=SenderCategory.TRANSACTIONAL,
        from_name="O",
        from_email="o@otherco.example",
    )
    url = reverse("ui:send_raw")
    r = staff_client.post(
        url,
        {
            "source_app": "operator_ui",
            "message_type": "transactional",
            "to_email": "dest3@example.com",
            "to_name": "",
            "subject": "Hello",
            "html_body": "<p>Hi</p>",
            "text_body": "",
            "metadata": "{}",
            "idempotency_key": "",
            "sender_profile": str(other_sp.id),
        },
    )
    assert r.status_code == 400
    assert not OutboundMessage.objects.filter(to_email="dest3@example.com").exists()
