"""Sync TenantDomain DNS expectations from Postal (best-effort) + persistence."""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.providers.postal_domains import fetch_domain_dns_metadata
from apps.tenants.models import DnsMetadataSource, TenantDomain

logger = logging.getLogger(__name__)


def sync_domain_dns_metadata(
    td: TenantDomain,
    *,
    timeout: float = 5.0,
) -> bool:
    """
    Attempt to refresh DNS metadata from Postal. Idempotent; updates td when data is returned.
    Does not save — caller saves if needed.

    Returns True if any field on td was updated from provider metadata.
    """
    try:
        meta = fetch_domain_dns_metadata(td.domain, timeout=timeout)
    except Exception as exc:
        logger.debug("sync_domain_dns_metadata fetch failed for %s: %s", td.domain, exc)
        return False

    if not meta:
        return False

    changed = False
    if meta.get("spf_txt_expected"):
        td.spf_txt_expected = meta["spf_txt_expected"]
        changed = True
    if meta.get("dkim_selector"):
        td.dkim_selector = meta["dkim_selector"]
        changed = True
    if meta.get("dkim_txt_value"):
        td.dkim_txt_value = meta["dkim_txt_value"]
        changed = True
    if meta.get("return_path_cname_name"):
        td.return_path_cname_name = meta["return_path_cname_name"]
        changed = True
    if meta.get("return_path_cname_target"):
        td.return_path_cname_target = meta["return_path_cname_target"]
        changed = True
    mx_t = meta.get("mx_targets")
    if isinstance(mx_t, list) and len(mx_t) > 0:
        td.mx_targets = [str(x).strip() for x in mx_t if str(x).strip()]
        changed = True
    if meta.get("dmarc_txt_expected"):
        td.dmarc_txt_expected = meta["dmarc_txt_expected"]
        changed = True

    if changed:
        td.dns_source = DnsMetadataSource.POSTAL_API
        td.dns_last_synced_at = timezone.now()
    return changed
