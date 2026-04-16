"""DNS checks for tenant domains — pluggable resolver for tests."""

from __future__ import annotations

import logging
import re
from typing import Callable

from django.conf import settings
from django.utils import timezone

from apps.tenants.models import DomainVerificationStatus, TenantDomain
from apps.tenants.services.domain_dns_instructions import normalize_fqdn
from apps.ui.tenant_validators import email_domain

logger = logging.getLogger(__name__)

ResolveTxtFn = Callable[[str], list[str]]


def _default_resolve_txt(qname: str) -> list[str]:
    try:
        import dns.resolver
        import dns.rdatatype
    except ImportError:
        logger.warning("dnspython not installed; DNS verification unavailable.")
        return []
    try:
        answers = dns.resolver.resolve(qname, "TXT")
    except Exception as exc:
        logger.debug("dns resolve %s: %s", qname, exc)
        return []
    out: list[str] = []
    for rdata in answers:
        chunks: list[str] = []
        for s in getattr(rdata, "strings", []) or []:
            chunks.append(s.decode("utf-8") if isinstance(s, (bytes, bytearray)) else str(s))
        if chunks:
            out.append("".join(chunks))
    return out


def _spf_include_hint() -> str:
    return (getattr(settings, "SKYMAILR_SPF_INCLUDE_HINT", None) or "").strip().lower()


def _dkim_selector() -> str:
    return (getattr(settings, "SKYMAILR_DKIM_SELECTOR", None) or "postal").strip()


def check_tenant_domain_dns(
    td: TenantDomain,
    *,
    resolve_txt: ResolveTxtFn | None = None,
) -> TenantDomain:
    """
    Query public DNS and update td status fields. Does not save — caller saves.
    """
    resolver = resolve_txt or _default_resolve_txt
    d = normalize_fqdn(td.domain)
    if not d:
        td.verification_status = DomainVerificationStatus.FAILED_CHECK
        td.verification_notes = "Invalid domain value."
        td.last_checked_at = timezone.now()
        return td

    spf_hint = _spf_include_hint()
    dkim_sel = _dkim_selector()
    dkim_name = f"{dkim_sel}._domainkey.{d}"

    spf_txts = resolver(d)
    spf_joined = " ".join(spf_txts).lower()
    spf_ok = bool(spf_hint and spf_hint in spf_joined and "v=spf1" in spf_joined)
    if not spf_hint:
        td.spf_status = "manual"
    elif spf_ok:
        td.spf_status = "pass"
    else:
        td.spf_status = "fail"

    dkim_txts = resolver(dkim_name)
    dkim_joined = " ".join(dkim_txts)
    dkim_ok = bool(re.search(r"\bp=", dkim_joined, re.I))
    if dkim_ok:
        td.dkim_status = "pass"
    elif dkim_joined:
        td.dkim_status = "partial"
    else:
        td.dkim_status = "fail"

    dmarc_txts = resolver(f"_dmarc.{d}")
    dmarc_joined = " ".join(dmarc_txts).lower()
    dmarc_ok = "v=dmarc1" in dmarc_joined
    if dmarc_ok:
        td.dmarc_status = "pass"
    elif dmarc_joined:
        td.dmarc_status = "partial"
    else:
        td.dmarc_status = "missing"

    if not spf_hint:
        overall = DomainVerificationStatus.PARTIALLY_VERIFIED
        notes = (
            "Automatic SPF check skipped — set SKYMAILR_SPF_INCLUDE_HINT to your provider’s include "
            "so SkyMailr can validate SPF. DKIM/DMARC checked against live DNS."
        )
    elif spf_ok and dkim_ok and dmarc_ok:
        overall = DomainVerificationStatus.VERIFIED
        notes = "SPF, DKIM, and DMARC records detected."
        td.verified = True
    elif spf_ok and dkim_ok:
        overall = DomainVerificationStatus.PARTIALLY_VERIFIED
        notes = "SPF and DKIM look good; add or tighten DMARC for full policy coverage."
        td.verified = True
    elif spf_ok or dkim_ok:
        overall = DomainVerificationStatus.PARTIALLY_VERIFIED
        notes = "Some records found; publish missing TXT records from the instructions below."
        td.verified = False
    else:
        overall = DomainVerificationStatus.DNS_PENDING
        notes = "No matching SPF/DKIM TXT records yet — DNS may still be propagating."
        td.verified = False

    if td.spf_status == "fail" and td.dkim_status == "fail" and spf_hint:
        overall = DomainVerificationStatus.FAILED_CHECK
        notes = "SPF/DKIM checks did not match expected patterns. Compare with Postal’s domain page."

    td.verification_status = overall
    td.verification_notes = notes
    td.last_checked_at = timezone.now()
    return td


def email_domain_matches_verified_tenant_domain(tenant, from_email: str) -> bool:
    """True if from_email is on a domain (or subdomain) that is verified for this tenant."""
    ed = email_domain(from_email)
    if not ed:
        return False
    qs = TenantDomain.objects.filter(
        tenant=tenant,
        verified=True,
        verification_status=DomainVerificationStatus.VERIFIED,
    )
    for td in qs:
        cfg = normalize_fqdn(td.domain)
        if not cfg:
            continue
        if ed == cfg or ed.endswith("." + cfg):
            return True
    return False
