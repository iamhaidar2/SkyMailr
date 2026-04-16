"""DNS instruction builder and customer portal HTML guards."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test.utils import override_settings
from django.urls import reverse

from apps.accounts.models import Account, AccountMembership, AccountRole, AccountStatus
from apps.tenants.models import DomainVerificationStatus, Tenant, TenantDomain, TenantStatus
from apps.tenants.services.domain_dns_instructions import (
    build_dns_instructions_for_domain,
    host_label_for_record,
    normalize_fqdn,
)
from apps.tenants.services.domain_verification import check_tenant_domain_dns
from tests.portal_helpers import bind_portal_account_session


@pytest.mark.django_db
def test_host_label_apex_and_subdomain():
    d = "mail.example.com"
    assert host_label_for_record("mail.example.com", d) == "@"
    assert host_label_for_record("postal._domainkey.mail.example.com", d) == "postal._domainkey"


@pytest.mark.django_db
def test_is_customer_ready_requires_dkim_key_material():
    td = TenantDomain(domain="a.com")
    td.spf_txt_expected = "v=spf1 include:x ~all"
    inst = build_dns_instructions_for_domain(td)
    assert inst.is_customer_ready is False
    assert inst.incomplete_message

    td2 = TenantDomain(
        domain="a.com",
        spf_txt_expected="v=spf1 include:x ~all",
        dkim_txt_value="v=DKIM1; p=abc",
        dkim_selector="s1",
    )
    inst2 = build_dns_instructions_for_domain(td2)
    assert inst2.is_customer_ready is True


@pytest.mark.django_db
@override_settings(SKYMAILR_SPF_INCLUDE_HINT="spf.op.example", SKYMAILR_RETURN_PATH_HOST="rp.provider.test")
def test_layered_resolution_from_settings():
    td = TenantDomain(domain="b.com", dkim_txt_value="v=DKIM1; p=KEYMATERIAL")
    inst = build_dns_instructions_for_domain(td)
    assert inst.is_customer_ready is True
    kinds = {r.kind for r in inst.rows}
    assert "spf" in kinds and "dkim" in kinds and "dmarc" in kinds
    spf_row = next(r for r in inst.rows if r.kind == "spf")
    assert "include:spf.op.example" in spf_row.value
    assert "YOUR_" not in spf_row.value
    dmarc_row = next(r for r in inst.rows if r.kind == "dmarc")
    assert "mailto:dmarc@" in dmarc_row.value
    assert "YOURDOMAIN" not in dmarc_row.value.lower()


@pytest.mark.django_db
def test_verification_notes_plain_language_no_env_names():
    acc = Account.objects.create(name="N", slug="n-env", status=AccountStatus.ACTIVE)
    tenant = Tenant.objects.create(account=acc, name="T", slug="t", status=TenantStatus.ACTIVE)
    td = TenantDomain.objects.create(
        tenant=tenant,
        domain="plain.example",
        verification_status=DomainVerificationStatus.UNVERIFIED,
        spf_txt_expected="v=spf1 include:z ~all",
        dkim_txt_value="v=DKIM1; p=AAA",
        dkim_selector="postal",
    )

    def fake_resolve(qname: str) -> list[str]:
        q = qname.lower().rstrip(".")
        if q == "plain.example":
            return ["v=spf1 include:z ~all"]
        if q == "postal._domainkey.plain.example":
            return ["v=DKIM1; p=AAA"]
        if q == "_dmarc.plain.example":
            return ["v=DMARC1; p=none"]
        return []

    check_tenant_domain_dns(td, resolve_txt=fake_resolve)
    assert "SKYMAILR" not in (td.verification_notes or "").upper()


@pytest.mark.django_db
@override_settings(SKYMAILR_SPF_INCLUDE_HINT="spf.sky.test")
@patch("apps.ui.views.portal_tenant_domains.sync_domain_dns_metadata", return_value=False)
def test_domain_detail_page_has_no_placeholder_tokens(
    sync_mock, client, django_user_model
):
    user = django_user_model.objects.create_user("p@e.com", password="x", email="p@e.com")
    acc = Account.objects.create(name="P Co", slug="p-co", status=AccountStatus.ACTIVE)
    AccountMembership.objects.create(account=acc, user=user, role=AccountRole.OWNER, is_active=True)
    tenant = Tenant.objects.create(account=acc, name="App", slug="app", status=TenantStatus.ACTIVE)
    td = TenantDomain.objects.create(
        tenant=tenant,
        domain="ready.example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
        dkim_txt_value="v=DKIM1; k=rsa; p=MIIB",
        dkim_selector="postal",
    )
    bind_portal_account_session(client, user, acc)
    url = reverse("portal:tenant_domain_detail", kwargs={"tenant_id": tenant.id, "domain_id": td.id})
    r = client.get(url)
    assert r.status_code == 200
    body = r.content.decode()
    assert "YOUR_POSTAL" not in body
    assert "YOURDOMAIN" not in body
    assert "(copy the DKIM" not in body
    assert "SKYMAILR_" not in body
