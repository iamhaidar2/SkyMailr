"""
Operator deliverability UI thresholds (bounce / complaint rate bands).

Rates are fractions in [0, 1], e.g. 0.02 == 2%.
Override via Django settings if needed later.
"""

from __future__ import annotations

from typing import Literal

from django.conf import settings

BounceRateLevel = Literal["ok", "warning", "danger"]
ComplaintRateLevel = Literal["ok", "warning", "danger"]

BOUNCE_RATE_WARNING = float(
    getattr(settings, "SKYMAILR_DELIVERABILITY_BOUNCE_WARN", 0.02)
)
BOUNCE_RATE_DANGER = float(
    getattr(settings, "SKYMAILR_DELIVERABILITY_BOUNCE_DANGER", 0.05)
)
COMPLAINT_RATE_WARNING = float(
    getattr(settings, "SKYMAILR_DELIVERABILITY_COMPLAINT_WARN", 0.001)
)
COMPLAINT_RATE_DANGER = float(
    getattr(settings, "SKYMAILR_DELIVERABILITY_COMPLAINT_DANGER", 0.003)
)


def bounce_rate_level(rate: float) -> BounceRateLevel:
    if rate >= BOUNCE_RATE_DANGER:
        return "danger"
    if rate >= BOUNCE_RATE_WARNING:
        return "warning"
    return "ok"


def complaint_rate_level(rate: float) -> ComplaintRateLevel:
    if rate >= COMPLAINT_RATE_DANGER:
        return "danger"
    if rate >= COMPLAINT_RATE_WARNING:
        return "warning"
    return "ok"


ReturnPathLevel = Literal["configured", "partial", "unknown"]


def return_path_config_level(*, cname_name: str, cname_target: str) -> ReturnPathLevel:
    """Infer return-path DNS readiness from TenantDomain CNAME fields."""
    n = (cname_name or "").strip()
    t = (cname_target or "").strip()
    if n and t:
        return "configured"
    if n or t:
        return "partial"
    return "unknown"
