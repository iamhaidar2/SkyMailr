"""
Tenant-scoped deliverability aggregates for the operator UI.

24h window uses ``OutboundMessage.updated_at``: counts reflect outcomes that
entered their current terminal status within the window (not message creation
time), so old backlog items are not mis-attributed to "today".
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.messages.models import OutboundMessage, OutboundStatus, ProviderWebhookEvent
from apps.messages.services.throttling import resolve_sending_hostname
from apps.tenants.models import Tenant, TenantDomain
from apps.ui.services.deliverability_thresholds import (
    bounce_rate_level,
    complaint_rate_level,
    return_path_config_level,
)

# Handed off to provider (or terminal outcome after handoff). Used as denominator for rates.
_SENT_PATH_STATUSES = (
    OutboundStatus.SENT,
    OutboundStatus.DELIVERED,
    OutboundStatus.BOUNCED,
    OutboundStatus.COMPLAINED,
    OutboundStatus.FAILED,
)


def _window_qs(tenant: Tenant, *, hours: int = 24) -> QuerySet[OutboundMessage]:
    t0 = timezone.now() - timedelta(hours=hours)
    return OutboundMessage.objects.filter(tenant=tenant, updated_at__gte=t0)


def _denominator(qs: QuerySet[OutboundMessage]) -> int:
    return qs.filter(status__in=_SENT_PATH_STATUSES).count()


def _tenant_provider_message_ids(tenant: Tenant, *, cap: int = 5000) -> list[str]:
    ids = (
        OutboundMessage.objects.filter(tenant=tenant)
        .exclude(provider_message_id="")
        .order_by("-updated_at")
        .values_list("provider_message_id", flat=True)[:cap]
    )
    return [str(x) for x in ids if x]


def _recent_webhooks_for_tenant(tenant: Tenant, *, limit: int = 20) -> list[ProviderWebhookEvent]:
    mids = _tenant_provider_message_ids(tenant)
    if not mids:
        return []
    return list(
        ProviderWebhookEvent.objects.filter(
            Q(normalized__provider_message_id__in=mids) | Q(normalized__message_id__in=mids)
        )
        .order_by("-created_at")[:limit]
    )


def _top_failure_reasons(qs: QuerySet[OutboundMessage], *, limit: int = 8) -> list[dict[str, Any]]:
    rows = (
        qs.filter(status=OutboundStatus.FAILED)
        .exclude(last_error="")
        .values("last_error")
        .annotate(c=Count("id"))
        .order_by("-c")[:limit]
    )
    return [{"reason": r["last_error"][:500], "count": r["c"]} for r in rows]


def build_domain_rows(tenant: Tenant, *, hours: int = 24) -> list[dict[str, Any]]:
    t0 = timezone.now() - timedelta(hours=hours)
    host_to_pks: dict[str, list[Any]] = defaultdict(list)
    for m in (
        OutboundMessage.objects.filter(tenant=tenant, updated_at__gte=t0)
        .select_related("sender_profile")
        .iterator(chunk_size=500)
    ):
        h = resolve_sending_hostname(m).lower()
        if h:
            host_to_pks[h].append(m.pk)

    rows: list[dict[str, Any]] = []
    for td in tenant.domains.all().order_by("domain"):
        pks = host_to_pks.get(td.domain.strip().lower(), [])
        qs = OutboundMessage.objects.filter(pk__in=pks) if pks else OutboundMessage.objects.none()
        d = _denominator(qs)
        rows.append(
            {
                "domain": td,
                "verification_status": td.get_verification_status_display(),
                "spf_status": td.spf_status or "—",
                "dkim_status": td.dkim_status or "—",
                "dmarc_status": td.dmarc_status or "—",
                "return_path_level": return_path_config_level(
                    cname_name=td.return_path_cname_name or "",
                    cname_target=td.return_path_cname_target or "",
                ),
                "last_checked_at": td.last_checked_at,
                "sent_path_count": d,
                "delivered": qs.filter(status=OutboundStatus.DELIVERED).count(),
                "bounced": qs.filter(status=OutboundStatus.BOUNCED).count(),
                "complained": qs.filter(status=OutboundStatus.COMPLAINED).count(),
                "failed": qs.filter(status=OutboundStatus.FAILED).count(),
                "recent_failures": list(
                    qs.filter(status__in=(OutboundStatus.FAILED, OutboundStatus.BOUNCED))
                    .order_by("-updated_at")[:5]
                ),
            }
        )
    return rows


def build_tenant_deliverability_context(tenant: Tenant, *, hours: int = 24) -> dict[str, Any]:
    qs = _window_qs(tenant, hours=hours)
    delivered = qs.filter(status=OutboundStatus.DELIVERED).count()
    bounced = qs.filter(status=OutboundStatus.BOUNCED).count()
    complained = qs.filter(status=OutboundStatus.COMPLAINED).count()
    failed = qs.filter(status=OutboundStatus.FAILED).count()
    suppressed = qs.filter(status=OutboundStatus.SUPPRESSED).count()
    sent_path = _denominator(qs)

    denom = max(sent_path, 1)
    delivery_rate = delivered / denom
    bounce_rate = bounced / denom
    complaint_rate = complained / denom

    return {
        "window_hours": hours,
        "metrics": {
            "sent_path": sent_path,
            "delivered": delivered,
            "failed": failed,
            "bounced": bounced,
            "complained": complained,
            "suppressed": suppressed,
            "delivery_rate": delivery_rate,
            "bounce_rate": bounce_rate,
            "complaint_rate": complaint_rate,
        },
        "bounce_level": bounce_rate_level(bounce_rate),
        "complaint_level": complaint_rate_level(complaint_rate),
        "top_failure_reasons": _top_failure_reasons(qs),
        "webhook_events": _recent_webhooks_for_tenant(tenant, limit=20),
        "recent_failures": list(
            qs.filter(status__in=(OutboundStatus.FAILED, OutboundStatus.BOUNCED))
            .select_related("sender_profile", "template")
            .order_by("-updated_at")[:20]
        ),
        "domain_rows": build_domain_rows(tenant, hours=hours),
    }
