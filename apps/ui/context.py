from __future__ import annotations

from django.urls import reverse

from apps.ui.services.operator import get_active_tenant, list_tenants_for_operator


def operator_shell_context(request) -> dict:
    tenants = list_tenants_for_operator()
    active = get_active_tenant(request)
    return {
        "operator_tenants": tenants,
        "active_tenant": active,
        "nav_items": [
            {"label": "Dashboard", "url": reverse("ui:dashboard"), "name": "dashboard"},
            {"label": "Messages", "url": reverse("ui:messages_list"), "name": "messages"},
            {"label": "Send email", "url": reverse("ui:send_email"), "name": "send"},
            {"label": "Templates", "url": reverse("ui:templates_list"), "name": "templates"},
            {"label": "Template studio", "url": reverse("ui:template_studio"), "name": "studio"},
            {"label": "Workflows", "url": reverse("ui:workflows_list"), "name": "workflows"},
            {"label": "Tenants", "url": reverse("ui:tenants_list"), "name": "tenants"},
            {"label": "Provider health", "url": reverse("ui:provider_health"), "name": "providers"},
            {"label": "Webhooks", "url": reverse("ui:webhooks_list"), "name": "webhooks"},
            {"label": "Suppressions", "url": reverse("ui:suppressions_list"), "name": "suppressions"},
            {"label": "Unsubscribes", "url": reverse("ui:unsubscribes_list"), "name": "unsubscribes"},
            {"label": "Setup", "url": reverse("ui:setup"), "name": "setup"},
        ],
    }
