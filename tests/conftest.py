import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


def pytest_configure():
    """Avoid RequestContext.copy() failures on Python 3.14+ when the test client stores rendered contexts."""
    from copy import copy as copy_fn

    import django.test.client as dj_client

    def store_rendered_templates(store, signal, sender, template, context, **kwargs):
        store.setdefault("templates", []).append(template)
        if "context" not in store:
            store["context"] = dj_client.ContextList()
        try:
            store["context"].append(copy_fn(context))
        except Exception:
            store["context"].append(context)

    dj_client.store_rendered_templates = store_rendered_templates


@pytest.fixture
def staff_client(db, client):
    """Staff session for operator UI tests."""
    u = User.objects.create_user("staffop", password="pass12345", is_staff=True)
    client.login(username="staffop", password="pass12345")
    return client


@pytest.fixture
def default_account(db):
    from apps.accounts.defaults import get_or_create_internal_account

    return get_or_create_internal_account()


@pytest.fixture
def tenant(db, default_account):
    from apps.tenants.models import Tenant, TenantStatus

    return Tenant.objects.create(
        account=default_account,
        name="TestCo",
        slug="testco",
        status=TenantStatus.ACTIVE,
        default_sender_email="noreply@testco.example",
        default_sender_name="TestCo",
        llm_defaults={"default_model": "gpt-4o-mini", "temperature": 0.2},
    )


@pytest.fixture
def other_tenant(db, default_account):
    from apps.tenants.models import Tenant, TenantStatus

    return Tenant.objects.create(
        account=default_account,
        name="OtherCo",
        slug="otherco",
        status=TenantStatus.ACTIVE,
        default_sender_email="noreply@otherco.example",
        default_sender_name="OtherCo",
        llm_defaults={"default_model": "gpt-4o-mini", "temperature": 0.2},
    )


@pytest.fixture
def api_key(db, tenant):
    from apps.tenants.crypto import generate_api_key, hash_api_key
    from apps.tenants.models import TenantAPIKey

    raw = generate_api_key()
    TenantAPIKey.objects.create(
        tenant=tenant,
        name="test",
        key_hash=hash_api_key(raw),
    )
    return raw


@pytest.fixture
def api_key_other(db, other_tenant):
    from apps.tenants.crypto import generate_api_key, hash_api_key
    from apps.tenants.models import TenantAPIKey

    raw = generate_api_key()
    TenantAPIKey.objects.create(
        tenant=other_tenant,
        name="test-other",
        key_hash=hash_api_key(raw),
    )
    return raw


@pytest.fixture
def approved_template(db, tenant):
    from apps.email_templates.models import (
        ApprovalStatus,
        CreatedByType,
        EmailTemplate,
        EmailTemplateVersion,
        TemplateCategory,
        TemplateStatus,
        VersionSourceType,
    )

    tpl = EmailTemplate.objects.create(
        tenant=tenant,
        key="email_verification",
        name="Verify",
        category=TemplateCategory.TRANSACTIONAL,
        status=TemplateStatus.ACTIVE,
    )
    ver = EmailTemplateVersion.objects.create(
        template=tpl,
        version_number=1,
        created_by_type=CreatedByType.SYSTEM,
        source_type=VersionSourceType.SEEDED,
        subject_template="Hi {{ user_name }}",
        html_template="<p>{{ user_name }}</p>",
        text_template="{{ user_name }}",
        approval_status=ApprovalStatus.APPROVED,
        is_current_approved=True,
    )
    return tpl, ver
