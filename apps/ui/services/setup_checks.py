"""Aggregated setup / health signals for the operator onboarding page."""

from __future__ import annotations

import os
from typing import Any

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.email_templates.models import EmailTemplate, TemplateStatus
from apps.providers.registry import get_email_provider
from apps.tenants.models import SenderProfile, Tenant, TenantAPIKey


def gather_setup_status() -> dict[str, Any]:
    tenants_exist = Tenant.objects.exists()
    api_keys = TenantAPIKey.objects.filter(revoked_at__isnull=True).count()
    approved_tpl = EmailTemplate.objects.filter(
        status=TemplateStatus.ACTIVE,
        versions__is_current_approved=True,
    ).distinct().count()
    sender_profiles = SenderProfile.objects.count()
    provider = get_email_provider()
    ok, detail = provider.health_check()
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
            "id": "provider",
            "label": "Email provider healthy",
            "ok": ok,
            "hint": detail or "dummy is fine for development.",
        },
        {
            "id": "postal",
            "label": "Postal configured (if not using dummy/console)",
            "ok": email_provider in ("dummy", "console") or bool(
                os.environ.get("POSTAL_BASE_URL", "").strip()
            ),
            "hint": "Set POSTAL_BASE_URL and POSTAL_SERVER_API_KEY when using postal.",
        },
    ]

    return {
        "checklist": checklist,
        "email_provider": email_provider,
        "provider_name": provider.name,
        "provider_ok": ok,
        "provider_detail": detail,
        "llm_provider": getattr(settings, "LLM_PROVIDER", "dummy").lower(),
        "now": timezone.now(),
    }
