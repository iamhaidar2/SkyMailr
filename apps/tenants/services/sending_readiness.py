"""Aggregate “sending readiness” signals for customer portal panels."""

from __future__ import annotations

from apps.tenants.models import DomainVerificationStatus, Tenant
from apps.ui.tenant_validators import email_domain, normalize_domain


def compute_sending_readiness(tenant: Tenant) -> dict:
    domains = list(tenant.domains.all())
    verified = [
        d
        for d in domains
        if d.verified
        and d.verification_status == DomainVerificationStatus.VERIFIED
    ]
    primary = next((d for d in domains if d.is_primary), None)
    dns_ref = primary or (domains[0] if domains else None)
    default_email = (tenant.default_sender_email or "").strip()
    default_dom = email_domain(default_email) if default_email else ""

    def _matches_any_verified(dom: str) -> bool:
        if not dom:
            return False
        for d in verified:
            cfg = normalize_domain(d.domain)
            if dom == cfg or dom.endswith("." + cfg):
                return True
        return False

    issues: list[str] = []
    if not (tenant.sending_domain or "").strip():
        issues.append("Tenant sending domain is not set.")
    if not verified:
        issues.append("No verified sending domain yet — publish DNS and use Check records now in the portal.")
    if primary and primary.verification_status != DomainVerificationStatus.VERIFIED:
        issues.append("Primary domain is not fully verified.")
    if default_email and verified and not _matches_any_verified(default_dom):
        issues.append("Default sender email domain does not match a verified domain.")
    if tenant.sender_profiles.filter(is_active=True).count() == 0:
        issues.append("No active sender profiles.")

    return {
        "has_sending_domain_field": bool((tenant.sending_domain or "").strip()),
        "has_verified_domain": bool(verified),
        "has_primary": primary is not None,
        "primary_verified": bool(
            primary
            and primary.verification_status == DomainVerificationStatus.VERIFIED
        ),
        "sender_profile_count": tenant.sender_profiles.filter(is_active=True).count(),
        "default_sender_matches_verified": _matches_any_verified(default_dom) if default_email else None,
        "issues": issues,
        "warmup_note": (
            "After DNS is verified, start with low volume and monitor bounces. "
            "Warm up new domains gradually before large campaigns."
        ),
        "spf_status": (dns_ref.spf_status or "—") if dns_ref else "—",
        "dkim_status": (dns_ref.dkim_status or "—") if dns_ref else "—",
        "dmarc_status": (dns_ref.dmarc_status or "—") if dns_ref else "—",
        "dns_ref_domain": dns_ref.domain if dns_ref else "",
    }
