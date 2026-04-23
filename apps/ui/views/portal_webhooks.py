"""Customer portal: delivery events (from provider webhooks) and outbound webhook docs."""

from __future__ import annotations

import json
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.shortcuts import render

from apps.messages.models import MessageEvent, OutboundMessage
from apps.tenants.models import Tenant
from apps.ui.decorators import customer_login_required, portal_account_required
from apps.ui.forms_customer import PortalWebhookEventFilterForm
from apps.ui.services.portal_account import get_active_portal_account
from apps.ui.views.customer_portal import _portal_ctx


def _apply_event_filters(qs, form: PortalWebhookEventFilterForm):
    if not form.is_valid():
        return qs
    d = form.cleaned_data
    if ten := d.get("tenant"):
        qs = qs.filter(message__tenant=ten)
    if et := d.get("event_type"):
        qs = qs.filter(event_type=et)
    if em := (d.get("to_email") or "").strip():
        qs = qs.filter(message__to_email__icontains=em)
    if df := d.get("date_from"):
        qs = qs.filter(created_at__date__gte=df)
    if dt := d.get("date_to"):
        qs = qs.filter(created_at__date__lte=dt)
    return qs


def _payload_preview(payload: dict | None, max_len: int = 200) -> str:
    if not payload:
        return "—"
    try:
        s = json.dumps(payload, indent=2, default=str)
    except TypeError:
        s = str(payload)
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


@customer_login_required
@portal_account_required
def portal_webhooks_overview(request):
    account = get_active_portal_account(request)
    assert account is not None
    api_base = request.build_absolute_uri("/api/v1/").rstrip("/")
    inbound_url = f"{api_base}/webhooks/provider/<provider_name>/"
    tenants = list(
        Tenant.objects.filter(account=account)
        .order_by("name")
        .only("id", "name", "slug", "webhook_secret")
    )
    qs = (
        MessageEvent.objects.filter(message__tenant__account=account)
        .select_related("message", "message__tenant")
        .order_by("-created_at")
    )
    form = PortalWebhookEventFilterForm(request.GET or None, account=account)
    qs = _apply_event_filters(qs, form)
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))
    event_rows = []
    for ev in page.object_list:
        msg: OutboundMessage = ev.message
        event_rows.append(
            {
                "ev": ev,
                "tenant": msg.tenant,
                "to_email": msg.to_email,
                "message_id": msg.id,
                "payload_preview": _payload_preview(ev.payload if isinstance(ev.payload, dict) else {}),
            }
        )
    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    ctx = _portal_ctx(request, "Webhooks & delivery events", "webhooks")
    ctx.update(
        {
            "filter_form": form,
            "page_obj": page,
            "filter_query": urlencode(qcopy),
            "event_rows": event_rows,
            "inbound_webhook_url_pattern": inbound_url,
            "portal_tenants_for_webhooks": tenants,
        }
    )
    return render(request, "ui/customer/webhooks_overview.html", ctx)
