from django.contrib import messages as django_messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.defaults import get_or_create_internal_account
from apps.accounts.policy import PolicyError
from apps.email_templates.models import EmailTemplate
from apps.tenants.crypto import generate_api_key, hash_api_key
from apps.tenants.models import SenderProfile, SendingPauseScope, SendingPauseSource, Tenant, TenantAPIKey
from apps.tenants.services.sending_risk import apply_automated_risk_pause, compute_tenant_sending_risk_metrics
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.messages.models import MessageType
from apps.messages.services.send_pipeline import create_raw_message, create_templated_message
from apps.ui.forms import (
    ApiKeyCreateForm,
    SenderProfileForm,
    TenantForm,
    TenantSendingRiskNotesForm,
    TenantSendingRiskPauseForm,
    TenantTestSendForm,
)
from apps.ui.services.deliverability_thresholds import (
    BOUNCE_RATE_DANGER,
    BOUNCE_RATE_WARNING,
    COMPLAINT_RATE_DANGER,
    COMPLAINT_RATE_WARNING,
)
from apps.ui.services.tenant_deliverability import build_tenant_deliverability_context
from apps.ui.tenant_validators import default_sender_domain_mismatch


SESSION_NEW_API_KEY = "_ui_new_api_key_once"


def _deliverability_threshold_legend():
    return {
        "bounce_warn": f"{BOUNCE_RATE_WARNING * 100:.2f}",
        "bounce_danger": f"{BOUNCE_RATE_DANGER * 100:.2f}",
        "complaint_warn": f"{COMPLAINT_RATE_WARNING * 100:.3f}",
        "complaint_danger": f"{COMPLAINT_RATE_DANGER * 100:.3f}",
    }


@operator_required
def tenants_list(request):
    tenants = Tenant.objects.order_by("name")
    ctx = operator_shell_context(request)
    ctx.update({"page_title": "Tenants", "nav_active": "tenants", "tenants": tenants})
    return render(request, "ui/pages/tenants_list.html", ctx)


@operator_required
def tenant_create(request):
    if request.method == "POST":
        form = TenantForm(request.POST)
        if form.is_valid():
            tenant = form.save(commit=False)
            tenant.account = get_or_create_internal_account()
            tenant.save()
            django_messages.success(request, f"Tenant “{tenant.name}” created.")
            return redirect("ui:tenant_detail", tenant_id=tenant.id)
    else:
        form = TenantForm()
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "New tenant",
            "nav_active": "tenants",
            "form": form,
            "submit_label": "Create tenant",
        }
    )
    return render(request, "ui/pages/tenant_form.html", ctx)


@operator_required
def tenant_edit(request, tenant_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    if request.method == "POST":
        form = TenantForm(request.POST, instance=tenant)
        if form.is_valid():
            form.save()
            django_messages.success(request, "Tenant updated.")
            return redirect("ui:tenant_detail", tenant_id=tenant.id)
    else:
        form = TenantForm(instance=tenant)
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": f"Edit {tenant.name}",
            "nav_active": "tenants",
            "tenant": tenant,
            "form": form,
            "submit_label": "Save changes",
        }
    )
    return render(request, "ui/pages/tenant_form.html", ctx)


@operator_required
def tenant_delete(request, tenant_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    if request.method == "POST":
        from apps.ui.services.operator import clear_active_tenant_if_deleted

        name = tenant.name
        clear_active_tenant_if_deleted(request.session, tenant)
        tenant.delete()
        django_messages.success(request, f"Tenant “{name}” deleted.")
        return redirect("ui:tenants_list")
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": f"Delete {tenant.name}",
            "nav_active": "tenants",
            "tenant": tenant,
        }
    )
    return render(request, "ui/pages/tenant_confirm_delete.html", ctx)


@operator_required
def tenant_detail(request, tenant_id):
    tenant = get_object_or_404(
        Tenant.objects.prefetch_related("api_keys", "sender_profiles", "domains"),
        pk=tenant_id,
    )
    keys = tenant.api_keys.order_by("-created_at")[:50]
    sender_profiles = list(tenant.sender_profiles.all())
    new_key = request.session.pop(SESSION_NEW_API_KEY, None)
    sending_domain_missing = not (tenant.sending_domain or "").strip()
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": tenant.name,
            "nav_active": "tenants",
            "tenant": tenant,
            "api_keys": keys,
            "new_api_key": new_key,
            "api_key_form": ApiKeyCreateForm(),
            "sender_profiles": sender_profiles,
            "sending_domain_missing": sending_domain_missing,
            "default_sender_domain_mismatch": default_sender_domain_mismatch(tenant),
            "default_sender_blank": not (tenant.default_sender_email or "").strip(),
        }
    )
    return render(request, "ui/pages/tenant_detail.html", ctx)


@operator_required
def sender_profile_create(request, tenant_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    if request.method == "POST":
        form = SenderProfileForm(request.POST, tenant=tenant)
        if form.is_valid():
            form.save()
            django_messages.success(request, "Sender profile created.")
            return redirect("ui:tenant_detail", tenant_id=tenant.id)
    else:
        form = SenderProfileForm(tenant=tenant)
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": f"New sender profile — {tenant.name}",
            "nav_active": "tenants",
            "tenant": tenant,
            "form": form,
            "submit_label": "Create profile",
            "sending_domain_missing": not (tenant.sending_domain or "").strip(),
        }
    )
    return render(request, "ui/pages/sender_profile_form.html", ctx)


@operator_required
def sender_profile_edit(request, tenant_id, profile_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    profile = get_object_or_404(SenderProfile, pk=profile_id, tenant=tenant)
    if request.method == "POST":
        form = SenderProfileForm(request.POST, tenant=tenant, instance=profile)
        if form.is_valid():
            form.save()
            django_messages.success(request, "Sender profile updated.")
            return redirect("ui:tenant_detail", tenant_id=tenant.id)
    else:
        form = SenderProfileForm(tenant=tenant, instance=profile)
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": f"Edit {profile.name}",
            "nav_active": "tenants",
            "tenant": tenant,
            "profile": profile,
            "form": form,
            "submit_label": "Save changes",
            "sending_domain_missing": not (tenant.sending_domain or "").strip(),
        }
    )
    return render(request, "ui/pages/sender_profile_form.html", ctx)


@operator_required
def sender_profile_delete(request, tenant_id, profile_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    profile = get_object_or_404(SenderProfile, pk=profile_id, tenant=tenant)
    if request.method == "POST":
        name = profile.name
        profile.delete()
        django_messages.success(request, f"Sender profile “{name}” deleted.")
        return redirect("ui:tenant_detail", tenant_id=tenant.id)
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": f"Delete {profile.name}",
            "nav_active": "tenants",
            "tenant": tenant,
            "profile": profile,
        }
    )
    return render(request, "ui/pages/sender_profile_confirm_delete.html", ctx)


@operator_required
@require_POST
def tenant_create_api_key(request, tenant_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    form = ApiKeyCreateForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Invalid name.")
        return redirect("ui:tenant_detail", tenant_id=tenant.id)
    raw = generate_api_key()
    TenantAPIKey.objects.create(
        tenant=tenant,
        name=form.cleaned_data["name"],
        key_hash=hash_api_key(raw),
    )
    request.session[SESSION_NEW_API_KEY] = raw
    django_messages.warning(
        request,
        "API key created. Copy it now — it will not be shown again.",
    )
    return redirect("ui:tenant_detail", tenant_id=tenant.id)


@operator_required
def tenant_deliverability(request, tenant_id):
    tenant = get_object_or_404(
        Tenant.objects.prefetch_related("domains"),
        pk=tenant_id,
    )
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": f"Deliverability · {tenant.name}",
            "nav_active": "tenants",
            "tenant": tenant,
            "deliverability": build_tenant_deliverability_context(tenant),
            "test_send_form": TenantTestSendForm(tenant=tenant),
            "threshold_legend": _deliverability_threshold_legend(),
        }
    )
    return render(request, "ui/pages/tenant_deliverability.html", ctx)


@operator_required
@require_POST
def tenant_deliverability_test_send(request, tenant_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    form = TenantTestSendForm(request.POST, tenant=tenant)
    if not form.is_valid():
        django_messages.error(request, "Fix the form errors and try again.")
        ctx = operator_shell_context(request)
        ctx.update(
            {
                "page_title": f"Deliverability · {tenant.name}",
                "nav_active": "tenants",
                "tenant": tenant,
                "deliverability": build_tenant_deliverability_context(tenant),
                "test_send_form": form,
                "threshold_legend": _deliverability_threshold_legend(),
            }
        )
        return render(request, "ui/pages/tenant_deliverability.html", ctx, status=400)

    d = form.cleaned_data
    sp = d.get("sender_profile")
    if sp is not None and sp.tenant_id != tenant.id:
        django_messages.error(request, "Sender profile does not belong to this tenant.")
        return redirect("ui:tenant_deliverability", tenant_id=tenant.id)

    try:
        if d["mode"] == TenantTestSendForm.MODE_RAW:
            msg = create_raw_message(
                tenant=tenant,
                source_app="operator_test_send",
                message_type=MessageType.TRANSACTIONAL,
                to_email=d["to_email"],
                to_name="",
                subject=d["subject"],
                html_body=d["html_body"],
                text_body=d.get("text_body") or "",
                metadata={},
                idempotency_key=None,
                sender_profile=sp,
                bypass_quota=request.user.is_staff,
                bypass_sending_pause=request.user.is_staff,
                bypass_domain_verification=request.user.is_staff,
            )
        else:
            tpl = EmailTemplate.objects.filter(tenant=tenant, key=d["template_key"].strip()).first()
            if not tpl:
                django_messages.error(request, "Unknown template key for this tenant.")
                return redirect("ui:tenant_deliverability", tenant_id=tenant.id)
            msg = create_templated_message(
                tenant=tenant,
                template=tpl,
                source_app="operator_test_send",
                message_type=MessageType.TRANSACTIONAL,
                to_email=d["to_email"],
                to_name="",
                context={},
                metadata={},
                tags={},
                idempotency_key=None,
                sender_profile=sp,
                bypass_quota=request.user.is_staff,
                bypass_sending_pause=request.user.is_staff,
                bypass_domain_verification=request.user.is_staff,
            )
    except PolicyError as e:
        django_messages.error(request, e.detail)
        return redirect("ui:tenant_deliverability", tenant_id=tenant.id)

    django_messages.success(
        request,
        "Test message created via the normal pipeline. Track it on the message detail page.",
    )
    url = reverse("ui:message_detail", kwargs={"message_id": msg.id}) + "?test_send=1"
    return HttpResponseRedirect(url)


@operator_required
def tenant_sending_risk(request, tenant_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    live_metrics = compute_tenant_sending_risk_metrics(tenant)

    pause_form = TenantSendingRiskPauseForm(
        initial={
            "sending_pause_scope": tenant.sending_pause_scope or SendingPauseScope.MARKETING_LIFECYCLE,
            "sending_pause_reason": tenant.sending_pause_reason,
        }
    )
    notes_form = TenantSendingRiskNotesForm(initial={"operator_risk_notes": tenant.operator_risk_notes})

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "resume":
            Tenant.objects.filter(pk=tenant.pk).update(
                sending_paused=False,
                sending_pause_reason="",
                sending_pause_source=None,
                sending_pause_scope=SendingPauseScope.MARKETING_LIFECYCLE,
            )
            django_messages.success(request, "Sending resumed for this tenant.")
            return redirect("ui:tenant_sending_risk", tenant_id=tenant.id)
        if action == "pause":
            pause_form = TenantSendingRiskPauseForm(request.POST)
            if pause_form.is_valid():
                d = pause_form.cleaned_data
                Tenant.objects.filter(pk=tenant.pk).update(
                    sending_paused=True,
                    sending_pause_scope=d["sending_pause_scope"],
                    sending_pause_source=SendingPauseSource.MANUAL,
                    sending_pause_reason=(d.get("sending_pause_reason") or "").strip()[:4000],
                )
                django_messages.warning(request, "Sending pause is now active for this tenant.")
                return redirect("ui:tenant_sending_risk", tenant_id=tenant.id)
            django_messages.error(request, "Fix the pause form and try again.")
        elif action == "save_notes":
            notes_form = TenantSendingRiskNotesForm(request.POST)
            if notes_form.is_valid():
                Tenant.objects.filter(pk=tenant.pk).update(
                    operator_risk_notes=(notes_form.cleaned_data.get("operator_risk_notes") or "").strip()[:8000]
                )
                django_messages.success(request, "Notes saved.")
                return redirect("ui:tenant_sending_risk", tenant_id=tenant.id)
            django_messages.error(request, "Fix the notes form and try again.")
        elif action == "mark_reviewed":
            Tenant.objects.filter(pk=tenant.pk).update(last_risk_review_at=timezone.now())
            django_messages.success(request, "Marked as reviewed.")
            return redirect("ui:tenant_sending_risk", tenant_id=tenant.id)
        elif action == "recompute":
            apply_automated_risk_pause(tenant)
            django_messages.info(request, "Risk metrics recomputed (auto-pause rules may apply).")
            return redirect("ui:tenant_sending_risk", tenant_id=tenant.id)

    tenant.refresh_from_db()
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": f"Sending risk · {tenant.name}",
            "nav_active": "tenants",
            "tenant": tenant,
            "live_metrics": live_metrics,
            "pause_form": pause_form,
            "notes_form": notes_form,
        }
    )
    return render(request, "ui/pages/tenant_sending_risk.html", ctx)
