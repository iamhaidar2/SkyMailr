from django.contrib.admin.views.decorators import staff_member_required
from datetime import timedelta

from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone

from apps.messages.models import OutboundMessage, OutboundStatus


@staff_member_required
def internal_dashboard(request):
    last_24h = timezone.now() - timedelta(hours=24)
    recent = OutboundMessage.objects.filter(created_at__gte=last_24h)
    stats = {
        "total_24h": recent.count(),
        "queued": recent.filter(status=OutboundStatus.QUEUED).count(),
        "sent": recent.filter(status=OutboundStatus.SENT).count(),
        "failed": recent.filter(status=OutboundStatus.FAILED).count(),
        "delivered": recent.filter(status=OutboundStatus.DELIVERED).count(),
    }
    by_tenant = (
        OutboundMessage.objects.filter(created_at__gte=last_24h)
        .values("tenant__slug")
        .annotate(c=Count("id"))
        .order_by("-c")[:10]
    )
    latest = OutboundMessage.objects.select_related("tenant").order_by("-created_at")[:25]
    return render(
        request,
        "internal/dashboard.html",
        {
            "stats": stats,
            "by_tenant": by_tenant,
            "latest": latest,
        },
    )
