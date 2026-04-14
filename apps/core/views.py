from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
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


def service_root(request):
    """Avoid 404 noise when browsers or uptime checks hit `/` on Railway."""
    return JsonResponse(
        {
            "service": "SkyMailr",
            "health": "/api/v1/health/",
            "admin": "/admin/",
        }
    )


def noop_favicon(request):
    return HttpResponse(status=204)


def empty_sitemap(request):
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
    )
    return HttpResponse(body, content_type="application/xml")
