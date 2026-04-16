"""Generate customer-facing DNS rows from app configuration (Postal-agnostic templates)."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class DnsInstructionRow:
    record_type: str
    name: str
    value: str
    ttl: int
    purpose: str


def normalize_fqdn(domain: str) -> str:
    d = (domain or "").strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix) :]
    if "/" in d:
        d = d.split("/")[0]
    return d.rstrip(".")


def build_dns_instructions(domain_fqdn: str) -> list[DnsInstructionRow]:
    """
    Deterministic instructions from env-driven hints.
    Exact values often come from your Postal org — set SKYMAILR_* env vars in production.
    """
    d = normalize_fqdn(domain_fqdn)
    rows: list[DnsInstructionRow] = []

    spf_include = (getattr(settings, "SKYMAILR_SPF_INCLUDE_HINT", None) or "").strip()
    if spf_include:
        spf_value = f"v=spf1 include:{spf_include} ~all"
    else:
        spf_value = "v=spf1 include:YOUR_POSTAL_OR_PROVIDER_SPF ~all"
    rows.append(
        DnsInstructionRow(
            record_type="TXT",
            name=d,
            value=spf_value,
            ttl=300,
            purpose="SPF authorizes your provider to send mail for this domain.",
        )
    )

    dkim_selector = (getattr(settings, "SKYMAILR_DKIM_SELECTOR", None) or "postal").strip()
    dkim_name = f"{dkim_selector}._domainkey.{d}"
    rows.append(
        DnsInstructionRow(
            record_type="TXT",
            name=dkim_name,
            value="(copy the DKIM public key from Postal / your provider for this domain)",
            ttl=300,
            purpose="DKIM signs messages so receivers can authenticate your mail.",
        )
    )

    rp_host = (getattr(settings, "SKYMAILR_RETURN_PATH_HOST", None) or "").strip()
    if rp_host:
        rows.append(
            DnsInstructionRow(
                record_type="CNAME",
                name=f"rp.{d}",
                value=rp_host,
                ttl=300,
                purpose="Return-path / bounce handling (if your provider uses a CNAME here).",
            )
        )
    else:
        rows.append(
            DnsInstructionRow(
                record_type="CNAME",
                name=f"rp.{d}",
                value="(set SKYMAILR_RETURN_PATH_HOST when your provider gives you a target)",
                ttl=300,
                purpose="Optional return-path — only if your mail stack requires it.",
            )
        )

    dmarc_name = f"_dmarc.{d}"
    rows.append(
        DnsInstructionRow(
            record_type="TXT",
            name=dmarc_name,
            value="v=DMARC1; p=none; rua=mailto:dmarc@YOURDOMAIN",
            ttl=300,
            purpose="DMARC policy (start with p=none, tighten after monitoring).",
        )
    )

    return rows
