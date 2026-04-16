"""Provider-aware DNS instruction rows for tenant sending domains (no customer-facing placeholders)."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.tenants.models import TenantDomain


@dataclass(frozen=True)
class DnsInstructionRow:
    kind: str  # spf | dkim | dmarc | return_path
    record_type: str
    name: str
    host_label: str
    value: str
    ttl: int
    title: str
    purpose: str
    # Staff-only provenance for admin/debug; never shown in customer templates.
    staff_source: str = ""


@dataclass(frozen=True)
class DnsInstructionSet:
    rows: tuple[DnsInstructionRow, ...]
    is_customer_ready: bool
    incomplete_message: str | None
    domain_fqdn: str


def normalize_fqdn(domain: str) -> str:
    d = (domain or "").strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix) :]
    if "/" in d:
        d = d.split("/")[0]
    return d.rstrip(".")


def registrable_root_for_mail(domain_fqdn: str) -> str:
    """Best-effort apex for DMARC aggregate mailto (last two labels)."""
    d = normalize_fqdn(domain_fqdn)
    parts = [p for p in d.split(".") if p]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return d


def host_label_for_record(full_name: str, domain_fqdn: str) -> str:
    """
    Host column for DNS UIs when the zone is the sending domain `domain_fqdn`.
    - Apex TXT: @
    - Subdomain: strip trailing .<domain>
    """
    d = normalize_fqdn(domain_fqdn)
    fn = normalize_fqdn(full_name)
    if fn == d:
        return "@"
    suffix = "." + d
    if fn.endswith(suffix) and len(fn) > len(suffix):
        return fn[: -len(suffix)]
    return fn


def _settings_spf_txt() -> str | None:
    hint = (getattr(settings, "SKYMAILR_SPF_INCLUDE_HINT", None) or "").strip()
    if not hint:
        return None
    return f"v=spf1 include:{hint} ~all"


def _settings_dkim_selector() -> str:
    return (getattr(settings, "SKYMAILR_DKIM_SELECTOR", None) or "postal").strip()


def _settings_return_path_target() -> str | None:
    v = (getattr(settings, "SKYMAILR_RETURN_PATH_HOST", None) or "").strip()
    return v or None


def resolve_expected_spf_txt(td: TenantDomain) -> tuple[str | None, str]:
    """Returns (spf_txt, provenance staff note)."""
    direct = (td.spf_txt_expected or "").strip()
    if direct:
        return direct, "domain"
    st = _settings_spf_txt()
    if st:
        return st, "operator_settings"
    return None, "missing"


def resolve_dkim(td: TenantDomain) -> tuple[str | None, str | None, str]:
    """Returns (selector, full_txt_value, provenance)."""
    txt = (td.dkim_txt_value or "").strip()
    if not txt:
        return None, None, "missing"
    sel = (td.dkim_selector or "").strip() or _settings_dkim_selector()
    return sel, txt, "domain_or_settings_selector"


def resolve_dmarc_txt(td: TenantDomain) -> tuple[str, str]:
    direct = (td.dmarc_txt_expected or "").strip()
    if direct:
        return direct, "domain"
    root = registrable_root_for_mail(td.domain)
    # Complete, valid default — optional aggregate reports to a sensible mailbox.
    val = f"v=DMARC1; p=none; rua=mailto:dmarc@{root}"
    return val, "computed_default"


def resolve_return_path(td: TenantDomain, d: str) -> tuple[str | None, str | None, str]:
    """Returns (cname_name_fqdn, target, provenance)."""
    tgt = (td.return_path_cname_target or "").strip() or _settings_return_path_target()
    if not tgt:
        return None, None, "missing"
    name = (td.return_path_cname_name or "").strip() or f"rp.{d}"
    return normalize_fqdn(name), tgt.rstrip("."), "domain_or_settings"


def build_dns_instructions_for_domain(td: TenantDomain) -> DnsInstructionSet:
    """
    Layered resolution:
    1) TenantDomain stored fields (sync/admin)
    2) Operator settings (SKYMAILR_*)
    3) Safe computed defaults (DMARC only — never placeholder tokens)
    """
    d = normalize_fqdn(td.domain)
    rows: list[DnsInstructionRow] = []

    spf_txt, spf_src = resolve_expected_spf_txt(td)
    dkim_sel, dkim_txt, dkim_src = resolve_dkim(td)
    dmarc_txt, dmarc_src = resolve_dmarc_txt(td)
    rp_name, rp_tgt, rp_src = resolve_return_path(td, d)

    if spf_txt:
        rows.append(
            DnsInstructionRow(
                kind="spf",
                record_type="TXT",
                name=d,
                host_label=host_label_for_record(d, d),
                value=spf_txt,
                ttl=300,
                title="SPF",
                purpose=(
                    "Tells receiving mail servers which providers are allowed to send email "
                    "using your domain name."
                ),
                staff_source=spf_src,
            )
        )

    if dkim_sel and dkim_txt:
        dkim_name = f"{dkim_sel}._domainkey.{d}"
        rows.append(
            DnsInstructionRow(
                kind="dkim",
                record_type="TXT",
                name=dkim_name,
                host_label=host_label_for_record(dkim_name, d),
                value=dkim_txt,
                ttl=300,
                title="DKIM",
                purpose=(
                    "Adds a digital signature to outgoing messages so receivers can verify they "
                    "were not altered in transit."
                ),
                staff_source=dkim_src,
            )
        )

    if rp_name and rp_tgt:
        rows.append(
            DnsInstructionRow(
                kind="return_path",
                record_type="CNAME",
                name=rp_name,
                host_label=host_label_for_record(rp_name, d),
                value=rp_tgt,
                ttl=300,
                title="Return path (bounces)",
                purpose=(
                    "Some providers use this hostname for bounce handling and reputation alignment."
                ),
                staff_source=rp_src,
            )
        )

    dmarc_name = f"_dmarc.{d}"
    rows.append(
        DnsInstructionRow(
            kind="dmarc",
            record_type="TXT",
            name=dmarc_name,
            host_label=host_label_for_record(dmarc_name, d),
            value=dmarc_txt,
            ttl=300,
            title="DMARC",
            purpose=(
                "Tells receivers what to do with messages that fail SPF/DKIM checks and can "
                "enable aggregate reporting."
            ),
            staff_source=dmarc_src,
        )
    )

    ready = bool(spf_txt and dkim_sel and dkim_txt)
    msg = None
    if not ready:
        msg = (
            "We’re still preparing the exact DNS values for this domain. "
            "Please try again later or contact support if this persists."
        )

    return DnsInstructionSet(
        rows=tuple(rows),
        is_customer_ready=ready,
        incomplete_message=msg,
        domain_fqdn=d,
    )


def build_dns_instructions(domain_fqdn: str) -> list[DnsInstructionRow]:
    """
    Backwards-compatible shim: builds a minimal in-memory TenantDomain for template/tests.
    Prefer build_dns_instructions_for_domain with a real TenantDomain in production.
    """
    td = TenantDomain(domain=domain_fqdn)
    inst = build_dns_instructions_for_domain(td)
    if not inst.is_customer_ready:
        return []
    return list(inst.rows)
