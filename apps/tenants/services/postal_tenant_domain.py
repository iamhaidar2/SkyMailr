"""Orchestrate Postal provisioning + DNS metadata sync for a TenantDomain."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

from apps.providers.postal_provisioning import (
    ProvisionOutcome,
    apply_dns_patch_to_tenant_domain,
    ensure_postal_domain_exists,
)
from apps.tenants.models import PostalProvisionStatus
from apps.tenants.services.domain_dns_instructions import build_dns_instructions_for_domain
from apps.tenants.services.domain_dns_sync import sync_domain_dns_metadata

if TYPE_CHECKING:
    from apps.tenants.models import TenantDomain

PROVISION_RETRY_SECONDS = 45

_DNS_FIELDS = (
    "spf_txt_expected",
    "dkim_selector",
    "dkim_txt_value",
    "return_path_cname_name",
    "return_path_cname_target",
    "dmarc_txt_expected",
    "postal_verification_txt_expected",
    "dns_source",
    "dns_last_synced_at",
)

_PROVISION_FIELDS = (
    "postal_provision_status",
    "postal_provision_error",
    "postal_provision_last_attempt_at",
    "postal_provider_domain_id",
)

_BRIDGE_MARKER_FIELDS = ("postal_verification_bridge_at",)


def _touch_dns_from_sync(td: TenantDomain) -> list[str]:
    changed: list[str] = []
    if sync_domain_dns_metadata(td, timeout=5.0):
        changed.extend(_DNS_FIELDS)
    return changed


def process_postal_for_tenant_domain(td: TenantDomain, *, force_provision: bool = False) -> list[str]:
    """
    Refresh DNS from Postal, run provisioning when needed (with cooldown), re-sync.
    Mutates td. Returns list of field names that may need persisting.
    """
    touched: list[str] = []

    touched.extend(_touch_dns_from_sync(td))

    inst = build_dns_instructions_for_domain(td)
    bridge_url = (getattr(settings, "POSTAL_PROVISIONING_URL", None) or "").strip()
    missing_pv = not (td.postal_verification_txt_expected or "").strip()
    needs_bridge_verification_fetch = (
        bool(bridge_url) and missing_pv and td.postal_verification_bridge_at is None
    )

    if inst.is_customer_ready and not needs_bridge_verification_fetch:
        if td.postal_provision_status != PostalProvisionStatus.EXISTS:
            td.postal_provision_status = PostalProvisionStatus.EXISTS
            td.postal_provision_error = ""
            touched.extend(_PROVISION_FIELDS)
        return list(dict.fromkeys(touched))

    now = timezone.now()
    # Always attempt provisioning when the bridge may still return postal_verification_txt_expected;
    # otherwise the 45s cooldown blocks every page load after sync filled SPF/DKIM from HTTP.
    can_run = force_provision or needs_bridge_verification_fetch
    if not can_run and td.postal_provision_last_attempt_at is None:
        can_run = True
    if not can_run and td.postal_provision_last_attempt_at is not None:
        delta = (now - td.postal_provision_last_attempt_at).total_seconds()
        can_run = delta >= PROVISION_RETRY_SECONDS

    if not can_run:
        return list(dict.fromkeys(touched))

    res = ensure_postal_domain_exists(td.domain)
    td.postal_provision_last_attempt_at = now
    touched.extend(_PROVISION_FIELDS)

    if res.dns_patch:
        if apply_dns_patch_to_tenant_domain(td, res.dns_patch):
            touched.extend(_DNS_FIELDS)

    if res.webhook_merged:
        td.postal_verification_bridge_at = now
        touched.extend(_BRIDGE_MARKER_FIELDS)

    if res.success:
        td.postal_provision_error = ""
        if res.outcome == ProvisionOutcome.CREATED:
            td.postal_provision_status = PostalProvisionStatus.CREATED
        else:
            td.postal_provision_status = PostalProvisionStatus.EXISTS
        if res.provider_domain_id:
            td.postal_provider_domain_id = res.provider_domain_id
    else:
        td.postal_provision_status = PostalProvisionStatus.FAILED
        td.postal_provision_error = (res.error_detail or res.error_code or "Unknown error.")[:4000]

    touched.extend(_touch_dns_from_sync(td))

    inst2 = build_dns_instructions_for_domain(td)
    if inst2.is_customer_ready:
        td.postal_provision_status = PostalProvisionStatus.EXISTS
        td.postal_provision_error = ""
        touched.extend(_PROVISION_FIELDS)

    return list(dict.fromkeys(touched))
