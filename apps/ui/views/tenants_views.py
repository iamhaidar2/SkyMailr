from django.contrib import messages as django_messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.defaults import get_or_create_internal_account
from apps.tenants.crypto import generate_api_key, hash_api_key
from apps.tenants.models import SenderProfile, Tenant, TenantAPIKey
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.ui.forms import ApiKeyCreateForm, SenderProfileForm, TenantForm
from apps.ui.tenant_validators import default_sender_domain_mismatch


SESSION_NEW_API_KEY = "_ui_new_api_key_once"


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
