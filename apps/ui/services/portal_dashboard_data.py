"""Dashboard aggregates for the customer portal home (account-scoped)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.accounts.models import AccountStatus
from apps.email_templates.models import EmailTemplate, TemplateStatus
from apps.messages.models import OutboundMessage, OutboundStatus
from apps.tenants.models import SenderProfile, Tenant, TenantAPIKey
from apps.ui.services.delivery_context import build_delivery_context


def build_portal_dashboard_context(account) -> dict[str, Any]:
    """Mirror operator dashboard signals where meaningful; scoped to the portal account."""
    now = timezone.now()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)

    base = OutboundMessage.objects.filter(tenant__account=account)
    recent = base.filter(created_at__gte=last_24h)

    stats_24h = {
        "total": recent.count(),
        "queued": recent.filter(status=OutboundStatus.QUEUED).count(),
        "delivered": recent.filter(status=OutboundStatus.DELIVERED).count(),
        "failed": recent.filter(status=OutboundStatus.FAILED).count(),
    }

    failures = (
        base.filter(status=OutboundStatus.FAILED, created_at__gte=last_7d)
        .select_related("tenant")
        .order_by("-created_at")[:15]
    )

    recent_messages = base.select_related("tenant").order_by("-created_at")[:25]

    delivery = build_delivery_context()

    tenants_exist = Tenant.objects.filter(account=account).exists()
    api_keys_ok = TenantAPIKey.objects.filter(
        tenant__account=account, revoked_at__isnull=True
    ).exists()
    approved_tpl = (
        EmailTemplate.objects.filter(
            tenant__account=account,
            status=TemplateStatus.ACTIVE,
            versions__is_current_approved=True,
        )
        .distinct()
        .exists()
    )
    sender_profiles_ok = SenderProfile.objects.filter(tenant__account=account).exists()
    account_active = account.status == AccountStatus.ACTIVE

    checklist = [
        {"label": "Account active", "ok": account_active},
        {"label": "At least one app (tenant)", "ok": tenants_exist},
        {"label": "At least one active API key", "ok": api_keys_ok},
        {"label": "At least one approved template", "ok": approved_tpl},
        {"label": "Sender profiles configured", "ok": sender_profiles_ok},
        {
            "label": "Email adapter health (technical check)",
            "ok": delivery["adapter_ok"],
        },
        {
            "label": "Real outbound delivery to inboxes",
            "ok": delivery["delivery_ready_ok"],
        },
    ]

    return {
        "stats_24h": stats_24h,
        "failures": failures,
        "recent_messages": recent_messages,
        "delivery": delivery,
        "portal_setup_checklist": checklist,
    }
