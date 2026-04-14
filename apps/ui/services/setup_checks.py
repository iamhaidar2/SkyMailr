"""Aggregated setup / health signals for the operator onboarding page."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.email_templates.models import EmailTemplate, TemplateStatus
from apps.tenants.models import SenderProfile, Tenant, TenantAPIKey
from apps.ui.services.delivery_context import build_delivery_context


def gather_setup_status() -> dict[str, Any]:
    tenants_exist = Tenant.objects.exists()
    api_keys = TenantAPIKey.objects.filter(revoked_at__isnull=True).count()
    approved_tpl = EmailTemplate.objects.filter(
        status=TemplateStatus.ACTIVE,
        versions__is_current_approved=True,
    ).distinct().count()
    sender_profiles = SenderProfile.objects.count()
    delivery = build_delivery_context()
    email_provider = getattr(settings, "EMAIL_PROVIDER", "dummy").lower()
    redis_url = getattr(settings, "CELERY_BROKER_URL", "") or ""
    db_ok = True
    try:
        connection.ensure_connection()
    except Exception:
        db_ok = False

    checklist = [
        {
            "id": "database",
            "label": "Database connected",
            "ok": db_ok,
            "hint": "Check DATABASE_URL and migrations.",
        },
        {
            "id": "redis",
            "label": "Redis / Celery broker configured",
            "ok": bool(redis_url),
            "hint": "Set REDIS_URL or CELERY_BROKER_URL for workers.",
        },
        {
            "id": "tenants",
            "label": "At least one tenant exists",
            "ok": tenants_exist,
            "hint": "Create a tenant via admin or seed command.",
        },
        {
            "id": "api_keys",
            "label": "At least one active API key",
            "ok": api_keys > 0,
            "hint": "Generate a key from Tenants or the API.",
        },
        {
            "id": "templates",
            "label": "At least one approved template",
            "ok": approved_tpl > 0,
            "hint": "Approve a template version before sending templated mail.",
        },
        {
            "id": "sender_profiles",
            "label": "Sender profiles configured",
            "ok": sender_profiles > 0,
            "hint": "Add sender profiles for outbound identity.",
        },
        {
            "id": "adapter",
            "label": "Email adapter health (technical check)",
            "ok": delivery["adapter_ok"],
            "hint": delivery["adapter_detail"] or "Health check on the configured provider class.",
        },
        {
            "id": "delivery",
            "label": "Real outbound delivery to inboxes",
            "ok": delivery["delivery_ready_ok"],
            "hint": delivery["delivery_readiness_hint"],
        },
    ]

    return {
        "checklist": checklist,
        "email_provider": email_provider,
        "provider_name": delivery["adapter_name"],
        "provider_ok": delivery["adapter_ok"],
        "provider_detail": delivery["adapter_detail"],
        "delivery": delivery,
        "llm_provider": getattr(settings, "LLM_PROVIDER", "dummy").lower(),
        "now": timezone.now(),
    }
