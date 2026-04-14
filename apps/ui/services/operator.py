"""Operator session: active tenant for staff UI actions."""

from __future__ import annotations

from django.contrib.sessions.backends.base import SessionBase

from apps.tenants.models import Tenant

SESSION_ACTIVE_TENANT_KEY = "ui_active_tenant_id"


def list_tenants_for_operator():
    return Tenant.objects.order_by("name")


def get_active_tenant(request) -> Tenant | None:
    tid = request.session.get(SESSION_ACTIVE_TENANT_KEY)
    if tid:
        t = Tenant.objects.filter(pk=tid).first()
        if t:
            return t
    return Tenant.objects.order_by("name").first()


def set_active_tenant(session: SessionBase, tenant: Tenant) -> None:
    session[SESSION_ACTIVE_TENANT_KEY] = str(tenant.pk)
    session.modified = True
