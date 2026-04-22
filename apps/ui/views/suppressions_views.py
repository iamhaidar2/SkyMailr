"""Operator UI: delivery suppressions and marketing unsubscribes."""

from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages as django_messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.messages.models import OutboundMessage
from apps.subscriptions.models import DeliverySuppression, UnsubscribeRecord
from apps.subscriptions.services.suppression_ops import (
    create_manual_suppression,
    merge_manual_suppression_metadata,
    remove_suppression_with_audit,
)
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.ui.forms import ManualSuppressionForm, SuppressionFilterForm


def _apply_suppression_filters(qs, form: SuppressionFilterForm):
    if not form.is_valid():
        return qs
    d = form.cleaned_data
    if em := (d.get("email") or "").strip():
        qs = qs.filter(email__icontains=em)
    if r := d.get("reason"):
        qs = qs.filter(reason=r)
    scope = d.get("scope") or ""
    if scope == "global":
        qs = qs.filter(tenant__isnull=True)
    elif scope == "tenant_only":
        qs = qs.filter(tenant__isnull=False)
    if ten := d.get("tenant"):
        qs = qs.filter(Q(tenant=ten) | Q(tenant__isnull=True))
    aff = d.get("affects") or ""
    if aff == "marketing":
        qs = qs.filter(applies_to_marketing=True)
    elif aff == "transactional":
        qs = qs.filter(applies_to_transactional=True)
    elif aff == "both":
        qs = qs.filter(applies_to_marketing=True, applies_to_transactional=True)
    if df := d.get("date_from"):
        qs = qs.filter(created_at__date__gte=df)
    if dt := d.get("date_to"):
        qs = qs.filter(created_at__date__lte=dt)
    return qs


def _message_links_for_suppressions(suppressions: list[DeliverySuppression]) -> dict:
    provider_mids: list[str] = []
    for s in suppressions:
        mid = (s.metadata or {}).get("provider_message_id")
        if mid:
            provider_mids.append(str(mid))
    by_provider: dict[str, OutboundMessage] = {}
    if provider_mids:
        for m in OutboundMessage.objects.filter(provider_message_id__in=provider_mids):
            by_provider[m.provider_message_id] = m
    out: dict = {}
    for s in suppressions:
        mid = (s.metadata or {}).get("provider_message_id")
        if mid and mid in by_provider:
            out[s.id] = by_provider[mid]
            continue
        oid = (s.metadata or {}).get("outbound_message_id")
        if oid:
            m = OutboundMessage.objects.filter(pk=oid).first()
            if m:
                out[s.id] = m
    return out


def _metadata_summary(md: dict, *, max_len: int = 140) -> str:
    if not md:
        return "—"
    parts: list[str] = []
    for k in ("note", "provider", "reason", "outbound_message_id", "source", "created_by_username"):
        v = md.get(k)
        if v is not None and str(v).strip():
            parts.append(f"{k}={v}")
    s = " · ".join(parts[:6])
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s or "—"


@operator_required
def suppressions_list(request):
    form = SuppressionFilterForm(request.GET or None)
    qs = DeliverySuppression.objects.select_related("tenant").all().order_by("-created_at")
    qs = _apply_suppression_filters(qs, form)
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))
    rows = list(page.object_list)
    msg_links = _message_links_for_suppressions(rows)
    suppression_rows = [
        {
            "s": s,
            "summary": _metadata_summary(s.metadata or {}),
            "message": msg_links.get(s.id),
        }
        for s in rows
    ]
    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Suppressions",
            "nav_active": "suppressions",
            "filter_form": form,
            "page_obj": page,
            "filter_query": urlencode(qcopy),
            "suppression_rows": suppression_rows,
        }
    )
    return render(request, "ui/pages/suppressions_list.html", ctx)


@operator_required
def suppression_manual(request):
    if request.method == "POST":
        form = ManualSuppressionForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            tenant = d.get("tenant")
            smid = d.get("source_message_id")
            om_id: str | None = None
            extra: dict = {}
            if smid:
                msg = OutboundMessage.objects.filter(pk=smid).first()
                if msg:
                    om_id = str(msg.id)
                    extra["outbound_tenant_slug"] = msg.tenant.slug
                else:
                    django_messages.warning(
                        request,
                        "Source message ID was not found; suppression was saved without that link.",
                    )
            meta = merge_manual_suppression_metadata(
                note=d.get("note") or "",
                actor_username=request.user.get_username(),
                source_message_id=om_id,
                extra=extra or None,
            )
            create_manual_suppression(
                email=d["email"],
                tenant=tenant,
                applies_to_marketing=bool(d.get("applies_to_marketing")),
                applies_to_transactional=bool(d.get("applies_to_transactional")),
                metadata=meta,
            )
            django_messages.success(request, f"Suppression saved for {(d['email'] or '').strip().lower()}.")
            return redirect("ui:suppressions_list")
    else:
        form = ManualSuppressionForm()
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Add suppression",
            "nav_active": "suppressions",
            "form": form,
        }
    )
    return render(request, "ui/pages/suppression_manual.html", ctx)


@operator_required
def suppression_delete(request, suppression_id):
    s = get_object_or_404(DeliverySuppression.objects.select_related("tenant"), pk=suppression_id)
    if request.method == "POST":
        email = s.email
        remove_suppression_with_audit(s, removed_by=request.user)
        django_messages.success(request, f"Removed suppression for {email}.")
        return redirect("ui:suppressions_list")
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Remove suppression",
            "nav_active": "suppressions",
            "suppression": s,
            "metadata_summary": _metadata_summary(s.metadata or {}),
        }
    )
    return render(request, "ui/pages/suppression_confirm_delete.html", ctx)


@operator_required
def unsubscribes_list(request):
    qs = UnsubscribeRecord.objects.select_related("tenant").order_by("-created_at")[:500]
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Unsubscribes",
            "nav_active": "unsubscribes",
            "rows": qs,
        }
    )
    return render(request, "ui/pages/unsubscribes_list.html", ctx)
