"""Customer portal: tenant sending domains, DNS verification, primary domain, account isolation."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test.utils import override_settings
from django.urls import reverse

from apps.accounts.models import Account, AccountMembership, AccountRole, AccountStatus
from apps.tenants.models import DomainVerificationStatus, Tenant, TenantDomain, TenantStatus
from apps.tenants.services.domain_verification import check_tenant_domain_dns
from tests.portal_helpers import bind_portal_account_session

User = get_user_model()


@pytest.fixture
def customer_user(db):
    return User.objects.create_user(
        "domains@example.com",
        password="SecurePass1!",
        email="domains@example.com",
    )


@pytest.fixture
def customer_account(db, customer_user):
    acc = Account.objects.create(name="Domains Co", slug="domains-co", status=AccountStatus.ACTIVE)
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
        "domeditor@example.com",
        password="SecurePass1!",
        email="domeditor@example.com",
    )


@pytest.fixture
def editor_membership(db, customer_account, editor_user):
    return AccountMembership.objects.create(
        account=customer_account,
        user=editor_user,
        role=AccountRole.EDITOR,
        is_active=True,
    )


@pytest.fixture
def viewer_user(db):
    return User.objects.create_user(
        "domviewer@example.com",
        password="SecurePass1!",
        email="domviewer@example.com",
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
        name="Domain App",
        slug="domain-app",
        status=TenantStatus.ACTIVE,
        default_sender_email="",
        sending_domain="",
    )


@pytest.fixture
def other_account_tenant(db):
    other = Account.objects.create(name="Other Dom", slug="other-dom", status=AccountStatus.ACTIVE)
    return Tenant.objects.create(
        account=other,
        name="Other T",
        slug="other-t",
        status=TenantStatus.ACTIVE,
        default_sender_email="a@b.com",
    )


@pytest.mark.django_db
@patch("apps.ui.views.portal_tenant_domains.delete_postal_domain", return_value=(True, None, True))
def test_remove_domain_calls_postal_delete(mock_delete, client, customer_user, customer_account, portal_tenant):
    td = TenantDomain.objects.create(
        tenant=portal_tenant,
        domain="remove.example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
        is_primary=True,
    )
    portal_tenant.sending_domain = td.domain
    portal_tenant.save()
    bind_portal_account_session(client, customer_user, customer_account)
    url = reverse("portal:tenant_domain_delete", kwargs={"tenant_id": portal_tenant.id, "domain_id": td.id})
    r = client.post(url)
    assert r.status_code == 302
    assert not TenantDomain.objects.filter(pk=td.pk).exists()
    mock_delete.assert_called_once_with("remove.example.com")


@pytest.mark.django_db
def test_owner_creates_first_domain_sets_primary_and_sending_domain(
    client, customer_user, customer_account, portal_tenant
):
    bind_portal_account_session(client, customer_user, customer_account)
    url = reverse("portal:tenant_domain_new", kwargs={"tenant_id": portal_tenant.id})
    r = client.post(url, {"domain": "mail.example.com"})
    assert r.status_code == 302
    td = TenantDomain.objects.get(tenant=portal_tenant, domain="mail.example.com")
    assert td.is_primary
    assert td.verification_status == DomainVerificationStatus.UNVERIFIED
    portal_tenant.refresh_from_db()
    assert portal_tenant.sending_domain == "mail.example.com"


@pytest.mark.django_db
def test_duplicate_domain_rejected(client, customer_user, customer_account, portal_tenant):
    TenantDomain.objects.create(
        tenant=portal_tenant,
        domain="existing.example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
    )
    bind_portal_account_session(client, customer_user, customer_account)
    url = reverse("portal:tenant_domain_new", kwargs={"tenant_id": portal_tenant.id})
    r = client.post(url, {"domain": "existing.example.com"})
    assert r.status_code == 200
    assert b"already" in r.content.lower() or b"already added" in r.content.lower()
    assert TenantDomain.objects.filter(tenant=portal_tenant, domain="existing.example.com").count() == 1


@pytest.mark.django_db
def test_cross_account_domain_access_denied(client, customer_user, customer_account, other_account_tenant):
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.get(
        reverse("portal:tenant_domain_list", kwargs={"tenant_id": other_account_tenant.id})
    )
    assert r.status_code == 404


@pytest.mark.django_db
def test_only_one_primary_after_make_primary(
    client, customer_user, customer_account, portal_tenant
):
    d1 = TenantDomain.objects.create(
        tenant=portal_tenant,
        domain="a.example.com",
        is_primary=True,
        verified=True,
        verification_status=DomainVerificationStatus.VERIFIED,
    )
    d2 = TenantDomain.objects.create(
        tenant=portal_tenant,
        domain="b.example.com",
        is_primary=False,
        verified=True,
        verification_status=DomainVerificationStatus.VERIFIED,
    )
    portal_tenant.sending_domain = d1.domain
    portal_tenant.save()
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.post(
        reverse("portal:tenant_domain_make_primary", kwargs={"tenant_id": portal_tenant.id, "domain_id": d2.id})
    )
    assert r.status_code == 302
    d1.refresh_from_db()
    d2.refresh_from_db()
    portal_tenant.refresh_from_db()
    assert d2.is_primary and not d1.is_primary
    assert portal_tenant.sending_domain == "b.example.com"
    assert TenantDomain.objects.filter(tenant=portal_tenant, is_primary=True).count() == 1


@pytest.mark.django_db
def test_editor_can_view_domains_but_not_create(
    client, customer_account, editor_user, editor_membership, portal_tenant
):
    TenantDomain.objects.create(
        tenant=portal_tenant,
        domain="v.example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
    )
    bind_portal_account_session(client, editor_user, customer_account)
    r_list = client.get(reverse("portal:tenant_domain_list", kwargs={"tenant_id": portal_tenant.id}))
    assert r_list.status_code == 200
    r_new = client.post(
        reverse("portal:tenant_domain_new", kwargs={"tenant_id": portal_tenant.id}),
        {"domain": "nope.example.com"},
    )
    assert r_new.status_code == 403


@pytest.mark.django_db
def test_viewer_can_list_domains(client, viewer_user, customer_account, viewer_membership, portal_tenant):
    bind_portal_account_session(client, viewer_user, customer_account)
    r = client.get(reverse("portal:tenant_domain_list", kwargs={"tenant_id": portal_tenant.id}))
    assert r.status_code == 200


@override_settings(SKYMAILR_SPF_INCLUDE_HINT="spf.sky.test", SKYMAILR_DKIM_SELECTOR="postal")
@pytest.mark.django_db
def test_check_tenant_domain_dns_verified_when_all_match(db):
    acc = Account.objects.create(name="Dns Acc", slug="dns-acc", status=AccountStatus.ACTIVE)
    tenant = Tenant.objects.create(
        account=acc,
        name="Dns T",
        slug="dns-t",
        status=TenantStatus.ACTIVE,
    )
    td = TenantDomain.objects.create(
        tenant=tenant,
        domain="example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
        dkim_txt_value="v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA",
        dkim_selector="postal",
    )

    def fake_resolve(qname: str) -> list[str]:
        q = qname.lower().rstrip(".")
        if q == "example.com":
            return ['v=spf1 include:spf.sky.test ~all']
        if q == "postal._domainkey.example.com":
            return ["v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA"]
        if q == "_dmarc.example.com":
            return ["v=DMARC1; p=none; rua=mailto:a@example.com"]
        return []

    check_tenant_domain_dns(td, resolve_txt=fake_resolve)
    assert td.verification_status == DomainVerificationStatus.VERIFIED
    assert td.verified is True
    assert td.spf_status == "pass"
    assert td.dkim_status == "pass"


@override_settings(SKYMAILR_SPF_INCLUDE_HINT="spf.sky.test")
@pytest.mark.django_db
def test_check_tenant_domain_dns_failed_when_no_txt_records(db):
    acc = Account.objects.create(name="Dns2", slug="dns2", status=AccountStatus.ACTIVE)
    tenant = Tenant.objects.create(
        account=acc,
        name="Dns T2",
        slug="dns-t2",
        status=TenantStatus.ACTIVE,
    )
    td = TenantDomain.objects.create(
        tenant=tenant,
        domain="empty.example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
        dkim_txt_value="v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA",
        dkim_selector="postal",
    )

    def empty(_q: str) -> list[str]:
        return []

    check_tenant_domain_dns(td, resolve_txt=empty)
    assert td.verification_status == DomainVerificationStatus.FAILED_CHECK
    assert td.verified is False


@pytest.mark.django_db
def test_sender_profile_detail_shows_verified_mismatch_warning(
    client, customer_user, customer_account, portal_tenant
):
    from apps.tenants.models import SenderCategory, SenderProfile

    TenantDomain.objects.create(
        tenant=portal_tenant,
        domain="good.com",
        verified=True,
        verification_status=DomainVerificationStatus.VERIFIED,
        is_primary=True,
    )
    sp = SenderProfile.objects.create(
        tenant=portal_tenant,
        name="Main",
        category=SenderCategory.TRANSACTIONAL,
        from_name="X",
        from_email="bad@other.com",
        is_active=True,
    )
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.get(reverse("portal:sender_profile_detail", kwargs={"profile_id": sp.id}))
    assert r.status_code == 200
    body = r.content.decode().lower()
    assert "verified" in body
    assert "not on" in body or "does not match" in body or "aligned" in body


@pytest.mark.django_db
def test_tenant_detail_includes_readiness(client, customer_user, customer_account, portal_tenant):
    bind_portal_account_session(client, customer_user, customer_account)
    r = client.get(reverse("portal:tenant_detail", kwargs={"tenant_id": portal_tenant.id}))
    assert r.status_code == 200
    assert b"Sending readiness" in r.content


@pytest.mark.django_db
@patch("apps.ui.views.portal_tenant_domains.process_postal_for_tenant_domain", return_value=())
def test_free_plan_redirects_when_sending_domain_limit_reached(
    _mock_pp, client, customer_user, customer_account, portal_tenant
):
    TenantDomain.objects.create(
        tenant=portal_tenant,
        domain="one.example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
    )
    TenantDomain.objects.create(
        tenant=portal_tenant,
        domain="two.example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
    )
    bind_portal_account_session(client, customer_user, customer_account)
    url = reverse("portal:tenant_domain_new", kwargs={"tenant_id": portal_tenant.id})
    r_get = client.get(url)
    assert r_get.status_code == 302
    assert r_get.url == reverse("portal:tenant_domain_list", kwargs={"tenant_id": portal_tenant.id})
    r_post = client.post(url, {"domain": "three.example.com"})
    assert r_post.status_code == 302
    assert r_post.url == reverse("portal:tenant_domain_list", kwargs={"tenant_id": portal_tenant.id})
    assert not TenantDomain.objects.filter(tenant=portal_tenant, domain="three.example.com").exists()


@pytest.mark.django_db
@patch("apps.ui.views.portal_tenant_domains.process_postal_for_tenant_domain", return_value=())
def test_plan_override_allows_third_sending_domain(
    _mock_pp, client, customer_user, customer_account, portal_tenant
):
    customer_account.metadata = {"plan_limits_override": {"max_sending_domains_per_tenant": 5}}
    customer_account.save()
    TenantDomain.objects.create(
        tenant=portal_tenant,
        domain="one.example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
    )
    TenantDomain.objects.create(
        tenant=portal_tenant,
        domain="two.example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
    )
    bind_portal_account_session(client, customer_user, customer_account)
    url = reverse("portal:tenant_domain_new", kwargs={"tenant_id": portal_tenant.id})
    r = client.post(url, {"domain": "three.example.com"})
    assert r.status_code == 302
    assert TenantDomain.objects.filter(tenant=portal_tenant, domain="three.example.com").exists()


@pytest.mark.django_db
def test_staff_operator_dashboard_still_ok(staff_client):
    r = staff_client.get(reverse("ui:dashboard"))
    assert r.status_code == 200
