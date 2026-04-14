from django.contrib import messages as django_messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.tenants.crypto import generate_api_key, hash_api_key
from apps.tenants.models import Tenant, TenantAPIKey
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.ui.forms import ApiKeyCreateForm


SESSION_NEW_API_KEY = "_ui_new_api_key_once"


@operator_required
def tenants_list(request):
    tenants = Tenant.objects.order_by("name")
    ctx = operator_shell_context(request)
    ctx.update({"page_title": "Tenants", "nav_active": "tenants", "tenants": tenants})
    return render(request, "ui/pages/tenants_list.html", ctx)


@operator_required
def tenant_detail(request, tenant_id):
    tenant = get_object_or_404(
        Tenant.objects.prefetch_related("api_keys", "sender_profiles", "domains"),
        pk=tenant_id,
    )
    keys = tenant.api_keys.order_by("-created_at")[:50]
    new_key = request.session.pop(SESSION_NEW_API_KEY, None)
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": tenant.name,
            "nav_active": "tenants",
            "tenant": tenant,
            "api_keys": keys,
            "new_api_key": new_key,
            "api_key_form": ApiKeyCreateForm(),
        }
    )
    return render(request, "ui/pages/tenant_detail.html", ctx)


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
