"""Customer portal: suppressions and webhooks / delivery events (account isolation)."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import Account, AccountMembership, AccountRole, AccountStatus
from apps.messages.models import MessageEvent, MessageEventType, OutboundMessage, OutboundStatus
from apps.subscriptions.models import DeliverySuppression, SuppressionReason
from apps.tenants.models import Tenant, TenantStatus
from tests.portal_helpers import bind_portal_account_session

User = get_user_model()


@pytest.fixture
def portal_account_a(db):
    return Account.objects.create(name="Portal A", slug="portal-a", status=AccountStatus.ACTIVE)


@pytest.fixture
def portal_account_b(db):
    return Account.objects.create(name="Portal B", slug="portal-b", status=AccountStatus.ACTIVE)


@pytest.fixture
def portal_user_a(db, portal_account_a):
    u = User.objects.create_user("portala@example.com", password="SecurePass1!", email="portala@example.com")
    AccountMembership.objects.create(
        account=portal_account_a,
        user=u,
        role=AccountRole.OWNER,
        is_active=True,
    )
    return u


@pytest.fixture
def portal_user_b(db, portal_account_b):
    u = User.objects.create_user("portalb@example.com", password="SecurePass1!", email="portalb@example.com")
    AccountMembership.objects.create(
        account=portal_account_b,
        user=u,
        role=AccountRole.OWNER,
        is_active=True,
    )
    return u


@pytest.fixture
def tenant_a(db, portal_account_a):
    return Tenant.objects.create(
        account=portal_account_a,
        name="App A",
        slug="app-a",
        status=TenantStatus.ACTIVE,
        default_sender_email="noreply@app-a.example",
        default_sender_name="App A",
    )


@pytest.fixture
def tenant_b(db, portal_account_b):
    return Tenant.objects.create(
        account=portal_account_b,
        name="App B",
        slug="app-b",
        status=TenantStatus.ACTIVE,
        default_sender_email="noreply@app-b.example",
        default_sender_name="App B",
    )


@pytest.mark.django_db
def test_portal_suppressions_list_shows_own_and_global_not_other_account(
    client, portal_user_a, portal_account_a, tenant_a, tenant_b
):
    DeliverySuppression.objects.create(
        tenant=tenant_a,
        email="mine@example.com",
        reason=SuppressionReason.MANUAL,
        applies_to_marketing=True,
    )
    DeliverySuppression.objects.create(
        tenant=None,
        email="global@example.com",
        reason=SuppressionReason.HARD_BOUNCE,
        applies_to_marketing=True,
    )
    DeliverySuppression.objects.create(
        tenant=tenant_b,
        email="other@example.com",
        reason=SuppressionReason.MANUAL,
        applies_to_marketing=True,
    )
    bind_portal_account_session(client, portal_user_a, portal_account_a)
    url = reverse("portal:suppressions_list")
    r = client.get(url)
    assert r.status_code == 200
    body = r.content.decode()
    assert "mine@example.com" in body
    assert "global@example.com" in body
    assert "other@example.com" not in body


@pytest.mark.django_db
def test_portal_webhooks_events_scoped_to_account(
    client, portal_user_a, portal_account_a, tenant_a, tenant_b
):
    msg_a = OutboundMessage.objects.create(
        tenant=tenant_a,
        source_app="t",
        message_type="transactional",
        to_email="a@example.com",
        status=OutboundStatus.SENT,
    )
    msg_b = OutboundMessage.objects.create(
        tenant=tenant_b,
        source_app="t",
        message_type="transactional",
        to_email="b@example.com",
        status=OutboundStatus.SENT,
    )
    MessageEvent.objects.create(
        message=msg_a, event_type=MessageEventType.DELIVERED, payload={"x": 1}
    )
    MessageEvent.objects.create(
        message=msg_b, event_type=MessageEventType.DELIVERED, payload={"y": 2}
    )
    bind_portal_account_session(client, portal_user_a, portal_account_a)
    r = client.get(reverse("portal:webhooks_overview"))
    assert r.status_code == 200
    body = r.content.decode()
    assert "a@example.com" in body
    assert "b@example.com" not in body


@pytest.mark.django_db
def test_portal_suppression_add_creates_manual_row(
    client, portal_user_a, portal_account_a, tenant_a
):
    bind_portal_account_session(client, portal_user_a, portal_account_a)
    url = reverse("portal:suppression_add")
    r = client.post(
        url,
        {
            "email": " block@Example.COM ",
            "tenant": str(tenant_a.id),
            "applies_to_marketing": "on",
            "applies_to_transactional": "",
            "note": "test note",
        },
        follow=False,
    )
    assert r.status_code == 302
    s = DeliverySuppression.objects.get(tenant=tenant_a, email="block@example.com")
    assert s.reason == SuppressionReason.MANUAL
    assert s.applies_to_marketing is True
    assert s.applies_to_transactional is False
    assert (s.metadata or {}).get("source") == "customer_portal"


@pytest.mark.django_db
def test_portal_suppression_delete_removes_tenant_row(
    client, portal_user_a, portal_account_a, tenant_a
):
    row = DeliverySuppression.objects.create(
        tenant=tenant_a,
        email="del@example.com",
        reason=SuppressionReason.MANUAL,
        applies_to_marketing=True,
    )
    bind_portal_account_session(client, portal_user_a, portal_account_a)
    url = reverse("portal:suppression_delete", kwargs={"suppression_id": row.id})
    r = client.post(url, {})
    assert r.status_code == 302
    assert not DeliverySuppression.objects.filter(pk=row.pk).exists()
