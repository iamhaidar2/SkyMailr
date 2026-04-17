"""Customer portal: signup, login, tenant scoping, API keys."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import Account, AccountMembership, AccountRole, AccountStatus
from apps.accounts.plans import DEFAULT_PLAN_CODE
from apps.tenants.crypto import generate_api_key, hash_api_key
from apps.tenants.models import Tenant, TenantAPIKey, TenantStatus
from tests.portal_helpers import bind_portal_account_session

User = get_user_model()


@pytest.fixture
def customer_user(db):
    return User.objects.create_user(
        "cust@example.com",
        password="SecurePass1!",
        email="cust@example.com",
        first_name="Cust User",
    )


@pytest.fixture
def customer_account(db, customer_user):
    acc = Account.objects.create(name="Cust Co", slug="cust-co", status=AccountStatus.ACTIVE)
    AccountMembership.objects.create(
        account=acc,
        user=customer_user,
        role=AccountRole.OWNER,
        is_active=True,
    )
    return acc


@pytest.fixture
def other_account_tenant(db):
    """Tenant under a different account — not accessible to customer_user."""
    other = Account.objects.create(name="Other", slug="other-acct", status=AccountStatus.ACTIVE)
    return Tenant.objects.create(
        account=other,
        name="Other Tenant",
        slug="other-tenant",
        status=TenantStatus.ACTIVE,
        default_sender_email="a@b.com",
    )


@pytest.mark.django_db
def test_signup_creates_user_account_owner_membership(client):
    url = reverse("portal:signup")
    r = client.post(
        url,
        {
            "display_name": "New Person",
            "email": "newperson@example.com",
            "password1": "GoodPassphrase9!",
            "password2": "GoodPassphrase9!",
            "account_name": "New Co",
            "account_slug": "new-co",
        },
    )
    assert r.status_code == 302
    assert User.objects.filter(username="newperson@example.com").exists()
    u = User.objects.get(username="newperson@example.com")
    assert Account.objects.filter(slug="new-co").exists()
    acc = Account.objects.get(slug="new-co")
    m = AccountMembership.objects.get(user=u, account=acc)
    assert m.role == AccountRole.OWNER
    assert acc.plan_code == DEFAULT_PLAN_CODE
    assert Tenant.objects.filter(account=acc).count() == 1
    t = Tenant.objects.get(account=acc)
    assert t.slug == "new-co"


@pytest.mark.django_db
def test_signup_logs_in_and_session(client):
    client.post(
        reverse("portal:signup"),
        {
            "display_name": "A",
            "email": "logged@example.com",
            "password1": "GoodPassphrase9!",
            "password2": "GoodPassphrase9!",
            "account_name": "A Co",
            "account_slug": "a-co",
        },
    )
    r = client.get(reverse("portal:dashboard"))
    assert r.status_code == 200


@pytest.mark.django_db
def test_signup_rejects_duplicate_email(client, customer_user):
    r = client.post(
        reverse("portal:signup"),
        {
            "display_name": "X",
            "email": customer_user.email,
            "password1": "GoodPassphrase9!",
            "password2": "GoodPassphrase9!",
            "account_name": "X",
            "account_slug": "x-co",
        },
    )
    assert r.status_code == 200
    assert b"already exists" in r.content.lower() or b"email" in r.content.lower()


@pytest.mark.django_db
def test_signup_rejects_duplicate_account_slug(client):
    Account.objects.create(name="Taken", slug="taken-slug", status=AccountStatus.ACTIVE)
    r = client.post(
        reverse("portal:signup"),
        {
            "display_name": "Y",
            "email": "y@example.com",
            "password1": "GoodPassphrase9!",
            "password2": "GoodPassphrase9!",
            "account_name": "Y",
            "account_slug": "taken-slug",
        },
    )
    assert r.status_code == 200
    assert "slug" in r.content.decode().lower()


@pytest.mark.django_db
def test_customer_login(client, customer_user, customer_account):
    client.logout()
    r = client.post(
        reverse("portal:login"),
        {"username": "cust@example.com", "password": "SecurePass1!"},
    )
    assert r.status_code == 302
    r2 = client.get(reverse("portal:dashboard"))
    assert r2.status_code == 200


@pytest.mark.django_db
def test_customer_cannot_access_operator_dashboard(client, customer_user, customer_account):
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.get(reverse("ui:dashboard"))
    assert r.status_code == 403


@pytest.mark.django_db
def test_staff_still_reaches_operator_dashboard(staff_client):
    r = staff_client.get(reverse("ui:dashboard"))
    assert r.status_code == 200


@pytest.mark.django_db
def test_portal_dashboard_loads(client, customer_user, customer_account):
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.get(reverse("portal:dashboard"))
    assert r.status_code == 200
    assert b"Cust Co" in r.content or b"cust-co" in r.content


@pytest.mark.django_db
def test_dashboard_creates_default_connected_app_if_missing(client, customer_user, customer_account):
    assert Tenant.objects.filter(account=customer_account).count() == 0
    bind_portal_account_session(client, customer_user, customer_account)
    client.get(reverse("portal:dashboard"))
    assert Tenant.objects.filter(account=customer_account).count() == 1
    t = Tenant.objects.get(account=customer_account)
    assert t.slug == "cust-co"


@pytest.mark.django_db
def test_customer_creates_tenant(client, customer_user, customer_account):
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.post(
        reverse("portal:tenant_new"),
        {
            "name": "App One",
            "slug": "app-one",
        },
    )
    assert r.status_code == 302
    t = Tenant.objects.get(slug="app-one")
    assert t.account_id == customer_account.id


@pytest.mark.django_db
def test_new_connected_app_redirects_when_at_plan_limit(client, customer_user, customer_account):
    Tenant.objects.create(
        account=customer_account,
        name="Existing",
        slug="existing-app",
        status=TenantStatus.ACTIVE,
    )
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.get(reverse("portal:tenant_new"))
    assert r.status_code == 302
    assert r.url == reverse("portal:tenant_list")


@pytest.mark.django_db
def test_customer_cannot_access_other_account_tenant_detail(
    client, customer_user, customer_account, other_account_tenant
):
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.get(reverse("portal:tenant_detail", kwargs={"tenant_id": other_account_tenant.id}))
    assert r.status_code == 404


@pytest.mark.django_db
def test_customer_api_key_only_own_tenant(client, customer_user, customer_account, other_account_tenant):
    own = Tenant.objects.create(
        account=customer_account,
        name="Mine",
        slug="mine-app",
        status=TenantStatus.ACTIVE,
        default_sender_email="a@mine.com",
    )
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.post(
        reverse("portal:tenant_create_api_key", kwargs={"tenant_id": other_account_tenant.id}),
        {"name": "evil"},
    )
    assert r.status_code == 404
    r2 = client.post(
        reverse("portal:tenant_create_api_key", kwargs={"tenant_id": own.id}),
        {"name": "k1"},
    )
    assert r2.status_code == 302
    assert TenantAPIKey.objects.filter(tenant=own).exists()


@pytest.mark.django_db
def test_tenant_api_key_bearer_unchanged(api_key, approved_template):
    """Regression: tenant API send still works (account layer does not affect Bearer)."""
    from apps.email_templates.models import TemplateVariable
    from rest_framework.test import APIClient

    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=False)
    c = APIClient()
    r = c.post(
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


@pytest.mark.django_db
def test_operator_login_redirects_authenticated_customer(client, customer_user, customer_account):
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.get(reverse("ui:login"))
    assert r.status_code == 302
    assert r["Location"].endswith(reverse("portal:dashboard")) or "/app/" in r["Location"]
