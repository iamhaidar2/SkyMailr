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
def test_postal_verification_row_prepended_at_apex():
    td = TenantDomain(
        domain="tx.kanassist.com",
        postal_verification_txt_expected="postal-verification tok123",
        spf_txt_expected="v=spf1 include:spf.example ~all",
        dkim_txt_value="v=DKIM1; p=KEY",
        dkim_selector="postal",
    )
    inst = build_dns_instructions_for_domain(td)
    assert inst.is_customer_ready is True
    assert inst.rows[0].kind == "postal_verification"
    assert inst.rows[0].record_type == "TXT"
    assert inst.rows[0].name == "tx.kanassist.com"
    assert inst.rows[0].value == "postal-verification tok123"
    spf_row = next(r for r in inst.rows if r.kind == "spf")
    assert spf_row.name == "tx.kanassist.com"


@pytest.mark.django_db
def test_postal_verification_does_not_gate_customer_ready():
    td = TenantDomain(
        domain="early.example",
        postal_verification_txt_expected="postal-verification x",
    )
    inst = build_dns_instructions_for_domain(td)
    assert inst.is_customer_ready is False
    assert inst.rows[0].kind == "postal_verification"


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
def test_return_path_and_mx_rows_when_targets_present():
    td = TenantDomain(
        domain="send.example.com",
        spf_txt_expected="v=spf1 include:x ~all",
        dkim_txt_value="v=DKIM1; p=KEYMATERIAL",
        dkim_selector="postal",
        return_path_cname_name="psrp.send.example.com",
        return_path_cname_target="rp.postal.example.com",
        mx_targets=["mx1.postal.example.com", "mx2.postal.example.com"],
    )
    inst = build_dns_instructions_for_domain(td)
    kinds = [r.kind for r in inst.rows]
    assert "return_path" in kinds
    assert kinds.count("mx") == 2
    rp = next(r for r in inst.rows if r.kind == "return_path")
    assert rp.record_type == "CNAME"
    assert rp.value == "rp.postal.example.com"
    mx_rows = [r for r in inst.rows if r.kind == "mx"]
    assert mx_rows[0].value == "10 mx1.postal.example.com"
    assert mx_rows[1].value == "10 mx2.postal.example.com"


@pytest.mark.django_db
@override_settings(SKYMAILR_MX_TARGETS="mx.from.settings")
def test_mx_from_operator_settings_when_domain_mx_empty():
    td = TenantDomain(
        domain="mxset.example.com",
        spf_txt_expected="v=spf1 include:x ~all",
        dkim_txt_value="v=DKIM1; p=KEY",
        dkim_selector="postal",
    )
    inst = build_dns_instructions_for_domain(td)
    assert any(r.kind == "mx" and r.value == "10 mx.from.settings" for r in inst.rows)


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
def test_check_dns_appends_postal_verification_note_when_expected():
    acc = Account.objects.create(name="N2", slug="n2", status=AccountStatus.ACTIVE)
    tenant = Tenant.objects.create(account=acc, name="T2", slug="t2", status=TenantStatus.ACTIVE)
    td = TenantDomain.objects.create(
        tenant=tenant,
        domain="pv.example",
        verification_status=DomainVerificationStatus.UNVERIFIED,
        postal_verification_txt_expected="postal-verification ABC",
        spf_txt_expected="v=spf1 include:z ~all",
        dkim_txt_value="v=DKIM1; p=AAA",
        dkim_selector="postal",
    )

    def fake_resolve(qname: str) -> list[str]:
        q = qname.lower().rstrip(".")
        if q == "pv.example":
            return ["postal-verification ABC", "v=spf1 include:z ~all"]
        if q == "postal._domainkey.pv.example":
            return ["v=DKIM1; p=AAA"]
        if q == "_dmarc.pv.example":
            return ["v=DMARC1; p=none"]
        return []

    check_tenant_domain_dns(td, resolve_txt=fake_resolve)
    assert "Mail server domain verification" in (td.verification_notes or "")
    assert "detected in DNS" in (td.verification_notes or "")


@pytest.mark.django_db
@override_settings(SKYMAILR_SPF_INCLUDE_HINT="spf.sky.test")
@patch("apps.ui.views.portal_tenant_domains.process_postal_for_tenant_domain", return_value=[])
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
