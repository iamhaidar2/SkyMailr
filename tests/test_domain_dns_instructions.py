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
from apps.providers.domain_records import get_expected_dns_records
from apps.tenants.services.domain_verification import (
    check_tenant_domain_dns,
    dispatch_should_block_unverified_managed_domain,
    evaluate_dns_instruction_rows,
)
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
    assert inst.rows[0].title == "Domain control verification"
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
def test_return_path_and_mx_derived_from_postal_style_spf_include():
    td = TenantDomain(
        domain="kanassist.com",
        spf_txt_expected="v=spf1 a mx include:spf.postal.skymailr.com ~all",
        dkim_txt_value="v=DKIM1; p=KEYMATERIAL",
        dkim_selector="postal",
    )
    inst = build_dns_instructions_for_domain(td)
    rp = next(r for r in inst.rows if r.kind == "return_path")
    assert rp.record_type == "CNAME"
    assert rp.host_label == "psrp"
    assert rp.value == "rp.postal.skymailr.com"
    assert any(r.kind == "mx" and r.value == "10 mx.postal.skymailr.com" for r in inst.rows)


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
    assert "Domain control verification" in (td.verification_notes or "")
    assert "detected in DNS" in (td.verification_notes or "")


@pytest.mark.django_db
def test_get_expected_dns_records_matches_build():
    td = TenantDomain(domain="x.com", spf_txt_expected="v=spf1 ~all", dkim_txt_value="v=DKIM1; p=AB", dkim_selector="s")
    assert get_expected_dns_records(td).domain_fqdn == build_dns_instructions_for_domain(td).domain_fqdn


@pytest.mark.django_db
def test_evaluate_spf_pass_and_mismatch():
    td = TenantDomain(
        domain="spf-eval.example",
        spf_txt_expected="v=spf1 include:z ~all",
        dkim_txt_value="v=DKIM1; p=KEY",
        dkim_selector="postal",
    )

    def ok_resolve(q: str) -> list[str]:
        q = q.lower().rstrip(".")
        if q == "spf-eval.example":
            return ["v=spf1 include:z ~all"]
        if q == "postal._domainkey.spf-eval.example":
            return ["v=DKIM1; p=KEY"]
        if q == "_dmarc.spf-eval.example":
            return ["v=DMARC1; p=none"]
        return []

    rows, _ = evaluate_dns_instruction_rows(td, resolve_txt=ok_resolve)
    spf_row = next(r for r in rows if r.kind == "spf")
    assert spf_row.check_status == "pass"

    def bad_spf(q: str) -> list[str]:
        q = q.lower().rstrip(".")
        if q == "spf-eval.example":
            return ["v=spf1 include:other ~all"]
        if q == "postal._domainkey.spf-eval.example":
            return ["v=DKIM1; p=KEY"]
        if q == "_dmarc.spf-eval.example":
            return ["v=DMARC1; p=none"]
        return []

    rows2, _ = evaluate_dns_instruction_rows(td, resolve_txt=bad_spf)
    assert next(r for r in rows2 if r.kind == "spf").check_status == "mismatch"


@pytest.mark.django_db
def test_evaluate_return_path_cname_pass_and_mismatch():
    td = TenantDomain(
        domain="rp.example",
        spf_txt_expected="v=spf1 include:x ~all",
        dkim_txt_value="v=DKIM1; p=K",
        dkim_selector="postal",
        return_path_cname_name="bounce.rp.example",
        return_path_cname_target="target.provider.test",
    )

    def txt(q: str) -> list[str]:
        q = q.lower().rstrip(".")
        if q == "rp.example":
            return ["v=spf1 include:x ~all"]
        if q == "postal._domainkey.rp.example":
            return ["v=DKIM1; p=K"]
        if q == "_dmarc.rp.example":
            return ["v=DMARC1; p=none"]
        return []

    def cname_ok(q: str) -> str | None:
        if normalize_fqdn(q) == "bounce.rp.example":
            return "target.provider.test"
        return None

    rows, _ = evaluate_dns_instruction_rows(td, resolve_txt=txt, resolve_cname=cname_ok)
    rp = next(r for r in rows if r.kind == "return_path")
    assert rp.check_status == "pass"

    def cname_bad(q: str) -> str | None:
        return "wrong.example"

    rows2, _ = evaluate_dns_instruction_rows(td, resolve_txt=txt, resolve_cname=cname_bad)
    assert next(r for r in rows2 if r.kind == "return_path").check_status == "mismatch"


@pytest.mark.django_db
def test_dispatch_block_unverified_managed_domain(db, default_account):
    from apps.messages.models import MessageType, OutboundMessage, OutboundStatus
    from apps.tenants.models import Tenant, TenantStatus

    tenant = Tenant.objects.create(
        account=default_account,
        name="T",
        slug="t-dispatch",
        status=TenantStatus.ACTIVE,
        default_sender_email="noreply@managed.example",
    )
    TenantDomain.objects.create(
        tenant=tenant,
        domain="managed.example",
        verification_status=DomainVerificationStatus.UNVERIFIED,
        verified=False,
    )
    msg = OutboundMessage.objects.create(
        tenant=tenant,
        source_app="test",
        message_type=MessageType.TRANSACTIONAL,
        to_email="to@example.com",
        subject_rendered="S",
        html_rendered="<p>x</p>",
        text_rendered="x",
        status=OutboundStatus.QUEUED,
        metadata={},
    )
    with override_settings(EMAIL_PROVIDER="postal"):
        blocked, reason = dispatch_should_block_unverified_managed_domain(msg)
    assert blocked is True
    assert "not verified" in reason.lower()

    msg.metadata = {"bypass_domain_verification": True}
    with override_settings(EMAIL_PROVIDER="postal"):
        assert dispatch_should_block_unverified_managed_domain(msg)[0] is False


@pytest.mark.django_db
def test_dispatch_allows_when_no_tenant_domain_row(db, default_account):
    from apps.messages.models import MessageType, OutboundMessage, OutboundStatus
    from apps.tenants.models import Tenant, TenantStatus

    tenant = Tenant.objects.create(
        account=default_account,
        name="T2",
        slug="t-dispatch-2",
        status=TenantStatus.ACTIVE,
        default_sender_email="noreply@unlisted.example",
    )
    msg = OutboundMessage.objects.create(
        tenant=tenant,
        source_app="test",
        message_type=MessageType.TRANSACTIONAL,
        to_email="to@example.com",
        subject_rendered="S",
        html_rendered="<p>x</p>",
        text_rendered="x",
        status=OutboundStatus.QUEUED,
        metadata={},
    )
    with override_settings(EMAIL_PROVIDER="postal"):
        assert dispatch_should_block_unverified_managed_domain(msg)[0] is False


@pytest.mark.django_db
def test_dispatch_dummy_provider_never_blocks(db, default_account):
    from apps.messages.models import MessageType, OutboundMessage, OutboundStatus
    from apps.tenants.models import Tenant, TenantStatus

    tenant = Tenant.objects.create(
        account=default_account,
        name="T3",
        slug="t-dispatch-3",
        status=TenantStatus.ACTIVE,
        default_sender_email="noreply@managed2.example",
    )
    TenantDomain.objects.create(
        tenant=tenant,
        domain="managed2.example",
        verification_status=DomainVerificationStatus.UNVERIFIED,
        verified=False,
    )
    msg = OutboundMessage.objects.create(
        tenant=tenant,
        source_app="test",
        message_type=MessageType.TRANSACTIONAL,
        to_email="to@example.com",
        subject_rendered="S",
        html_rendered="<p>x</p>",
        text_rendered="x",
        status=OutboundStatus.QUEUED,
        metadata={},
    )
    with override_settings(EMAIL_PROVIDER="dummy"):
        assert dispatch_should_block_unverified_managed_domain(msg)[0] is False


@pytest.mark.django_db
@override_settings(EMAIL_PROVIDER="postal")
@patch("apps.messages.services.dispatch.get_email_provider")
def test_email_dispatch_service_blocks_before_provider(mock_get, db, default_account):
    from unittest.mock import MagicMock

    from apps.messages.models import MessageType, OutboundMessage, OutboundStatus
    from apps.messages.services.dispatch import EmailDispatchService
    from apps.providers.base import SendResult
    from apps.tenants.models import Tenant, TenantStatus

    tenant = Tenant.objects.create(
        account=default_account,
        name="TDisp",
        slug="t-disp-svc",
        status=TenantStatus.ACTIVE,
        default_sender_email="noreply@blocksvc.example",
    )
    TenantDomain.objects.create(
        tenant=tenant,
        domain="blocksvc.example",
        verification_status=DomainVerificationStatus.UNVERIFIED,
        verified=False,
    )
    msg = OutboundMessage.objects.create(
        tenant=tenant,
        source_app="test",
        message_type=MessageType.TRANSACTIONAL,
        to_email="to@example.com",
        subject_rendered="S",
        html_rendered="<p>x</p>",
        text_rendered="x",
        status=OutboundStatus.QUEUED,
        metadata={},
    )
    prov = MagicMock()
    prov.name = "postal"
    prov.send_message = MagicMock(return_value=SendResult(success=True, provider_message_id="1", raw_response={}))
    mock_get.return_value = prov
    EmailDispatchService().dispatch(msg)
    prov.send_message.assert_not_called()
    msg.refresh_from_db()
    assert msg.status == OutboundStatus.FAILED


@pytest.mark.django_db
@override_settings(EMAIL_PROVIDER="postal")
@patch("apps.messages.services.dispatch.get_email_provider")
def test_email_dispatch_service_sends_when_domain_verified(mock_get, db, default_account):
    from unittest.mock import MagicMock

    from apps.messages.models import MessageType, OutboundMessage, OutboundStatus
    from apps.messages.services.dispatch import EmailDispatchService
    from apps.providers.base import SendResult
    from apps.tenants.models import Tenant, TenantStatus

    tenant = Tenant.objects.create(
        account=default_account,
        name="TDisp2",
        slug="t-disp-svc2",
        status=TenantStatus.ACTIVE,
        default_sender_email="noreply@goodsvc.example",
    )
    TenantDomain.objects.create(
        tenant=tenant,
        domain="goodsvc.example",
        verification_status=DomainVerificationStatus.VERIFIED,
        verified=True,
    )
    msg = OutboundMessage.objects.create(
        tenant=tenant,
        source_app="test",
        message_type=MessageType.TRANSACTIONAL,
        to_email="to@example.com",
        subject_rendered="S",
        html_rendered="<p>x</p>",
        text_rendered="x",
        status=OutboundStatus.QUEUED,
        metadata={},
    )
    prov = MagicMock()
    prov.name = "postal"
    prov.send_message = MagicMock(return_value=SendResult(success=True, provider_message_id="1", raw_response={}))
    mock_get.return_value = prov
    EmailDispatchService().dispatch(msg)
    prov.send_message.assert_called_once()
    msg.refresh_from_db()
    assert msg.status == OutboundStatus.SENT


def test_send_raw_serializer_strips_internal_bypass_metadata():
    from apps.api.v1.serializers import SendRawSerializer, SendTemplateSerializer

    ser = SendRawSerializer(
        data={
            "to_email": "a@b.com",
            "subject": "Hi",
            "html_body": "<p>x</p>",
            "metadata": {"bypass_domain_verification": True, "customer": "ok"},
        }
    )
    assert ser.is_valid()
    assert ser.validated_data["metadata"] == {"customer": "ok"}

    tpl = SendTemplateSerializer(
        data={
            "template_key": "k",
            "to_email": "a@b.com",
            "metadata": {"bypass_domain_verification": True, "x": 1},
        }
    )
    assert tpl.is_valid()
    assert tpl.validated_data["metadata"] == {"x": 1}


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
