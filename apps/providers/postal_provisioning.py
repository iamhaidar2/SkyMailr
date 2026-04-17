"""
Ensure a sending domain exists in Postal and optionally receive DNS material.

Stock Postal (github.com/postalserver/postal) exposes only legacy JSON APIs for
send/message under /api/v1 — not domain CRUD with X-Server-API-Key. Domain
management is through the web UI (session + CSRF). Therefore:

1) **Recommended:** set POSTAL_PROVISIONING_URL to a small HTTPS service you run
   next to Postal (e.g. rails runner, docker exec) that creates the Domain record
   and returns JSON including SPF/DKIM TXT values.

2) **Optional:** we still try a few experimental POST paths with the server API key
   for forks/custom installs; results are logged, never silent.

3) **Discovery:** if fetch_domain_dns_metadata already returns records, we treat the
   domain as present in Postal without creating anything (idempotent).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urljoin

import httpx
from django.conf import settings

from apps.providers.postal_domains import fetch_domain_dns_metadata

logger = logging.getLogger(__name__)


class ProvisionOutcome(str, Enum):
    CREATED = "created"
    ALREADY_EXISTS = "already_exists"
    FAILED = "failed"


_DNS_PATCH_KEYS = (
    "spf_txt_expected",
    "dkim_selector",
    "dkim_txt_value",
    "return_path_cname_name",
    "return_path_cname_target",
    "dmarc_txt_expected",
    "postal_verification_txt_expected",
)


@dataclass
class ProvisionResult:
    success: bool
    outcome: ProvisionOutcome
    error_code: str | None = None
    error_detail: str | None = None
    provider_domain_id: str | None = None
    """Optional DNS fields to merge onto TenantDomain (same keys as fetch_domain_dns_metadata)."""
    dns_patch: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] | None = None
    log_lines: list[str] = field(default_factory=list)
    """True if the provisioning bridge returned HTTP 200 with ok and merged dns (or no dns keys)."""
    webhook_merged: bool = False


def _norm_domain(domain_fqdn: str) -> str:
    return (domain_fqdn or "").strip().lower().rstrip(".")


def _base_http() -> tuple[str, str, float, bool]:
    base = (getattr(settings, "POSTAL_BASE_URL", "") or "").rstrip("/")
    key = getattr(settings, "POSTAL_SERVER_API_KEY", "") or ""
    timeout = float(getattr(settings, "POSTAL_TIMEOUT", 30))
    verify = getattr(settings, "POSTAL_USE_TLS_VERIFY", True)
    return base, key, timeout, verify


def _log(r: ProvisionResult, msg: str, *args: Any) -> None:
    line = msg % args if args else msg
    r.log_lines.append(line)
    logger.info("postal_provision: %s", line)


def _merge_dns_from_webhook_dict(dns: dict[str, Any], dns_patch: dict[str, Any]) -> None:
    for k in _DNS_PATCH_KEYS:
        if dns.get(k):
            dns_patch[str(k)] = dns[k]


def _merge_webhook_dns_after_http_fetch(domain: str, r: ProvisionResult) -> None:
    """
    When Postal HTTP API already returned SPF/DKIM, still call the bridge once to merge
    dns (e.g. postal_verification_txt_expected). Does not change r.success if the webhook fails.
    """
    url = (getattr(settings, "POSTAL_PROVISIONING_URL", None) or "").strip()
    if not url:
        return
    secret = (getattr(settings, "POSTAL_PROVISIONING_SECRET", None) or "").strip()
    _, _key, timeout, verify = _base_http()
    t = min(timeout, 30.0)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
        headers["X-Provisioning-Secret"] = secret
    _log(r, "webhook merge after HTTP fetch url=%s domain=%s", url, domain)
    try:
        resp = httpx.post(
            url,
            json={"domain": domain},
            headers=headers,
            timeout=t,
            verify=verify,
        )
    except Exception as exc:
        logger.warning("postal webhook merge after HTTP fetch transport error: %s", exc)
        return

    try:
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        data = {}

    if resp.status_code >= 400 or not isinstance(data, dict) or not data.get("ok", True):
        logger.warning(
            "postal webhook merge after HTTP fetch skipped http=%s ok=%s",
            resp.status_code,
            isinstance(data, dict) and data.get("ok"),
        )
        return

    dns = data.get("dns") or data.get("dns_metadata")
    if isinstance(dns, dict):
        _merge_dns_from_webhook_dict(dns, r.dns_patch)

    _pid = data.get("provider_domain_id") or data.get("domain_id")
    if _pid is not None:
        r.provider_domain_id = str(_pid)

    r.webhook_merged = True
    _log(r, "webhook merge after HTTP fetch ok dns_keys=%s", [k for k in _DNS_PATCH_KEYS if r.dns_patch.get(k)])


def _try_provisioning_webhook(domain: str, r: ProvisionResult) -> bool:
    url = (getattr(settings, "POSTAL_PROVISIONING_URL", None) or "").strip()
    if not url:
        return False
    secret = (getattr(settings, "POSTAL_PROVISIONING_SECRET", None) or "").strip()
    base, _key, timeout, verify = _base_http()
    t = min(timeout, 30.0)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
        headers["X-Provisioning-Secret"] = secret
    _log(r, "webhook POST mode url=%s domain=%s", url, domain)
    try:
        resp = httpx.post(
            url,
            json={"domain": domain},
            headers=headers,
            timeout=t,
            verify=verify,
        )
    except Exception as exc:
        r.success = False
        r.outcome = ProvisionOutcome.FAILED
        r.error_code = "provisioning_webhook_transport"
        r.error_detail = str(exc)[:2000]
        _log(r, "webhook transport error: %s", exc)
        return True

    _log(r, "webhook http_status=%s", resp.status_code)
    try:
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        data = {}

    if isinstance(data, dict):
        r.raw_response = data

    if resp.status_code >= 400:
        r.success = False
        r.outcome = ProvisionOutcome.FAILED
        r.error_code = "provisioning_webhook_http"
        r.error_detail = (data.get("error") if isinstance(data, dict) else None) or resp.text[:2000]
        return True

    if not isinstance(data, dict):
        r.success = False
        r.outcome = ProvisionOutcome.FAILED
        r.error_code = "provisioning_webhook_bad_json"
        r.error_detail = "Provisioning endpoint did not return a JSON object."
        return True

    if not data.get("ok", True):
        r.success = False
        r.outcome = ProvisionOutcome.FAILED
        r.error_code = str(data.get("error_code") or "provisioning_webhook_rejected")
        r.error_detail = str(data.get("error_detail") or data.get("message") or "Provisioning refused.")[:2000]
        return True

    oc = (data.get("outcome") or data.get("status") or "").strip().lower()
    if oc in ("created", "create"):
        r.outcome = ProvisionOutcome.CREATED
    elif oc in ("already_exists", "exists", "present"):
        r.outcome = ProvisionOutcome.ALREADY_EXISTS
    else:
        r.outcome = ProvisionOutcome.CREATED

    r.success = True
    _pid = data.get("provider_domain_id") or data.get("domain_id")
    r.provider_domain_id = str(_pid) if _pid is not None else None
    dns = data.get("dns") or data.get("dns_metadata")
    if isinstance(dns, dict):
        _merge_dns_from_webhook_dict(dns, r.dns_patch)

    r.webhook_merged = True
    _log(r, "webhook success outcome=%s dns_keys=%s", r.outcome.value, list(r.dns_patch.keys()))
    return True


def _try_experimental_server_key_create(domain: str, r: ProvisionResult) -> None:
    base, key, timeout, verify = _base_http()
    if not base or not key:
        _log(r, "skip experiments: missing POSTAL_BASE_URL or POSTAL_SERVER_API_KEY")
        return
    t = min(timeout, 12.0)
    headers = {"X-Server-API-Key": key, "Content-Type": "application/json", "Accept": "application/json"}
    candidates: list[tuple[str, dict[str, Any]]] = [
        ("api/v1/domains", {"name": domain}),
        ("api/v1/domains", {"domain": domain}),
        ("api/v1/domains/create", {"name": domain}),
        ("api/v1/servers/domains", {"name": domain}),
    ]
    for path, body in candidates:
        url = urljoin(base + "/", path)
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=t, verify=verify)
        except Exception as exc:
            _log(r, "experiment POST %s transport: %s", path, exc)
            continue
        _log(r, "experiment POST %s http=%s", path, resp.status_code)
        if resp.status_code == 404:
            continue
        try:
            data = resp.json()
        except Exception:
            data = {}
        if isinstance(data, dict):
            st = data.get("status")
            if st == "success" or data.get("data"):
                r.success = True
                r.outcome = ProvisionOutcome.CREATED
                r.raw_response = data
                inner = data.get("data") if isinstance(data.get("data"), dict) else data
                if isinstance(inner, dict) and inner.get("id"):
                    r.provider_domain_id = str(inner.get("id"))
                _log(r, "experiment accepted path=%s", path)
                return
            if st == "error":
                code = (data.get("data") or {}).get("code") if isinstance(data.get("data"), dict) else None
                _log(r, "experiment error code=%s path=%s", code, path)


def ensure_postal_domain_exists(domain_fqdn: str) -> ProvisionResult:
    """
    Idempotent: if Postal already exposes DNS metadata for this domain, we do not
    need to create it. Otherwise call webhook (if configured), then experimental APIs.
    """
    d = _norm_domain(domain_fqdn)
    r = ProvisionResult(success=False, outcome=ProvisionOutcome.FAILED, error_code=None, error_detail=None)

    if not d:
        r.error_code = "invalid_domain"
        r.error_detail = "Domain is empty."
        return r

    # 1) Already present in Postal (metadata visible via HTTP)
    try:
        meta = fetch_domain_dns_metadata(d, timeout=min(8.0, float(getattr(settings, "POSTAL_TIMEOUT", 30))))
    except Exception as exc:
        meta = None
        _log(r, "fetch_domain_dns_metadata error (ignored): %s", exc)

    if meta and (meta.get("dkim_txt_value") or meta.get("spf_txt_expected")):
        r.success = True
        r.outcome = ProvisionOutcome.ALREADY_EXISTS
        r.dns_patch.update({k: v for k, v in meta.items() if v})
        _log(r, "domain metadata already available from Postal fetch; treating as already_exists")
        _merge_webhook_dns_after_http_fetch(d, r)
        return r

    # 2) Operator bridge (required for stock Postal without domain HTTP API)
    _try_provisioning_webhook(d, r)
    if r.success:
        return r

    # 3) Experimental direct API (forks / future Postal)
    _try_experimental_server_key_create(d, r)
    if r.success:
        return r

    # 4) Failure — explain stock Postal limitation
    r.success = False
    r.outcome = ProvisionOutcome.FAILED
    r.error_code = r.error_code or "postal_domain_api_unavailable"
    r.error_detail = (
        r.error_detail
        or "The mail server’s public HTTP API does not expose domain creation (typical for Postal). "
        "Configure POSTAL_PROVISIONING_URL to a provisioning endpoint, or add the domain in Postal manually, "
        "then return here — we will pick up DNS records automatically when they are available."
    )
    _log(r, "provisioning failed: %s", r.error_detail[:200])
    return r


def delete_postal_domain(domain_fqdn: str) -> tuple[bool, str | None, bool]:
    """
    Best-effort: remove the sending domain from Postal via the provisioning bridge
    (POST /delete on POSTAL_PROVISIONING_URL base).

    Returns (ok, optional_warning_message, bridge_configured).

    If no bridge URL is set: (True, None, False).

    If the bridge is configured and Postal confirms deletion or domain was absent:
    (True, None, True).

    If the bridge is configured but the delete call fails: (False, warning_message, True).
    """
    base = (getattr(settings, "POSTAL_PROVISIONING_URL", None) or "").strip()
    if not base:
        return True, None, False

    d = _norm_domain(domain_fqdn)
    if not d:
        return True, None, False

    secret = (getattr(settings, "POSTAL_PROVISIONING_SECRET", None) or "").strip()
    _, _key, timeout, verify = _base_http()
    t = min(timeout, 30.0)
    url = urljoin(base.rstrip("/") + "/", "delete")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
        headers["X-Provisioning-Secret"] = secret

    try:
        resp = httpx.post(
            url,
            json={"domain": d},
            headers=headers,
            timeout=t,
            verify=verify,
        )
    except Exception as exc:
        logger.warning("postal delete transport error for %s: %s", d, exc)
        return (
            False,
            "Removed from SkyMailr. The mail server could not be updated automatically — remove the domain in Postal if it is still listed.",
            True,
        )

    try:
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        data = {}

    if resp.status_code == 404:
        logger.info("postal delete endpoint not found (bridge too old?): %s", url)
        return (
            False,
            "Removed from SkyMailr. Update the provisioning bridge to remove domains from the mail server automatically, or delete the domain in Postal manually.",
            True,
        )

    if resp.status_code >= 400:
        detail = (data.get("error_detail") if isinstance(data, dict) else None) or resp.text[:500]
        logger.warning("postal delete http=%s detail=%s", resp.status_code, detail)
        return (
            False,
            "Removed from SkyMailr. The mail server did not confirm removal — delete the domain in Postal if it is still listed.",
            True,
        )

    if not isinstance(data, dict):
        return (
            False,
            "Removed from SkyMailr. The mail server did not confirm removal — delete the domain in Postal if it is still listed.",
            True,
        )

    if not data.get("ok", True):
        logger.warning("postal delete rejected: %s", data)
        return (
            False,
            "Removed from SkyMailr. The mail server did not confirm removal — delete the domain in Postal if it is still listed.",
            True,
        )

    oc = (data.get("outcome") or "").strip().lower()
    logger.info("postal delete success domain=%s outcome=%s", d, oc)
    return True, None, True


def apply_dns_patch_to_tenant_domain(td: Any, patch: dict[str, Any]) -> bool:
    """Apply non-empty keys from patch onto TenantDomain. Returns True if any field changed."""
    from django.utils import timezone

    from apps.tenants.models import DnsMetadataSource

    changed = False
    for k in (
        "spf_txt_expected",
        "dkim_selector",
        "dkim_txt_value",
        "return_path_cname_name",
        "return_path_cname_target",
        "dmarc_txt_expected",
        "postal_verification_txt_expected",
    ):
        if k in patch and patch[k]:
            setattr(td, k, patch[k])
            changed = True
    if changed:
        td.dns_source = DnsMetadataSource.POSTAL_API
        td.dns_last_synced_at = timezone.now()
    return changed
