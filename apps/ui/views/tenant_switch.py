from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.tenants.models import Tenant
from apps.ui.decorators import operator_required
from apps.ui.services.operator import set_active_tenant


@operator_required
@require_POST
def switch_tenant(request):
    tenant = get_object_or_404(Tenant, pk=request.POST.get("tenant_id"))
    set_active_tenant(request.session, tenant)
    messages.success(request, f"Active tenant: {tenant.name}")
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "ui:dashboard")
