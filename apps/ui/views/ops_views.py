from django.conf import settings
from django.shortcuts import render

from apps.providers.registry import get_email_provider
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required


@operator_required
def provider_health(request):
    p = get_email_provider()
    ok, detail = p.health_check()
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Provider health",
            "nav_active": "providers",
            "provider_name": p.name,
            "provider_ok": ok,
            "provider_detail": detail,
            "email_provider_setting": getattr(settings, "EMAIL_PROVIDER", "dummy"),
            "postal_base": getattr(settings, "POSTAL_BASE_URL", "") or "",
        }
    )
    return render(request, "ui/pages/provider_health.html", ctx)


@operator_required
def webhooks_list(request):
    events = ProviderWebhookEvent.objects.order_by("-created_at")[:200]
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Webhooks",
            "nav_active": "webhooks",
            "events": events,
        }
    )
    return render(request, "ui/pages/webhooks_list.html", ctx)
