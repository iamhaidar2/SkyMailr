"""Customer portal: sender profiles, templates, workflows — account scoping and roles."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import Account, AccountMembership, AccountRole, AccountStatus
from apps.email_templates.models import (
    ApprovalStatus,
    CreatedByType,
    EmailTemplate,
    EmailTemplateVersion,
    TemplateCategory,
    TemplateStatus,
    VersionSourceType,
)
from apps.tenants.models import SenderCategory, SenderProfile, Tenant, TenantStatus
from apps.workflows.models import Workflow

User = get_user_model()


@pytest.fixture
def customer_user(db):
    return User.objects.create_user(
        "auto@example.com",
        password="SecurePass1!",
        email="auto@example.com",
    )


@pytest.fixture
def customer_account(db, customer_user):
    acc = Account.objects.create(name="Auto Co", slug="auto-co", status=AccountStatus.ACTIVE)
    AccountMembership.objects.create(
        account=acc,
        user=customer_user,
        role=AccountRole.OWNER,
        is_active=True,
    )
    return acc


@pytest.fixture
def editor_user(db):
    return User.objects.create_user(
        "editor@example.com",
        password="SecurePass1!",
        email="editor@example.com",
    )


@pytest.fixture
def editor_account_membership(db, customer_account, editor_user):
    return AccountMembership.objects.create(
        account=customer_account,
        user=editor_user,
        role=AccountRole.EDITOR,
        is_active=True,
    )


@pytest.fixture
def viewer_user(db):
    return User.objects.create_user(
        "viewer@example.com",
        password="SecurePass1!",
        email="viewer@example.com",
    )


@pytest.fixture
def viewer_membership(db, customer_account, viewer_user):
    return AccountMembership.objects.create(
        account=customer_account,
        user=viewer_user,
        role=AccountRole.VIEWER,
        is_active=True,
    )


@pytest.fixture
def portal_tenant(db, customer_account):
    return Tenant.objects.create(
        account=customer_account,
        name="Portal App",
        slug="portal-app",
        status=TenantStatus.ACTIVE,
        default_sender_email="noreply@portal-app.example",
        sending_domain="",
    )


@pytest.fixture
def other_account_tenant(db):
    other = Account.objects.create(name="Other", slug="other-acct", status=AccountStatus.ACTIVE)
    t = Tenant.objects.create(
        account=other,
        name="Other Tenant",
        slug="other-tenant",
        status=TenantStatus.ACTIVE,
        default_sender_email="a@b.com",
    )
    return t


@pytest.mark.django_db
def test_sender_profile_crud(client, customer_user, customer_account, portal_tenant):
    client.force_login(customer_user)
    url_new = reverse("portal:sender_profile_new")
    r = client.post(
        url_new,
        {
            "tenant": str(portal_tenant.id),
            "name": "Main",
            "category": SenderCategory.TRANSACTIONAL,
            "from_name": "App",
            "from_email": "hi@example.com",
            "reply_to": "",
            "is_default": "on",
            "is_active": "on",
        },
    )
    assert r.status_code == 302
    sp = SenderProfile.objects.get(tenant=portal_tenant, name="Main")
    r2 = client.get(reverse("portal:sender_profile_detail", kwargs={"profile_id": sp.id}))
    assert r2.status_code == 200
    r3 = client.post(
        reverse("portal:sender_profile_edit", kwargs={"profile_id": sp.id}),
        {
            "tenant": str(portal_tenant.id),
            "name": "Main Renamed",
            "category": SenderCategory.TRANSACTIONAL,
            "from_name": "App",
            "from_email": "hi@example.com",
            "reply_to": "",
            "is_default": "",
            "is_active": "on",
        },
    )
    assert r3.status_code == 302
    sp.refresh_from_db()
    assert sp.name == "Main Renamed"
    r4 = client.post(reverse("portal:sender_profile_delete", kwargs={"profile_id": sp.id}), {})
    assert r4.status_code == 302
    assert not SenderProfile.objects.filter(pk=sp.id).exists()


@pytest.mark.django_db
def test_sender_profile_domain_validation(client, customer_user, customer_account, portal_tenant):
    portal_tenant.sending_domain = "allowed.example"
    portal_tenant.save(update_fields=["sending_domain"])
    client.force_login(customer_user)
    r = client.post(
        reverse("portal:sender_profile_new"),
        {
            "tenant": str(portal_tenant.id),
            "name": "Bad",
            "category": SenderCategory.TRANSACTIONAL,
            "from_name": "X",
            "from_email": "x@wrong.com",
            "reply_to": "",
            "is_default": "",
            "is_active": "on",
        },
    )
    assert r.status_code == 200
    assert b"sending domain" in r.content.lower() or b"domain" in r.content.lower()


@pytest.mark.django_db
def test_cross_account_sender_profile_404(client, customer_user, customer_account, other_account_tenant):
    sp = SenderProfile.objects.create(
        tenant=other_account_tenant,
        name="Other",
        category=SenderCategory.TRANSACTIONAL,
        from_name="O",
        from_email="o@other.com",
    )
    client.force_login(customer_user)
    r = client.get(reverse("portal:sender_profile_detail", kwargs={"profile_id": sp.id}))
    assert r.status_code == 404


@pytest.mark.django_db
def test_template_list_scoped(client, customer_user, customer_account, portal_tenant):
    EmailTemplate.objects.create(
        tenant=portal_tenant,
        key="t1",
        name="T1",
        category=TemplateCategory.TRANSACTIONAL,
        status=TemplateStatus.DRAFT,
    )
    client.force_login(customer_user)
    r = client.get(reverse("portal:template_list"))
    assert r.status_code == 200
    assert b"t1" in r.content


@pytest.mark.django_db
def test_template_create_and_approve(
    client, customer_user, customer_account, portal_tenant
):
    client.force_login(customer_user)
    r = client.post(
        reverse("portal:template_new"),
        {
            "tenant": str(portal_tenant.id),
            "key": "welcome",
            "name": "Welcome",
            "category": TemplateCategory.TRANSACTIONAL,
            "description": "",
        },
    )
    assert r.status_code == 302
    tpl = EmailTemplate.objects.get(tenant=portal_tenant, key="welcome")
    r2 = client.post(
        reverse("portal:template_version_create", kwargs={"template_id": tpl.id}),
        {
            "subject_template": "Hi",
            "preview_text_template": "",
            "html_template": "<p>x</p>",
            "text_template": "x",
        },
    )
    assert r2.status_code == 302
    assert EmailTemplateVersion.objects.filter(template=tpl).exists()
    r3 = client.post(
        reverse("portal:template_approve", kwargs={"template_id": tpl.id}),
        {"note": ""},
    )
    assert r3.status_code == 302
    tpl.refresh_from_db()
    assert tpl.current_approved_version is not None


@pytest.mark.django_db
def test_template_preview_scoped(client, customer_user, customer_account, portal_tenant):
    tpl = EmailTemplate.objects.create(
        tenant=portal_tenant,
        key="pv",
        name="Pv",
        category=TemplateCategory.TRANSACTIONAL,
        status=TemplateStatus.DRAFT,
    )
    EmailTemplateVersion.objects.create(
        template=tpl,
        version_number=1,
        created_by_type=CreatedByType.USER,
        source_type=VersionSourceType.MANUAL,
        subject_template="S {{ a }}",
        html_template="<p>{{ a }}</p>",
        text_template="{{ a }}",
        approval_status=ApprovalStatus.PENDING,
    )
    client.force_login(customer_user)
    r = client.post(
        reverse("portal:template_preview", kwargs={"template_id": tpl.id}),
        {"context": json.dumps({"a": "1"})},
    )
    assert r.status_code == 200
    assert b"1" in r.content


@pytest.mark.django_db
def test_cross_account_template_404(client, customer_user, customer_account, other_account_tenant):
    tpl = EmailTemplate.objects.create(
        tenant=other_account_tenant,
        key="x",
        name="X",
        category=TemplateCategory.TRANSACTIONAL,
        status=TemplateStatus.DRAFT,
    )
    client.force_login(customer_user)
    r = client.get(reverse("portal:template_detail", kwargs={"template_id": tpl.id}))
    assert r.status_code == 404


@pytest.mark.django_db
def test_workflow_create_list_detail(client, customer_user, customer_account, portal_tenant):
    client.force_login(customer_user)
    r = client.post(
        reverse("portal:workflow_new"),
        {"tenant": str(portal_tenant.id), "name": "Onboarding", "slug": "onboarding"},
    )
    assert r.status_code == 302
    wf = Workflow.objects.get(tenant=portal_tenant, slug="onboarding")
    r2 = client.get(reverse("portal:workflow_list"))
    assert r2.status_code == 200
    assert b"onboarding" in r.content.lower()
    r3 = client.get(reverse("portal:workflow_detail", kwargs={"workflow_id": wf.id}))
    assert r3.status_code == 200


@pytest.mark.django_db
def test_workflow_step_validates_template_key(
    client, customer_user, customer_account, portal_tenant
):
    tpl = EmailTemplate.objects.create(
        tenant=portal_tenant,
        key="step_tpl",
        name="Step",
        category=TemplateCategory.TRANSACTIONAL,
        status=TemplateStatus.DRAFT,
    )
    wf = Workflow.objects.create(tenant=portal_tenant, name="W", slug="w")
    client.force_login(customer_user)
    r = client.post(
        reverse("portal:workflow_add_step", kwargs={"workflow_id": wf.id}),
        {
            "order": "0",
            "step_type": "send_template",
            "template_key": "missing",
            "wait_seconds": "",
        },
    )
    assert r.status_code == 302
    # Should not create step — error message
    assert wf.steps.count() == 0
    r2 = client.post(
        reverse("portal:workflow_add_step", kwargs={"workflow_id": wf.id}),
        {
            "order": "0",
            "step_type": "send_template",
            "template_key": "step_tpl",
            "wait_seconds": "",
        },
    )
    assert r2.status_code == 302
    assert wf.steps.count() == 1


@pytest.mark.django_db
def test_editor_cannot_create_tenant(client, editor_user, customer_account, editor_account_membership):
    client.force_login(editor_user)
    r = client.get(reverse("portal:tenant_new"))
    assert r.status_code == 403


@pytest.mark.django_db
def test_viewer_cannot_edit_sender_profile(client, viewer_user, customer_account, viewer_membership, portal_tenant):
    client.force_login(viewer_user)
    r = client.get(reverse("portal:sender_profile_new"))
    assert r.status_code == 403


@pytest.mark.django_db
def test_editor_cannot_approve_template(
    client, editor_user, customer_account, editor_account_membership, portal_tenant
):
    tpl = EmailTemplate.objects.create(
        tenant=portal_tenant,
        key="ed",
        name="Ed",
        category=TemplateCategory.TRANSACTIONAL,
        status=TemplateStatus.DRAFT,
    )
    EmailTemplateVersion.objects.create(
        template=tpl,
        version_number=1,
        created_by_type=CreatedByType.USER,
        source_type=VersionSourceType.MANUAL,
        subject_template="S",
        html_template="<p>x</p>",
        text_template="x",
        approval_status=ApprovalStatus.PENDING,
    )
    client.force_login(editor_user)
    r = client.post(
        reverse("portal:template_approve", kwargs={"template_id": tpl.id}),
        {"note": ""},
    )
    assert r.status_code == 403


@pytest.mark.django_db
def test_operator_templates_list_still_works(staff_client):
    r = staff_client.get(reverse("ui:templates_list"))
    assert r.status_code == 200
