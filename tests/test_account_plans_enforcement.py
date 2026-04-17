"""Plans, usage metering, enforcement, suspension, and API errors."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import AccountStatus
from apps.accounts.plans import get_effective_limits
from apps.accounts.services.usage import usage_snapshot
from apps.messages.models import MessageType, OutboundMessage, OutboundStatus
from apps.messages.services.send_pipeline import create_templated_message
from apps.tenants.models import TenantStatus
from tests.portal_helpers import bind_portal_account_session


@pytest.fixture
def customer_user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        "plans@example.com",
        password="SecurePass1!",
        email="plans@example.com",
        first_name="Plans User",
    )


@pytest.fixture
def customer_account(db, customer_user):
    from apps.accounts.models import Account, AccountMembership, AccountRole, AccountStatus

    acc = Account.objects.create(name="Plans Co", slug="plans-co", status=AccountStatus.ACTIVE)
    AccountMembership.objects.create(
        account=acc,
        user=customer_user,
        role=AccountRole.OWNER,
        is_active=True,
    )
    return acc


@pytest.mark.django_db
def test_get_effective_limits_merges_metadata_override(default_account):
    default_account.metadata = {
        "plan_limits_override": {"max_tenants": 42, "max_sending_domains_per_tenant": 99}
    }
    default_account.save()
    lim = get_effective_limits(default_account)
    assert lim.max_tenants == 42
    assert lim.max_sending_domains_per_tenant == 99


@pytest.mark.django_db
def test_usage_snapshot_excludes_draft_and_cancelled(default_account, tenant, approved_template):
    tpl, ver = approved_template
    OutboundMessage.objects.create(
        tenant=tenant,
        source_app="t",
        message_type=MessageType.TRANSACTIONAL.value,
        template=tpl,
        template_version=ver,
        to_email="d@example.com",
        status=OutboundStatus.DRAFT,
    )
    OutboundMessage.objects.create(
        tenant=tenant,
        source_app="t",
        message_type=MessageType.TRANSACTIONAL.value,
        template=tpl,
        template_version=ver,
        to_email="c@example.com",
        status=OutboundStatus.CANCELLED,
    )
    OutboundMessage.objects.create(
        tenant=tenant,
        source_app="t",
        message_type=MessageType.TRANSACTIONAL.value,
        template=tpl,
        template_version=ver,
        to_email="q@example.com",
        status=OutboundStatus.QUEUED,
    )
    snap = usage_snapshot(default_account)
    assert snap.monthly_send_count == 1


@pytest.mark.django_db
def test_send_api_returns_429_when_monthly_cap_zero(api_key, approved_template, default_account):
    from apps.email_templates.models import TemplateVariable

    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=False)
    default_account.metadata = {"plan_limits_override": {"max_monthly_sends": 0}}
    default_account.save()

    client = APIClient()
    r = client.post(
        "/api/v1/messages/send-template/",
        {
            "template_key": "email_verification",
            "to_email": "u@example.com",
            "context": {"user_name": "Bob"},
            "source_app": "tests",
            "message_type": "transactional",
        },
        HTTP_AUTHORIZATION=f"Bearer {api_key}",
        format="json",
    )
    assert r.status_code == 429
    body = r.json()
    assert body["code"] == "monthly_send_limit"
    assert "detail" in body


@pytest.mark.django_db
def test_send_api_returns_403_when_account_suspended(api_key, approved_template, default_account):
    from apps.email_templates.models import TemplateVariable

    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=False)
    default_account.status = AccountStatus.SUSPENDED
    default_account.save()

    client = APIClient()
    r = client.post(
        "/api/v1/messages/send-template/",
        {
            "template_key": "email_verification",
            "to_email": "u@example.com",
            "context": {"user_name": "Bob"},
            "source_app": "tests",
            "message_type": "transactional",
        },
        HTTP_AUTHORIZATION=f"Bearer {api_key}",
        format="json",
    )
    assert r.status_code == 403
    assert r.json()["code"] == "account_suspended"


@pytest.mark.django_db
def test_send_pipeline_blocks_tenant_suspended(tenant, approved_template):
    from apps.accounts.policy import PolicyError

    tenant.status = TenantStatus.SUSPENDED
    tenant.save()
    tpl, _ = approved_template
    with pytest.raises(PolicyError) as ei:
        create_templated_message(
            tenant=tenant,
            template=tpl,
            source_app="t",
            message_type=MessageType.TRANSACTIONAL.value,
            to_email="x@example.com",
            to_name="",
            context={},
            metadata={},
            tags={},
            idempotency_key=None,
        )
    assert ei.value.code == "tenant_suspended"


@pytest.mark.django_db
def test_portal_account_usage_page_200(client, customer_user, customer_account):
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.get(reverse("portal:account_usage"))
    assert r.status_code == 200
    assert b"Usage" in r.content or b"plan" in r.content.lower()


@pytest.mark.django_db
def test_portal_suspended_account_blocks_manage_post(client, customer_user, customer_account):
    customer_account.status = AccountStatus.SUSPENDED
    customer_account.save()
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.post(
        reverse("portal:tenant_new"),
        {
            "name": "Nope",
            "slug": "nope-tenant",
            "status": TenantStatus.ACTIVE,
            "timezone": "UTC",
            "rate_limit_per_minute": 120,
        },
    )
    assert r.status_code == 302
    assert r.url == reverse("portal:dashboard")
