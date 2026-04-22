"""DNS checks for tenant domains — pluggable resolvers for tests."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

from django.utils import timezone

from apps.providers.domain_records import get_expected_dns_records
from apps.tenants.models import DomainVerificationStatus, TenantDomain
from apps.tenants.services.domain_dns_instructions import (
    DnsInstructionRow,
    normalize_fqdn,
    resolve_dmarc_txt,
    resolve_dkim,
    resolve_expected_spf_txt,
)
from apps.ui.tenant_validators import email_domain

logger = logging.getLogger(__name__)

ResolveTxtFn = Callable[[str], list[str]]
ResolveCnameFn = Callable[[str], str | None]
ResolveMxFn = Callable[[str], list[tuple[int, str]]]

RecordCheckStatus = str  # pass | missing | mismatch | unknown


@dataclass(frozen=True)
class DnsInstructionCheckRow:
    """Instruction row plus live check status for customer UI."""

    kind: str
    record_type: str
    name: str
    host_label: str
    value: str
    ttl: int
    title: str
    purpose: str
    check_status: RecordCheckStatus


def _dns_lib_available() -> bool:
    try:
        import dns.resolver  # noqa: F401
    except ImportError:
        return False
    return True


def _default_resolve_txt(qname: str) -> list[str]:
    try:
        import dns.resolver
    except ImportError:
        logger.warning("dnspython not installed; DNS verification unavailable.")
        return []
    try:
        answers = dns.resolver.resolve(qname, "TXT")
    except Exception as exc:
        logger.debug("dns resolve TXT %s: %s", qname, exc)
        return []
    out: list[str] = []
    for rdata in answers:
        chunks: list[str] = []
        for s in getattr(rdata, "strings", []) or []:
            chunks.append(s.decode("utf-8") if isinstance(s, (bytes, bytearray)) else str(s))
        if chunks:
            out.append("".join(chunks))
    return out


def _default_resolve_cname(qname: str) -> str | None:
    try:
        import dns.resolver
    except ImportError:
        return None
    try:
        answers = dns.resolver.resolve(qname, "CNAME")
        for rdata in answers:
            return str(rdata.target).rstrip(".").lower()
    except Exception as exc:
        logger.debug("dns resolve CNAME %s: %s", qname, exc)
        return None


def _default_resolve_mx(qname: str) -> list[tuple[int, str]]:
    try:
        import dns.resolver
    except ImportError:
        return []
    try:
        answers = dns.resolver.resolve(qname, "MX")
        out: list[tuple[int, str]] = []
        for rdata in answers:
            prio = int(rdata.preference)
            host = str(rdata.exchange).rstrip(".").lower()
            out.append((prio, host))
        return sorted(out, key=lambda x: x[0])
    except Exception as exc:
        logger.debug("dns resolve MX %s: %s", qname, exc)
        return []


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


def _dmarc_matches(live_joined: str, expected: str) -> bool:
    lj = live_joined.lower()
    if "v=dmarc1" not in lj:
        return False
    m = re.search(r"p=([a-z]+)", expected, re.I)
    if m:
        return f"p={m.group(1).lower()}" in lj
    return True


def _normalize_dns_hostname(h: str) -> str:
    return (h or "").strip().lower().rstrip(".")


def _parse_mx_instruction_value(val: str) -> tuple[int | None, str]:
    parts = (val or "").strip().split(None, 1)
    if len(parts) == 2 and parts[0].isdigit():
        return int(parts[0]), _normalize_dns_hostname(parts[1])
    return None, _normalize_dns_hostname(val)


def _postal_verification_txt_matches(apex_txts: list[str], expected: str) -> bool:
    joined = " ".join(apex_txts)
    compact_live = joined.replace(" ", "").lower()
    compact_exp = expected.replace(" ", "").lower()
    return compact_exp in compact_live or expected in joined


def _append_domain_control_verification_note(
    td: TenantDomain,
    *,
    apex_fqdn: str,
    resolver: ResolveTxtFn,
) -> None:
    """When a domain-control TXT is expected at the apex, note whether public DNS shows it."""
    pv = (td.postal_verification_txt_expected or "").strip()
    if not pv:
        return
    apex_txts = resolver(apex_fqdn)
    ok = _postal_verification_txt_matches(apex_txts, pv)
    extra = (
        "Domain control verification (TXT at your domain apex): detected in DNS."
        if ok
        else (
            "Domain control verification (TXT at your domain apex): not detected yet — "
            "add the verification TXT from the table at the same host as SPF (@ or apex)."
        )
    )
    base = (td.verification_notes or "").strip()
    td.verification_notes = f"{base} {extra}".strip() if base else extra


def evaluate_dns_instruction_rows(
    td: TenantDomain,
    *,
    resolve_txt: ResolveTxtFn | None = None,
    resolve_cname: ResolveCnameFn | None = None,
    resolve_mx: ResolveMxFn | None = None,
) -> tuple[tuple[DnsInstructionCheckRow, ...], bool]:
    """
    Live per-record status for each expected DNS row.

    Returns (rows, dns_lib_available). Status is one of: pass, missing, mismatch, unknown.
    """
    resolver_txt = resolve_txt or _default_resolve_txt
    resolver_cname = resolve_cname or _default_resolve_cname
    resolver_mx = resolve_mx or _default_resolve_mx
    lib_ok = _dns_lib_available()

    inst = get_expected_dns_records(td)
    d = normalize_fqdn(td.domain)
    spf_expected, _ = resolve_expected_spf_txt(td)
    dkim_sel, dkim_expected, _ = resolve_dkim(td)
    dmarc_expected, _ = resolve_dmarc_txt(td)

    spf_joined = " ".join(resolver_txt(d)) if d else ""
    dkim_name = f"{dkim_sel}._domainkey.{d}" if dkim_sel and d else ""
    dkim_joined = " ".join(resolver_txt(dkim_name)) if dkim_name else ""
    dmarc_joined = " ".join(resolver_txt(f"_dmarc.{d}")) if d else ""

    out: list[DnsInstructionCheckRow] = []
    for row in inst.rows:
        status: RecordCheckStatus = "unknown"
        if row.kind == "postal_verification":
            if not lib_ok:
                status = "unknown"
            elif not row.value.strip():
                status = "unknown"
            else:
                apex = normalize_fqdn(row.name)
                txts = resolver_txt(apex)
                if _postal_verification_txt_matches(txts, row.value.strip()):
                    status = "pass"
                elif not txts:
                    status = "missing"
                else:
                    status = "mismatch"
        elif row.kind == "spf":
            if not spf_expected:
                status = "unknown"
            elif not lib_ok:
                status = "unknown"
            elif _spf_matches_expectation(spf_joined, row.value):
                status = "pass"
            elif not spf_joined or "v=spf1" not in spf_joined.lower():
                status = "missing"
            else:
                status = "mismatch"
        elif row.kind == "dkim":
            if not (dkim_expected and dkim_sel):
                status = "unknown"
            elif not lib_ok:
                status = "unknown"
            else:
                exp_p = _extract_dkim_p(dkim_expected)
                live_p = _extract_dkim_p(dkim_joined)
                if exp_p and live_p and exp_p == live_p:
                    status = "pass"
                elif not live_p or not re.search(r"\bp=", dkim_joined, re.I):
                    status = "missing"
                else:
                    status = "mismatch"
        elif row.kind == "dmarc":
            if not lib_ok:
                status = "unknown"
            elif _dmarc_matches(dmarc_joined, dmarc_expected):
                status = "pass"
            elif not dmarc_joined:
                status = "missing"
            elif "v=dmarc1" in dmarc_joined.lower():
                status = "mismatch"
            else:
                status = "missing"
        elif row.kind == "return_path":
            if not lib_ok:
                status = "unknown"
            elif row.record_type != "CNAME":
                status = "unknown"
            else:
                name = normalize_fqdn(row.name)
                expected_t = _normalize_dns_hostname(row.value)
                live_t = resolver_cname(name)
                if live_t is None:
                    status = "missing"
                elif _normalize_dns_hostname(live_t) == expected_t:
                    status = "pass"
                else:
                    status = "mismatch"
        elif row.kind == "mx":
            if not lib_ok:
                status = "unknown"
            else:
                _, expected_host = _parse_mx_instruction_value(row.value)
                if not expected_host:
                    status = "unknown"
                else:
                    live = resolver_mx(d)
                    hosts = [h for _, h in live]
                    if not live:
                        status = "missing"
                    elif expected_host in hosts:
                        status = "pass"
                    else:
                        status = "mismatch"
        else:
            status = "unknown"

        out.append(
            DnsInstructionCheckRow(
                kind=row.kind,
                record_type=row.record_type,
                name=row.name,
                host_label=row.host_label,
                value=row.value,
                ttl=row.ttl,
                title=row.title,
                purpose=row.purpose,
                check_status=status,
            )
        )
    return tuple(out), lib_ok


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

    _append_domain_control_verification_note(td, apex_fqdn=d, resolver=resolver)

    if not _dns_lib_available() and can_verify_all:
        note = (
            "DNS lookup library is not available on this server, so automated checks could not run. "
            "Contact support if this persists."
        )
        td.verification_notes = f"{(td.verification_notes or '').strip()} {note}".strip()

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
    for tdom in qs:
        cfg = normalize_fqdn(tdom.domain)
        if not cfg:
            continue
        if ed == cfg or ed.endswith("." + cfg):
            return True
    return False


def tenant_domain_for_from_hostname(tenant, host: str) -> TenantDomain | None:
    """Return the tenant's sending-domain row whose name matches this email domain, if any."""
    h = _normalize_dns_hostname(host)
    if not h:
        return None
    for tdom in tenant.domains.all():
        cfg = normalize_fqdn(tdom.domain)
        if not cfg:
            continue
        if h == cfg or h.endswith("." + cfg):
            return tdom
    return None


def dispatch_should_block_unverified_managed_domain(message) -> tuple[bool, str]:
    """
    If True, Postal dispatch must not send — From address belongs to a TenantDomain
    that is not fully verified.
    """
    from django.conf import settings

    provider = (getattr(settings, "EMAIL_PROVIDER", "") or "dummy").lower()
    if provider != "postal":
        return False, ""
    if getattr(settings, "SKYMAILR_ALLOW_UNVERIFIED_DOMAIN_SEND", False):
        return False, ""
    md = message.metadata or {}
    if md.get("bypass_domain_verification"):
        return False, ""

    profile = message.sender_profile
    tenant = message.tenant
    from_email = (profile.from_email if profile else tenant.default_sender_email) or ""
    ed = email_domain(from_email)
    if not ed:
        return False, ""

    tdom = tenant_domain_for_from_hostname(tenant, ed)
    if tdom is None:
        return False, ""

    if tdom.verified and tdom.verification_status == DomainVerificationStatus.VERIFIED:
        return False, ""

    return (
        True,
        f'Sending domain "{tdom.domain}" is not verified. Add the DNS records in the portal, '
        "then use Check records now before sending.",
    )
