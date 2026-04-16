"""Phase 1: Account layer above tenants."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from apps.accounts.defaults import INTERNAL_ACCOUNT_SLUG, get_or_create_internal_account
from apps.accounts.models import Account, AccountMembership, AccountRole, AccountStatus
from apps.accounts.services.account_access import (
    get_user_accounts,
    user_has_account_access,
    user_has_account_role,
)
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()


@pytest.mark.django_db
def test_account_model_create():
    a = Account.objects.create(
        name="Acme Corp",
        slug="acme-corp",
        status=AccountStatus.ACTIVE,
    )
    assert a.id
    assert str(a) == "Acme Corp (acme-corp)"


@pytest.mark.django_db
def test_account_membership_unique_per_account_user(default_account):
    u = User.objects.create_user("u1", password="x")
    AccountMembership.objects.create(
        account=default_account,
        user=u,
        role=AccountRole.OWNER,
    )
    with pytest.raises(IntegrityError):
        AccountMembership.objects.create(
            account=default_account,
            user=u,
            role=AccountRole.VIEWER,
        )


@pytest.mark.django_db
def test_tenant_requires_account(default_account):
    t = Tenant.objects.create(
        account=default_account,
        name="T",
        slug="t-acct",
        status=TenantStatus.ACTIVE,
        default_sender_email="a@b.com",
    )
    assert t.account_id == default_account.id


@pytest.mark.django_db
def test_all_tenants_have_account_after_migrations(default_account):
    assert not Tenant.objects.filter(account__isnull=True).exists()


@pytest.mark.django_db
def test_internal_account_and_slug():
    a = get_or_create_internal_account()
    assert a.slug == INTERNAL_ACCOUNT_SLUG
    b = get_or_create_internal_account()
    assert a.pk == b.pk


@pytest.mark.django_db
def test_user_has_account_access_staff_bypass(default_account):
    staff = User.objects.create_user("staff", password="x", is_staff=True)
    plain = User.objects.create_user("plain", password="x", is_staff=False)

    assert user_has_account_access(staff, default_account) is True
    assert user_has_account_access(plain, default_account) is False


@pytest.mark.django_db
def test_user_has_account_role_staff_bypass(default_account):
    staff = User.objects.create_user("staff2", password="x", is_staff=True)
    assert user_has_account_role(
        staff,
        default_account,
        [AccountRole.BILLING],
    ) is True


@pytest.mark.django_db
def test_get_user_accounts_non_member(default_account):
    u = User.objects.create_user("nomem", password="x", is_staff=False)
    qs = get_user_accounts(u)
    assert not qs.filter(pk=default_account.pk).exists()


@pytest.mark.django_db
def test_get_user_accounts_member(default_account):
    u = User.objects.create_user("mem", password="x", is_staff=False)
    AccountMembership.objects.create(
        account=default_account,
        user=u,
        role=AccountRole.VIEWER,
    )
    qs = get_user_accounts(u)
    assert qs.filter(pk=default_account.pk).exists()


@pytest.mark.django_db
def test_tenant_api_key_send_unchanged(api_key, approved_template):
    """Bearer tenant API key still resolves the tenant; account field does not affect auth."""
    from apps.email_templates.models import TemplateVariable
    from rest_framework.test import APIClient

    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=False)
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
    assert r.status_code == 201
