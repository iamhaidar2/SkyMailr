"""Customer portal: delivery suppressions for the active account's tenants."""

from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages as django_messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.messages.models import OutboundMessage
from apps.subscriptions.models import DeliverySuppression
from apps.subscriptions.services.suppression_ops import (
    create_manual_suppression,
    merge_manual_suppression_metadata,
    remove_suppression_with_audit,
)
from apps.tenants.models import Tenant
from apps.ui.decorators import customer_login_required, portal_account_required, portal_editor_required
from apps.ui.forms_customer import PortalManualSuppressionForm, PortalSuppressionFilterForm
from apps.ui.services.portal_account import get_active_portal_account
from apps.ui.services.portal_permissions import portal_user_can_edit_content
from apps.ui.views.customer_portal import _portal_ctx


def _apply_portal_suppression_filters(
    qs,
    form: PortalSuppressionFilterForm,
    *,
    account_tenant_ids: set,
):
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
    elif scope == "mine":
        qs = qs.filter(tenant_id__in=account_tenant_ids)
    if ten := d.get("tenant"):
        qs = qs.filter(Q(tenant=ten) | Q(tenant__isnull=True))
    aff = d.get("affects") or ""
    if aff == "marketing":
        qs = qs.filter(applies_to_marketing=True)
    elif aff == "transactional":
        qs = qs.filter(applies_to_transactional=True)
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


@customer_login_required
@portal_account_required
def portal_suppression_list(request):
    account = get_active_portal_account(request)
    assert account is not None
    tenant_ids = set(
        Tenant.objects.filter(account=account).values_list("id", flat=True)
    )
    qs = (
        DeliverySuppression.objects.filter(
            Q(tenant__account=account) | Q(tenant__isnull=True)
        )
        .select_related("tenant")
        .order_by("-created_at")
    )
    form = PortalSuppressionFilterForm(request.GET or None, account=account)
    qs = _apply_portal_suppression_filters(qs, form, account_tenant_ids=tenant_ids)
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))
    rows = list(page.object_list)
    msg_links = _message_links_for_suppressions(rows)
    suppression_rows = [
        {
            "s": s,
            "summary": _metadata_summary(s.metadata or {}),
            "message": msg_links.get(s.id),
            "is_global": s.tenant_id is None,
        }
        for s in rows
    ]
    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    ctx = _portal_ctx(request, "Suppressions", "suppressions")
    ctx.update(
        {
            "filter_form": form,
            "page_obj": page,
            "filter_query": urlencode(qcopy),
            "suppression_rows": suppression_rows,
            "portal_can_edit_suppressions": portal_user_can_edit_content(
                request.user, account
            ),
        }
    )
    return render(request, "ui/customer/suppressions_list.html", ctx)


@customer_login_required
@portal_editor_required
def portal_suppression_add(request):
    account = get_active_portal_account(request)
    assert account is not None
    tenants = list(Tenant.objects.filter(account=account).order_by("name"))
    if not tenants:
        django_messages.info(
            request,
            "Add a connected app before managing suppressions.",
        )
        return redirect("portal:tenant_list")
    single = tenants[0] if len(tenants) == 1 else None
    if request.method == "POST":
        form = PortalManualSuppressionForm(
            request.POST, account=account, single_tenant=single
        )
        if form.is_valid():
            d = form.cleaned_data
            tenant = d["tenant"]
            meta = merge_manual_suppression_metadata(
                note=d.get("note") or "",
                actor_username=request.user.get_username(),
                source_message_id=None,
                extra=None,
                source="customer_portal",
            )
            create_manual_suppression(
                email=d["email"],
                tenant=tenant,
                applies_to_marketing=bool(d.get("applies_to_marketing")),
                applies_to_transactional=bool(d.get("applies_to_transactional")),
                metadata=meta,
            )
            django_messages.success(
                request,
                f"Suppression saved for {(d['email'] or '').strip().lower()}.",
            )
            return redirect("portal:suppressions_list")
    else:
        form = PortalManualSuppressionForm(account=account, single_tenant=single)
    ctx = _portal_ctx(request, "Add suppression", "suppressions")
    ctx.update({"form": form, "tenants": tenants})
    return render(request, "ui/customer/suppression_manual.html", ctx)


@customer_login_required
@portal_editor_required
def portal_suppression_delete(request, suppression_id):
    account = get_active_portal_account(request)
    assert account is not None
    s = get_object_or_404(
        DeliverySuppression.objects.select_related("tenant"),
        pk=suppression_id,
    )
    if s.tenant_id is None:
        django_messages.error(
            request,
            "Global suppressions cannot be removed from the customer app. Contact support if you need help.",
        )
        return HttpResponseRedirect(reverse("portal:suppressions_list"))
    if s.tenant is None or s.tenant.account_id != account.id:
        django_messages.error(request, "Suppression not found.")
        return HttpResponseRedirect(reverse("portal:suppressions_list"))
    if request.method == "POST":
        email = s.email
        remove_suppression_with_audit(s, removed_by=request.user)
        django_messages.success(request, f"Removed suppression for {email}.")
        return redirect("portal:suppressions_list")
    ctx = _portal_ctx(request, "Remove suppression", "suppressions")
    ctx.update(
        {
            "suppression": s,
            "metadata_summary": _metadata_summary(s.metadata or {}),
        }
    )
    return render(request, "ui/customer/suppression_confirm_delete.html", ctx)
