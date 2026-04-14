"""Adapter health vs outbound delivery readiness for operator UI copy."""

from __future__ import annotations

import os
from typing import Any

from django.conf import settings

from apps.providers.registry import get_email_provider


def build_delivery_context() -> dict[str, Any]:
    """
    - Adapter: Python class + health_check() — technical connectivity/config.
    - Delivery: whether real email leaves the app to real inboxes (Postal/SMTP path).
    - dummy: no network send; console: logs only.
    """
    email_provider = getattr(settings, "EMAIL_PROVIDER", "dummy").lower()
    p = get_email_provider()
    adapter_ok, adapter_detail = p.health_check()

    is_dummy = email_provider == "dummy"
    is_console = email_provider == "console"
    is_non_sending_mode = is_dummy or is_console

    postal_url = (os.environ.get("POSTAL_BASE_URL") or "").strip()
    postal_key = (os.environ.get("POSTAL_SERVER_API_KEY") or "").strip()
    is_postal = email_provider == "postal"

    if is_non_sending_mode:
        delivery_label = "No real email delivery"
        if is_dummy:
            delivery_hint = (
                "EMAIL_PROVIDER is dummy: outbound is a no-op. Use console or Postal for real sends."
            )
        else:
            delivery_hint = (
                "EMAIL_PROVIDER is console: messages are logged only, not delivered to inboxes."
            )
    elif is_postal:
        if postal_url and postal_key:
            delivery_label = "Outbound delivery configured (Postal)"
            delivery_hint = "Postal adapter can send real mail if DNS/domains are valid."
        else:
            delivery_label = "Postal selected but incomplete"
            delivery_hint = "Set POSTAL_BASE_URL and POSTAL_SERVER_API_KEY for real delivery."
    else:
        delivery_label = "Outbound delivery depends on adapter"
        delivery_hint = f"Adapter “{p.name}”: confirm credentials and network for your environment."

    if is_non_sending_mode:
        delivery_ready_ok = False
    elif is_postal:
        delivery_ready_ok = bool(postal_url and postal_key)
    else:
        delivery_ready_ok = True

    return {
        "email_provider_setting": email_provider,
        "is_non_sending_mode": is_non_sending_mode,
        "is_dummy": is_dummy,
        "is_console": is_console,
        "adapter_ok": adapter_ok,
        "adapter_detail": adapter_detail,
        "adapter_name": p.name,
        "delivery_readiness_label": delivery_label,
        "delivery_readiness_hint": delivery_hint,
        "postal_base_configured": bool(postal_url),
        "postal_key_configured": bool(postal_key),
        "delivery_ready_ok": delivery_ready_ok,
    }
