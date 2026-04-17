"""Postal provisioning + portal wiring (mocked HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.test.utils import override_settings
from django.utils import timezone
from django.urls import reverse

from apps.accounts.models import Account, AccountMembership, AccountRole, AccountStatus
from apps.providers.postal_provisioning import (
    ProvisionOutcome,
    ProvisionResult,
    delete_postal_domain,
    ensure_postal_domain_exists,
)
from apps.tenants.models import DomainVerificationStatus, PostalProvisionStatus, Tenant, TenantDomain, TenantStatus
from apps.tenants.services.postal_tenant_domain import process_postal_for_tenant_domain
from tests.portal_helpers import bind_portal_account_session


@pytest.mark.django_db
def test_delete_postal_domain_skips_when_no_bridge():
    with override_settings(POSTAL_PROVISIONING_URL=""):
        ok, msg, bridge = delete_postal_domain("x.example.com")
    assert ok is True and msg is None and bridge is False


@pytest.mark.django_db
def test_delete_postal_domain_success_via_bridge():
    with patch("apps.providers.postal_provisioning.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=200,
            headers={"content-type": "application/json"},
            json=lambda: {"ok": True, "outcome": "deleted"},
        )
        with override_settings(
            POSTAL_BASE_URL="https://postal.test",
            POSTAL_SERVER_API_KEY="k",
            POSTAL_PROVISIONING_URL="https://bridge.test/",
            POSTAL_PROVISIONING_SECRET="secret",
        ):
            ok, msg, bridge = delete_postal_domain("gone.example.com")
    post.assert_called_once()
    call_kw = post.call_args
    assert "/delete" in (call_kw[0][0] if call_kw[0] else "")
    assert ok is True and msg is None and bridge is True


@pytest.mark.django_db
def test_ensure_postal_treats_existing_metadata_as_already_exists():
    with patch("apps.providers.postal_provisioning.fetch_domain_dns_metadata") as m:
        m.return_value = {
            "spf_txt_expected": "v=spf1 include:x ~all",
            "dkim_txt_value": "v=DKIM1; p=ABC",
            "dkim_selector": "postal",
        }
        r = ensure_postal_domain_exists("mail.example.com")
    assert r.success is True
    assert r.outcome == ProvisionOutcome.ALREADY_EXISTS


@pytest.mark.django_db
def test_ensure_postal_merges_bridge_dns_after_http_metadata():
    with patch("apps.providers.postal_provisioning.fetch_domain_dns_metadata") as m, patch(
        "apps.providers.postal_provisioning.httpx.post"
    ) as post:
        m.return_value = {
            "spf_txt_expected": "v=spf1 include:x ~all",
            "dkim_txt_value": "v=DKIM1; p=ABC",
            "dkim_selector": "postal",
        }
        post.return_value = MagicMock(
            status_code=200,
            headers={"content-type": "application/json"},
            json=lambda: {
                "ok": True,
                "outcome": "already_exists",
                "dns": {"postal_verification_txt_expected": "postal-verification TOKEN123"},
            },
        )
        with override_settings(
            POSTAL_BASE_URL="https://postal.test",
            POSTAL_SERVER_API_KEY="k",
            POSTAL_PROVISIONING_URL="https://bridge.test/",
            POSTAL_PROVISIONING_SECRET="s",
        ):
            r = ensure_postal_domain_exists("mail.example.com")
    assert r.success is True
    assert r.dns_patch.get("postal_verification_txt_expected") == "postal-verification TOKEN123"
    assert r.webhook_merged is True
    post.assert_called_once()


@pytest.mark.django_db
def test_merge_after_http_does_not_set_webhook_merged_when_pv_missing_and_not_verified():
    with patch("apps.providers.postal_provisioning.fetch_domain_dns_metadata") as m, patch(
        "apps.providers.postal_provisioning.httpx.post"
    ) as post:
        m.return_value = {
            "spf_txt_expected": "v=spf1 include:x ~all",
            "dkim_txt_value": "v=DKIM1; p=ABC",
            "dkim_selector": "postal",
        }
        post.return_value = MagicMock(
            status_code=200,
            headers={"content-type": "application/json"},
            json=lambda: {
                "ok": True,
                "outcome": "already_exists",
                "dns": {
                    "spf_txt_expected": "v=spf1 include:x ~all",
                    "dkim_txt_value": "v=DKIM1; p=ABC",
                },
            },
        )
        with override_settings(
            POSTAL_BASE_URL="https://postal.test",
            POSTAL_SERVER_API_KEY="k",
            POSTAL_PROVISIONING_URL="https://bridge.test/",
            POSTAL_PROVISIONING_SECRET="s",
        ):
            r = ensure_postal_domain_exists("nomailpv.example.com")
    assert r.success is True
    assert r.webhook_merged is False
    assert not r.dns_patch.get("postal_verification_txt_expected")


@pytest.mark.django_db
def test_merge_after_http_sets_webhook_merged_when_postal_domain_verified_without_pv():
    with patch("apps.providers.postal_provisioning.fetch_domain_dns_metadata") as m, patch(
        "apps.providers.postal_provisioning.httpx.post"
    ) as post:
        m.return_value = {
            "spf_txt_expected": "v=spf1 include:x ~all",
            "dkim_txt_value": "v=DKIM1; p=ABC",
            "dkim_selector": "postal",
        }
        post.return_value = MagicMock(
            status_code=200,
            headers={"content-type": "application/json"},
            json=lambda: {
                "ok": True,
                "outcome": "already_exists",
                "dns": {"spf_txt_expected": "v=spf1 include:x ~all"},
                "postal_domain_verified": True,
            },
        )
        with override_settings(
            POSTAL_BASE_URL="https://postal.test",
            POSTAL_SERVER_API_KEY="k",
            POSTAL_PROVISIONING_URL="https://bridge.test/",
            POSTAL_PROVISIONING_SECRET="s",
        ):
            r = ensure_postal_domain_exists("verified.example.com")
    assert r.success is True
    assert r.webhook_merged is True


@pytest.mark.django_db
def test_process_postal_fetches_verification_when_customer_ready_but_pv_missing():
    acc = Account.objects.create(name="A", slug="a-pv", status=AccountStatus.ACTIVE)
    tenant = Tenant.objects.create(account=acc, name="T", slug="t", status=TenantStatus.ACTIVE)
    td = TenantDomain.objects.create(
        tenant=tenant,
        domain="pv.example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
        spf_txt_expected="v=spf1 include:x ~all",
        dkim_txt_value="v=DKIM1; p=ABC",
        dkim_selector="postal",
        postal_provision_last_attempt_at=None,
    )
    with patch("apps.tenants.services.postal_tenant_domain.sync_domain_dns_metadata", return_value=False), patch(
        "apps.tenants.services.postal_tenant_domain.ensure_postal_domain_exists"
    ) as ens:
        ens.return_value = ProvisionResult(
            success=True,
            outcome=ProvisionOutcome.ALREADY_EXISTS,
            dns_patch={"postal_verification_txt_expected": "postal-verification ZZ"},
            webhook_merged=True,
        )
        with override_settings(
            POSTAL_PROVISIONING_URL="https://bridge.test/",
            POSTAL_BASE_URL="https://postal.test",
            POSTAL_SERVER_API_KEY="k",
        ):
            fields = process_postal_for_tenant_domain(td, force_provision=True)
    assert ens.called
    td.save(update_fields=list(dict.fromkeys(fields + ["updated_at"])))
    td.refresh_from_db()
    assert td.postal_verification_txt_expected == "postal-verification ZZ"
    assert td.postal_verification_bridge_at is not None


@pytest.mark.django_db
def test_process_postal_bypasses_cooldown_when_postal_verification_missing():
    """SPF/DKIM from HTTP + recent provision attempt must not block bridge merge for PV."""
    from datetime import timedelta

    acc = Account.objects.create(name="A2", slug="a2-pv", status=AccountStatus.ACTIVE)
    tenant = Tenant.objects.create(account=acc, name="T2", slug="t2", status=TenantStatus.ACTIVE)
    td = TenantDomain.objects.create(
        tenant=tenant,
        domain="cooldown.example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
        spf_txt_expected="v=spf1 include:x ~all",
        dkim_txt_value="v=DKIM1; p=ABC",
        dkim_selector="postal",
        postal_provision_last_attempt_at=timezone.now() - timedelta(seconds=5),
    )
    with patch("apps.tenants.services.postal_tenant_domain.sync_domain_dns_metadata", return_value=False), patch(
        "apps.tenants.services.postal_tenant_domain.ensure_postal_domain_exists"
    ) as ens:
        ens.return_value = ProvisionResult(
            success=True,
            outcome=ProvisionOutcome.ALREADY_EXISTS,
            dns_patch={"postal_verification_txt_expected": "postal-verification CD"},
            webhook_merged=True,
        )
        with override_settings(
            POSTAL_PROVISIONING_URL="https://bridge.test/",
            POSTAL_BASE_URL="https://postal.test",
            POSTAL_SERVER_API_KEY="k",
        ):
            process_postal_for_tenant_domain(td, force_provision=False)
    assert ens.called


@pytest.mark.django_db
def test_ensure_postal_webhook_success_applies_dns_patch():
    with patch("apps.providers.postal_provisioning.fetch_domain_dns_metadata", return_value=None), patch(
        "apps.providers.postal_provisioning.httpx.post"
    ) as post:
        post.return_value = MagicMock(
            status_code=200,
            headers={"content-type": "application/json"},
            json=lambda: {
                "ok": True,
                "outcome": "created",
                "dns": {"dkim_txt_value": "v=DKIM1; p=ZZZ", "spf_txt_expected": "v=spf1 include:a ~all"},
            },
        )
        with override_settings(
            POSTAL_BASE_URL="https://postal.test",
            POSTAL_SERVER_API_KEY="k",
            POSTAL_PROVISIONING_URL="https://bridge.test/provision",
            POSTAL_PROVISIONING_SECRET="secret",
        ):
            r = ensure_postal_domain_exists("new.example.com")
    assert r.success is True
    assert r.outcome == ProvisionOutcome.CREATED
    assert "dkim_txt_value" in r.dns_patch


@pytest.mark.django_db
def test_process_postal_sets_failed_when_provision_returns_error():
    acc = Account.objects.create(name="A", slug="a-prov", status=AccountStatus.ACTIVE)
    tenant = Tenant.objects.create(account=acc, name="T", slug="t", status=TenantStatus.ACTIVE)
    td = TenantDomain.objects.create(
        tenant=tenant,
        domain="orphan.example.com",
        verification_status=DomainVerificationStatus.UNVERIFIED,
    )
    with patch("apps.tenants.services.domain_dns_sync.fetch_domain_dns_metadata", return_value=None), patch(
        "apps.tenants.services.postal_tenant_domain.ensure_postal_domain_exists"
    ) as ens:
        ens.return_value = ProvisionResult(
            success=False,
            outcome=ProvisionOutcome.FAILED,
            error_code="postal_domain_api_unavailable",
            error_detail="No provisioning bridge configured.",
        )
        with override_settings(POSTAL_BASE_URL="https://postal.test", POSTAL_SERVER_API_KEY="k"):
            fields = process_postal_for_tenant_domain(td, force_provision=True)
    assert "postal_provision_status" in fields
    td.save(update_fields=list(dict.fromkeys(fields + ["updated_at"])))
    td.refresh_from_db()
    assert td.postal_provision_status == PostalProvisionStatus.FAILED


@pytest.mark.django_db
@patch("apps.tenants.services.postal_tenant_domain.ensure_postal_domain_exists")
@patch("apps.tenants.services.postal_tenant_domain.sync_domain_dns_metadata", return_value=False)
def test_new_domain_triggers_provision_and_sync(mock_sync, mock_ensure, client, django_user_model):
    mock_ensure.return_value = ProvisionResult(
        success=True,
        outcome=ProvisionOutcome.CREATED,
        dns_patch={"dkim_txt_value": "v=DKIM1; p=X", "spf_txt_expected": "v=spf1 include:y ~all"},
    )
    user = django_user_model.objects.create_user("u@e.com", password="x", email="u@e.com")
    acc = Account.objects.create(name="Co", slug="co", status=AccountStatus.ACTIVE)
    AccountMembership.objects.create(account=acc, user=user, role=AccountRole.OWNER, is_active=True)
    tenant = Tenant.objects.create(account=acc, name="App", slug="app", status=TenantStatus.ACTIVE)
    bind_portal_account_session(client, user, acc)
    url = reverse("portal:tenant_domain_new", kwargs={"tenant_id": tenant.id})
    r = client.post(url, {"domain": "provisioned.example.com"})
    assert r.status_code == 302
    td = TenantDomain.objects.get(domain="provisioned.example.com")
    assert mock_ensure.called
    assert td.postal_provision_status in (PostalProvisionStatus.CREATED, PostalProvisionStatus.EXISTS)


@pytest.mark.django_db
def test_account_isolation_retry_postal_other_account_404(client, django_user_model):
    user = django_user_model.objects.create_user("iso@e.com", password="x", email="iso@e.com")
    acc = Account.objects.create(name="Mine", slug="mine", status=AccountStatus.ACTIVE)
    AccountMembership.objects.create(account=acc, user=user, role=AccountRole.OWNER, is_active=True)
    other = Account.objects.create(name="O", slug="o", status=AccountStatus.ACTIVE)
    ot = Tenant.objects.create(account=other, name="OT", slug="ot", status=TenantStatus.ACTIVE)
    td = TenantDomain.objects.create(tenant=ot, domain="x.com", verification_status=DomainVerificationStatus.UNVERIFIED)
    bind_portal_account_session(client, user, acc)
    url = reverse("portal:tenant_domain_retry_postal", kwargs={"tenant_id": ot.id, "domain_id": td.id})
    r = client.post(url)
    assert r.status_code == 404
