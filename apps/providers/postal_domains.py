"""
Best-effort Postal HTTP discovery for domain/DNS metadata.

Postal’s public server API is primarily send/message; domain management endpoints vary by version.
This module tries a small set of JSON routes and parses common response shapes. On failure it
returns None so callers can fall back to TenantDomain admin fields and operator settings.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


def _base_config() -> tuple[str, str, float, bool]:
    base = (getattr(settings, "POSTAL_BASE_URL", "") or "").rstrip("/")
    key = getattr(settings, "POSTAL_SERVER_API_KEY", "") or ""
    timeout = float(getattr(settings, "POSTAL_TIMEOUT", 30))
    verify = getattr(settings, "POSTAL_USE_TLS_VERIFY", True)
    return base, key, timeout, verify


def _extract_from_domain_obj(obj: dict[str, Any], domain_fqdn: str) -> dict[str, Any] | None:
    """Map loosely structured Postal domain JSON to our metadata keys."""
    d = domain_fqdn.lower().strip().rstrip(".")
    name = (obj.get("name") or obj.get("domain") or obj.get("hostname") or "").lower().strip().rstrip(".")
    if name and name != d:
        return None

    out: dict[str, Any] = {}
    # SPF
    for key in ("spf_record", "spf_txt", "spf", "spf_record_value"):
        v = obj.get(key)
        if isinstance(v, str) and v.strip().lower().startswith("v=spf1"):
            out["spf_txt_expected"] = v.strip()
            break
    # DKIM
    sel = obj.get("dkim_selector") or obj.get("dkim_record_name")
    if isinstance(sel, str) and sel.strip():
        out["dkim_selector"] = sel.strip().split(".")[0]
    for key in ("dkim_record", "dkim_txt", "dkim_public_key", "dkim_value"):
        v = obj.get(key)
        if isinstance(v, str) and "v=dkim1" in v.lower().replace(" ", ""):
            out["dkim_txt_value"] = v.strip()
            break
    # Return path / bounce
    for key in ("return_path_domain", "bounce_domain", "rp_cname_target"):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            out["return_path_cname_target"] = v.strip().rstrip(".")
            break
    if "return_path_cname_target" in out and "return_path_cname_name" not in out:
        out["return_path_cname_name"] = f"rp.{d}"

    if out:
        return out
    return None


def _walk_for_domain_payload(data: Any, domain_fqdn: str) -> dict[str, Any] | None:
    if isinstance(data, dict):
        hit = _extract_from_domain_obj(data, domain_fqdn)
        if hit:
            return hit
        for v in data.values():
            found = _walk_for_domain_payload(v, domain_fqdn)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _walk_for_domain_payload(item, domain_fqdn)
            if found:
                return found
    return None


def fetch_domain_dns_metadata(domain_fqdn: str, *, timeout: float | None = None) -> dict[str, Any] | None:
    """
    Returns a dict with optional keys:
    spf_txt_expected, dkim_selector, dkim_txt_value,
    return_path_cname_name, return_path_cname_target, dmarc_txt_expected
    or None if nothing could be fetched.
    """
    base, key, default_timeout, verify = _base_config()
    if not base or not key:
        return None
    t = float(timeout) if timeout is not None else min(default_timeout, 8.0)
    headers = {"X-Server-API-Key": key, "Accept": "application/json"}
    d = domain_fqdn.lower().strip().rstrip(".")

    candidate_gets = [
        "api/v1/domains",
        "api/v1/org/domains",
    ]
    for path in candidate_gets:
        url = urljoin(base + "/", path)
        try:
            r = httpx.get(url, headers=headers, timeout=t, verify=verify)
        except Exception as exc:
            logger.debug("postal domains GET %s: %s", path, exc)
            continue
        if r.status_code != 200:
            continue
        try:
            data = r.json()
        except Exception:
            continue
        parsed = _walk_for_domain_payload(data, d)
        if parsed:
            return parsed

    # POST-style query variants (version-dependent)
    posts: list[tuple[str, dict[str, Any]]] = [
        ("api/v1/domains/query", {"domain": d}),
        ("api/v1/domains/show", {"domain": d}),
        ("api/v1/domains/get", {"name": d}),
    ]
    for path, body in posts:
        url = urljoin(base + "/", path)
        try:
            r = httpx.post(url, headers=headers, json=body, timeout=t, verify=verify)
        except Exception as exc:
            logger.debug("postal domains POST %s: %s", path, exc)
            continue
        if r.status_code != 200:
            continue
        try:
            data = r.json()
        except Exception:
            continue
        if isinstance(data, dict) and "data" in data:
            inner = data.get("data")
            parsed = _walk_for_domain_payload(inner, d)
            if parsed:
                return parsed
        parsed = _walk_for_domain_payload(data, d)
        if parsed:
            return parsed

    return None
