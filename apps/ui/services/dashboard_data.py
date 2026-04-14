"""Dashboard aggregates for operator home."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Count
from django.utils import timezone

from apps.messages.models import OutboundMessage, OutboundStatus, ProviderWebhookEvent


def build_dashboard_context() -> dict[str, Any]:
    now = timezone.now()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)

    base = OutboundMessage.objects.all()
    recent = base.filter(created_at__gte=last_24h)

    stats_24h = {
        "total": recent.count(),
        "queued": recent.filter(status=OutboundStatus.QUEUED).count(),
        "sent": recent.filter(status=OutboundStatus.SENT).count(),
        "delivered": recent.filter(status=OutboundStatus.DELIVERED).count(),
        "failed": recent.filter(status=OutboundStatus.FAILED).count(),
        "suppressed": recent.filter(status=OutboundStatus.SUPPRESSED).count(),
        "deferred": recent.filter(status=OutboundStatus.DEFERRED).count(),
    }

    week = base.filter(created_at__gte=last_7d)
    stats_7d = {"total": week.count()}

    by_tenant = (
        recent.values("tenant__slug", "tenant__name")
        .annotate(c=Count("id"))
        .order_by("-c")[:12]
    )
    by_status = (
        recent.values("status").annotate(c=Count("id")).order_by("-c")
    )

    failures = (
        base.filter(status=OutboundStatus.FAILED, created_at__gte=last_7d)
        .select_related("tenant")
        .order_by("-created_at")[:15]
    )

    webhook_recent = ProviderWebhookEvent.objects.order_by("-created_at")[:20]

    recent_messages = (
        base.select_related("tenant", "template")
        .order_by("-created_at")[:25]
    )

    return {
        "stats_24h": stats_24h,
        "stats_7d": stats_7d,
        "by_tenant": by_tenant,
        "by_status": by_status,
        "failures": failures,
        "webhook_recent": webhook_recent,
        "recent_messages": recent_messages,
    }
