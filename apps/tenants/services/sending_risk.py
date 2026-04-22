"""Tenant sending risk metrics and automated pause (Postal reputation protection)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.messages.models import MessageType, OutboundMessage, OutboundStatus
from apps.tenants.models import SendingPauseScope, SendingPauseSource, Tenant

logger = logging.getLogger(__name__)

# Fractions in [0, 1]. Override via settings.SKYMAILR_RISK_*.
COMPLAINT_RATE_PAUSE_MARKETING = float(
    getattr(settings, "SKYMAILR_RISK_COMPLAINT_PAUSE_MARKETING", 0.003)
)  # 0.3%
BOUNCE_RATE_PAUSE_MARKETING = float(
    getattr(settings, "SKYMAILR_RISK_BOUNCE_PAUSE_MARKETING", 0.05)
)  # 5%
COMPLAINT_RATE_PAUSE_NON_CRITICAL = float(
    getattr(settings, "SKYMAILR_RISK_COMPLAINT_PAUSE_NON_CRITICAL", 0.01)
)  # 1%
FAILED_RATE_PAUSE_MARKETING = float(
    getattr(settings, "SKYMAILR_RISK_FAILED_RATE_PAUSE_MARKETING", 0.12)
)
VOLUME_SPIKE_RATIO = float(getattr(settings, "SKYMAILR_RISK_VOLUME_SPIKE_RATIO", 4.0))
VOLUME_SPIKE_MIN_BASELINE = int(getattr(settings, "SKYMAILR_RISK_VOLUME_SPIKE_MIN_BASELINE", 40))
NEW_RECIPIENT_SPIKE_RATIO = float(getattr(settings, "SKYMAILR_RISK_NEW_RECIPIENT_SPIKE_RATIO", 3.0))

_SENT_PATH_STATUSES = (
    OutboundStatus.SENT,
    OutboundStatus.DELIVERED,
    OutboundStatus.BOUNCED,
    OutboundStatus.COMPLAINED,
    OutboundStatus.FAILED,
)


def _window_qs(tenant: Tenant, *, hours: int = 24):
    t0 = timezone.now() - timedelta(hours=hours)
    return OutboundMessage.objects.filter(tenant=tenant, updated_at__gte=t0)


def _denominator(qs) -> int:
    return qs.filter(status__in=_SENT_PATH_STATUSES).count()


def compute_tenant_sending_risk_metrics(tenant: Tenant, *, hours: int = 24) -> dict[str, Any]:
    """Recent metrics for UI and automated pause (aligned with deliverability 24h window)."""
    qs = _window_qs(tenant, hours=hours)
    delivered = qs.filter(status=OutboundStatus.DELIVERED).count()
    bounced = qs.filter(status=OutboundStatus.BOUNCED).count()
    complained = qs.filter(status=OutboundStatus.COMPLAINED).count()
    failed = qs.filter(status=OutboundStatus.FAILED).count()
    suppressed = qs.filter(status=OutboundStatus.SUPPRESSED).count()
    sent_path = _denominator(qs)
    denom = max(sent_path, 1)

    bounce_rate = bounced / denom
    complaint_rate = complained / denom
    failed_rate = failed / denom

    t_now = timezone.now()
    prev_start = t_now - timedelta(hours=hours * 2)
    prev_end = t_now - timedelta(hours=hours)
    qs_prev = OutboundMessage.objects.filter(
        tenant=tenant, updated_at__gte=prev_start, updated_at__lt=prev_end
    )
    sent_path_prev = _denominator(qs_prev)
    volume_spike_ratio = (sent_path / max(sent_path_prev, 1)) if sent_path_prev else 0.0

    created_qs = OutboundMessage.objects.filter(
        tenant=tenant, created_at__gte=t_now - timedelta(hours=hours)
    )
    new_recipients_now = created_qs.values("to_email").distinct().count()
    created_prev = OutboundMessage.objects.filter(
        tenant=tenant,
        created_at__gte=t_now - timedelta(hours=hours * 2),
        created_at__lt=t_now - timedelta(hours=hours),
    )
    new_recipients_prev = created_prev.values("to_email").distinct().count()
    new_recipient_spike_ratio = (
        (new_recipients_now / max(new_recipients_prev, 1)) if new_recipients_prev else 0.0
    )

    return {
        "window_hours": hours,
        "sent_path": sent_path,
        "delivered": delivered,
        "bounced": bounced,
        "complained": complained,
        "failed": failed,
        "suppressed": suppressed,
        "bounce_rate": round(bounce_rate, 6),
        "complaint_rate": round(complaint_rate, 6),
        "failed_rate": round(failed_rate, 6),
        "volume_spike_ratio": round(volume_spike_ratio, 4),
        "sent_path_prev_window": sent_path_prev,
        "new_distinct_recipients_24h": new_recipients_now,
        "new_distinct_recipients_prev_24h": new_recipients_prev,
        "new_recipient_spike_ratio": round(new_recipient_spike_ratio, 4),
    }


def _risk_score_from_metrics(m: dict[str, Any]) -> int:
    """0–100 rough score for operator dashboard (not statistically rigorous)."""
    br = float(m.get("bounce_rate") or 0)
    cr = float(m.get("complaint_rate") or 0)
    fr = float(m.get("failed_rate") or 0)
    score = min(100, int(br * 200 + cr * 5000 + fr * 150))
    if m.get("volume_spike_ratio", 0) >= VOLUME_SPIKE_RATIO and m.get("sent_path_prev_window", 0) >= 10:
        score = min(100, score + 15)
    if m.get("new_recipient_spike_ratio", 0) >= NEW_RECIPIENT_SPIKE_RATIO and m.get(
        "new_distinct_recipients_prev_24h", 0
    ) >= 20:
        score = min(100, score + 10)
    return score


def evaluate_automated_pause_triggers(metrics: dict[str, Any]) -> tuple[SendingPauseScope | None, str]:
    """
    Returns (scope, reason) if automation should pause, else (None, "").
    Strictest scope wins (non_critical > marketing).
    """
    br = float(metrics.get("bounce_rate") or 0)
    cr = float(metrics.get("complaint_rate") or 0)
    fr = float(metrics.get("failed_rate") or 0)
    sent = int(metrics.get("sent_path") or 0)
    complained = int(metrics.get("complained") or 0)

    reasons: list[str] = []
    scope: SendingPauseScope | None = None

    if cr >= COMPLAINT_RATE_PAUSE_NON_CRITICAL or (sent >= 50 and cr >= 0.005 and complained >= 5):
        scope = SendingPauseScope.NON_CRITICAL
        reasons.append(
            f"Complaint rate {cr:.4%} or elevated complaint volume in 24h (threshold "
            f"{COMPLAINT_RATE_PAUSE_NON_CRITICAL:.2%} / spike rule)"
        )

    if br >= BOUNCE_RATE_PAUSE_MARKETING:
        if scope != SendingPauseScope.NON_CRITICAL:
            scope = SendingPauseScope.MARKETING_LIFECYCLE
        reasons.append(f"Bounce rate {br:.2%} (pause marketing threshold {BOUNCE_RATE_PAUSE_MARKETING:.0%})")

    if cr >= COMPLAINT_RATE_PAUSE_MARKETING and scope != SendingPauseScope.NON_CRITICAL:
        scope = SendingPauseScope.MARKETING_LIFECYCLE
        reasons.append(
            f"Complaint rate {cr:.4%} (pause marketing threshold {COMPLAINT_RATE_PAUSE_MARKETING:.2%})"
        )

    if fr >= FAILED_RATE_PAUSE_MARKETING and scope != SendingPauseScope.NON_CRITICAL:
        scope = SendingPauseScope.MARKETING_LIFECYCLE
        reasons.append(f"Failed send rate {fr:.2%} (threshold {FAILED_RATE_PAUSE_MARKETING:.0%})")

    prev = int(metrics.get("sent_path_prev_window") or 0)
    now_ct = int(metrics.get("sent_path") or 0)
    if prev >= VOLUME_SPIKE_MIN_BASELINE:
        ratio = float(metrics.get("volume_spike_ratio") or 0)
        if ratio >= VOLUME_SPIKE_RATIO:
            if scope != SendingPauseScope.NON_CRITICAL:
                scope = SendingPauseScope.MARKETING_LIFECYCLE
            reasons.append(f"Volume spike vs prior 24h (ratio {ratio:.1f}x)")

    nr_prev = int(metrics.get("new_distinct_recipients_prev_24h") or 0)
    if nr_prev >= 30:
        nr_ratio = float(metrics.get("new_recipient_spike_ratio") or 0)
        if nr_ratio >= NEW_RECIPIENT_SPIKE_RATIO:
            if scope != SendingPauseScope.NON_CRITICAL:
                scope = SendingPauseScope.MARKETING_LIFECYCLE
            reasons.append(f"New recipient count spike (ratio {nr_ratio:.1f}x)")

    if not reasons:
        return None, ""
    return scope, " · ".join(reasons)


def apply_automated_risk_pause(tenant: Tenant) -> dict[str, Any]:
    """
    Recompute metrics; auto-pause tenant if triggers fire.
    Does not override a manual operator pause (only updates metrics cache).
    """
    metrics = compute_tenant_sending_risk_metrics(tenant)
    score = _risk_score_from_metrics(metrics)
    now = timezone.now()

    tenant.refresh_from_db()
    if tenant.sending_paused and tenant.sending_pause_source == SendingPauseSource.MANUAL:
        Tenant.objects.filter(pk=tenant.pk).update(
            risk_score=score,
            risk_metrics_cache=metrics,
            last_risk_eval_at=now,
        )
        return {"updated": "metrics_only", "metrics": metrics, "risk_score": score}

    desired_scope, reason = evaluate_automated_pause_triggers(metrics)
    if desired_scope:
        Tenant.objects.filter(pk=tenant.pk).update(
            sending_paused=True,
            sending_pause_scope=desired_scope,
            sending_pause_source=SendingPauseSource.AUTO,
            sending_pause_reason=reason[:4000],
            risk_score=score,
            risk_metrics_cache=metrics,
            last_risk_eval_at=now,
        )
        logger.warning(
            "tenant_auto_sending_pause tenant_id=%s scope=%s score=%s",
            tenant.id,
            desired_scope,
            score,
        )
        return {
            "updated": "paused",
            "scope": desired_scope,
            "reason": reason,
            "metrics": metrics,
            "risk_score": score,
        }

    Tenant.objects.filter(pk=tenant.pk).update(
        risk_score=score,
        risk_metrics_cache=metrics,
        last_risk_eval_at=now,
    )
    return {"updated": "metrics", "metrics": metrics, "risk_score": score}


def message_type_blocked_by_sending_pause(tenant: Tenant, message_type: str) -> tuple[bool, str]:
    """If tenant is paused, whether this message_type is blocked."""
    if not tenant.sending_paused:
        return False, ""
    scope = tenant.sending_pause_scope or SendingPauseScope.MARKETING_LIFECYCLE
    mt = (message_type or "").strip().lower()
    if scope == SendingPauseScope.MARKETING_LIFECYCLE:
        if mt in (MessageType.MARKETING.value, MessageType.LIFECYCLE.value):
            return True, "sending_paused_marketing"
        return False, ""
    if scope == SendingPauseScope.NON_CRITICAL:
        if mt == MessageType.SYSTEM.value:
            return False, ""
        return True, "sending_paused_non_critical"
    return False, ""


def dispatch_blocked_by_sending_pause(message: OutboundMessage) -> tuple[bool, str]:
    tenant = message.tenant
    blocked, code = message_type_blocked_by_sending_pause(tenant, message.message_type)
    return blocked, code
