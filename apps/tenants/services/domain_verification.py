"""DNS checks for tenant domains — pluggable resolver for tests."""

from __future__ import annotations

import logging
import re
from typing import Callable

from django.utils import timezone

from apps.tenants.models import DomainVerificationStatus, TenantDomain
from apps.tenants.services.domain_dns_instructions import (
    normalize_fqdn,
    resolve_dmarc_txt,
    resolve_dkim,
    resolve_expected_spf_txt,
)
from apps.ui.tenant_validators import email_domain

logger = logging.getLogger(__name__)

ResolveTxtFn = Callable[[str], list[str]]


def _default_resolve_txt(qname: str) -> list[str]:
    try:
        import dns.resolver
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


def _extract_dkim_p(txt: str) -> str | None:
    compact = re.sub(r"\s+", "", txt)
    m = re.search(r"\bp=([A-Za-z0-9+/=]+)", compact, re.I)
    return m.group(1) if m else None


def _spf_matches_expectation(live_joined: str, expected: str) -> bool:
    lj = live_joined.lower()
    ex = expected.strip().lower()
    if not ex:
        return False
    if ex.replace(" ", "") in lj.replace(" ", ""):
        return True
    if "v=spf1" not in lj:
        return False
    includes = re.findall(r"include:([^\s;]+)", ex)
    if includes:
        return all(inc.rstrip(".").lower() in lj for inc in includes)
    return False


def _append_postal_verification_dns_note(
    td: TenantDomain,
    *,
    apex_fqdn: str,
    resolver: ResolveTxtFn,
) -> None:
    """When Postal expects a domain-control TXT at the apex, note whether DNS shows it."""
    pv = (td.postal_verification_txt_expected or "").strip()
    if not pv:
        return
    apex_txts = resolver(apex_fqdn)
    joined = " ".join(apex_txts)
    compact_live = joined.replace(" ", "").lower()
    compact_exp = pv.replace(" ", "").lower()
    ok = compact_exp in compact_live or pv in joined
    extra = (
        "Mail server domain verification (TXT at your domain name): detected in DNS."
        if ok
        else (
            "Mail server domain verification (TXT at your domain name): not detected yet — "
            "add the verification TXT value from the DNS table at the same host as SPF (@ or apex)."
        )
    )
    base = (td.verification_notes or "").strip()
    td.verification_notes = f"{base} {extra}".strip() if base else extra


def _dmarc_matches(live_joined: str, expected: str) -> bool:
    lj = live_joined.lower()
    if "v=dmarc1" not in lj:
        return False
    m = re.search(r"p=([a-z]+)", expected, re.I)
    if m:
        return f"p={m.group(1).lower()}" in lj
    return True


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
        td.verification_notes = "This domain value is not valid."
        td.last_checked_at = timezone.now()
        return td

    spf_expected, _ = resolve_expected_spf_txt(td)
    dkim_sel, dkim_expected, _ = resolve_dkim(td)
    dmarc_expected, _ = resolve_dmarc_txt(td)

    spf_txts = resolver(d)
    spf_joined = " ".join(spf_txts)

    if spf_expected:
        spf_ok = _spf_matches_expectation(spf_joined, spf_expected)
        td.spf_status = "pass" if spf_ok else "fail"
    else:
        spf_ok = False
        td.spf_status = "manual"

    dkim_name = f"{dkim_sel}._domainkey.{d}" if dkim_sel else ""
    dkim_txts = resolver(dkim_name) if dkim_name else []
    dkim_joined = " ".join(dkim_txts)

    dkim_ok = False
    if dkim_expected and dkim_sel:
        exp_p = _extract_dkim_p(dkim_expected)
        live_p = _extract_dkim_p(dkim_joined)
        if exp_p and live_p and exp_p == live_p:
            td.dkim_status = "pass"
            dkim_ok = True
        elif live_p and exp_p and exp_p != live_p:
            td.dkim_status = "fail"
        elif re.search(r"\bp=", dkim_joined, re.I) and exp_p:
            td.dkim_status = "fail"
        else:
            td.dkim_status = "fail"
    else:
        if dkim_joined and re.search(r"\bp=", dkim_joined, re.I):
            td.dkim_status = "partial"
        elif dkim_joined:
            td.dkim_status = "partial"
        else:
            td.dkim_status = "manual"

    dmarc_txts = resolver(f"_dmarc.{d}")
    dmarc_joined = " ".join(dmarc_txts)
    dmarc_ok = _dmarc_matches(dmarc_joined, dmarc_expected) if dmarc_expected else False
    if dmarc_ok:
        td.dmarc_status = "pass"
    elif dmarc_joined and "v=dmarc1" in dmarc_joined.lower():
        td.dmarc_status = "partial"
    elif dmarc_joined:
        td.dmarc_status = "partial"
    else:
        td.dmarc_status = "missing"

    can_verify_all = bool(spf_expected and dkim_expected)

    if not can_verify_all:
        td.verification_status = DomainVerificationStatus.PARTIALLY_VERIFIED
        td.verified = False
        td.verification_notes = (
            "We do not yet have the full expected DNS values for this domain "
            "(SPF and DKIM). Contact support or wait until your domain page shows complete records."
        )
        td.last_checked_at = timezone.now()
        return td

    if spf_ok and dkim_ok and dmarc_ok:
        td.verification_status = DomainVerificationStatus.VERIFIED
        td.verified = True
        td.verification_notes = (
            "SPF, DKIM, and DMARC match the values we expect for this domain."
        )
    elif spf_ok and dkim_ok:
        td.verification_status = DomainVerificationStatus.PARTIALLY_VERIFIED
        td.verified = True
        td.verification_notes = (
            "SPF and DKIM match. DMARC is not present yet or does not match the suggested record."
        )
    elif spf_ok or dkim_ok:
        td.verification_status = DomainVerificationStatus.PARTIALLY_VERIFIED
        td.verified = False
        td.verification_notes = (
            "Some DNS records match, but others do not yet. Compare each row below with your DNS host."
        )
    elif not spf_ok and not dkim_ok:
        td.verification_status = DomainVerificationStatus.FAILED_CHECK
        td.verified = False
        td.verification_notes = (
            "We could not confirm SPF or DKIM yet. If you already published records, DNS may still be updating."
        )

    _append_postal_verification_dns_note(td, apex_fqdn=d, resolver=resolver)
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
