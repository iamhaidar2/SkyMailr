"""
DB-backed dispatch throttling: per-tenant rolling minute window and optional
per-domain daily / per-minute caps (TenantDomainSendingPolicy).

Uses DispatchRateSlot rows as reservations. Callers should use
`transaction.atomic()` and invoke `can_send_now` then `record_send_attempt`
in the same transaction so counts stay consistent under concurrency.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from apps.messages.models import OutboundMessage

logger = logging.getLogger(__name__)

ROLLING_WINDOW = timedelta(seconds=60)


def _floor_per_minute() -> int:
    return int(getattr(settings, "SKYMAILR_DISPATCH_RATE_LIMIT_FLOOR_PER_MINUTE", 30))


def effective_tenant_per_minute(tenant) -> int:
    """Tenant cap; 0 or unset uses conservative floor (never unlimited by accident)."""
    raw = int(getattr(tenant, "rate_limit_per_minute", None) or 0)
    if raw <= 0:
        return _floor_per_minute()
    return raw


def _host_from_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    return email.split("@", 1)[-1].strip().lower()


def resolve_sending_hostname(message: OutboundMessage) -> str:
    from apps.messages.models import OutboundMessage

    if not isinstance(message, OutboundMessage):
        return ""
    if message.sender_profile_id and message.sender_profile:
        return _host_from_email(message.sender_profile.from_email)
    return _host_from_email(message.tenant.default_sender_email or "")


def resolve_tenant_domain(message: OutboundMessage):
    """Return TenantDomain if hostname matches stored domain (exact)."""
    from apps.tenants.models import TenantDomain

    host = resolve_sending_hostname(message)
    if not host:
        return None
    return TenantDomain.objects.filter(tenant_id=message.tenant_id, domain=host).first()


def resolve_domain_policy(message: OutboundMessage):
    from apps.tenants.models import TenantDomainSendingPolicy

    td = resolve_tenant_domain(message)
    if not td:
        return None, None
    policy = TenantDomainSendingPolicy.objects.filter(tenant_domain=td).first()
    return td, policy


def _tenant_tz(tenant):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tenant.timezone or "UTC")
    except Exception:
        from zoneinfo import ZoneInfo

        return ZoneInfo("UTC")


def local_day_bounds(tenant, now: datetime) -> tuple[datetime, datetime]:
    """Start (inclusive) and end (exclusive) of tenant-local calendar day as aware UTC datetimes."""
    tz = _tenant_tz(tenant)
    local = now.astimezone(tz)
    start_local = datetime.combine(local.date(), time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _next_tenant_window_opens_at(tenant, *, now: datetime, tenant_limit: int) -> datetime:
    from apps.messages.models import DispatchRateSlot

    if tenant_limit <= 0:
        return now + ROLLING_WINDOW
    t_cut = now - ROLLING_WINDOW
    oldest = (
        DispatchRateSlot.objects.filter(tenant=tenant, created_at__gte=t_cut)
        .order_by("created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if oldest:
        return oldest + ROLLING_WINDOW
    return now + timedelta(seconds=1)


def _next_domain_minute_opens_at(tenant_domain, *, now: datetime, per_minute: int) -> datetime:
    from apps.messages.models import DispatchRateSlot

    if per_minute <= 0:
        return now + ROLLING_WINDOW
    t_cut = now - ROLLING_WINDOW
    oldest = (
        DispatchRateSlot.objects.filter(tenant_domain=tenant_domain, created_at__gte=t_cut)
        .order_by("created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if oldest:
        return oldest + ROLLING_WINDOW
    return now + timedelta(seconds=1)


def _next_domain_day_opens_at(tenant, tenant_domain, *, now: datetime) -> datetime:
    _, end = local_day_bounds(tenant, now)
    return end


def calculate_next_send_time(message: OutboundMessage) -> datetime:
    """
    Earliest time at which this message might pass tenant + domain throttle,
    assuming caps stay unchanged (best-effort).
    """
    now = timezone.now()
    tenant = message.tenant
    tenant_limit = effective_tenant_per_minute(tenant)
    candidates = [_next_tenant_window_opens_at(tenant, now=now, tenant_limit=tenant_limit)]
    td, policy = resolve_domain_policy(message)
    if td and policy and policy.enabled:
        if policy.per_minute_limit:
            candidates.append(
                _next_domain_minute_opens_at(td, now=now, per_minute=int(policy.per_minute_limit))
            )
        if policy.daily_limit:
            candidates.append(_next_domain_day_opens_at(tenant, td, now=now))
    return max(candidates)


def _tenant_slot_count(tenant, *, since: datetime) -> int:
    from apps.messages.models import DispatchRateSlot

    return DispatchRateSlot.objects.filter(tenant=tenant, created_at__gte=since).count()


def _domain_slot_count(tenant_domain, *, since: datetime) -> int:
    from apps.messages.models import DispatchRateSlot

    return DispatchRateSlot.objects.filter(tenant_domain=tenant_domain, created_at__gte=since).count()


def _domain_day_slot_count(tenant_domain, *, start: datetime, end: datetime) -> int:
    from apps.messages.models import DispatchRateSlot

    return DispatchRateSlot.objects.filter(
        tenant_domain=tenant_domain,
        created_at__gte=start,
        created_at__lt=end,
    ).count()


def can_send_now(message: OutboundMessage) -> tuple[bool, datetime | None, str]:
    """
    Read-only check (no slot row) under tenant row lock.
    Must run inside the same ``transaction.atomic()`` as ``record_send_attempt`` for correctness.
    """
    from apps.messages.models import OutboundMessage
    from apps.tenants.models import Tenant

    if not isinstance(message, OutboundMessage):
        return False, None, "invalid_message"

    now = timezone.now()
    tenant_limit = effective_tenant_per_minute(message.tenant)
    t_cut = now - ROLLING_WINDOW

    Tenant.objects.select_for_update().filter(pk=message.tenant_id).first()
    if _tenant_slot_count(message.tenant, since=t_cut) >= tenant_limit:
        when = _next_tenant_window_opens_at(message.tenant, now=now, tenant_limit=tenant_limit)
        return False, when, "rate_limited: tenant limit exceeded"

    td, policy = resolve_domain_policy(message)
    if td and policy and policy.enabled:
        if policy.per_minute_limit:
            dlim = int(policy.per_minute_limit)
            if _domain_slot_count(td, since=t_cut) >= dlim:
                when = _next_domain_minute_opens_at(td, now=now, per_minute=dlim)
                return False, when, "rate_limited: domain per-minute limit exceeded"
        if policy.daily_limit:
            day_start, day_end = local_day_bounds(message.tenant, now)
            if _domain_day_slot_count(td, start=day_start, end=day_end) >= int(policy.daily_limit):
                when = _next_domain_day_opens_at(message.tenant, td, now=now)
                return False, when, "rate_limited: domain daily limit exceeded"

    return True, None, ""


def record_send_attempt(message: OutboundMessage) -> bool:
    """
    Insert a DispatchRateSlot after a successful can_send_now in the same transaction.
    Re-checks limits under the same tenant lock to avoid overshoot.
    Returns False if a concurrent sender consumed capacity (caller should defer).
    """
    from apps.messages.models import DispatchRateSlot, OutboundMessage
    from apps.tenants.models import Tenant

    if not isinstance(message, OutboundMessage):
        return False

    now = timezone.now()
    tenant_limit = effective_tenant_per_minute(message.tenant)
    t_cut = now - ROLLING_WINDOW

    Tenant.objects.select_for_update().filter(pk=message.tenant_id).first()
    if _tenant_slot_count(message.tenant, since=t_cut) >= tenant_limit:
        logger.warning("record_send_attempt: tenant limit race for message %s", message.id)
        return False

    td, policy = resolve_domain_policy(message)
    if td and policy and policy.enabled:
        if policy.per_minute_limit:
            dlim = int(policy.per_minute_limit)
            if _domain_slot_count(td, since=t_cut) >= dlim:
                logger.warning("record_send_attempt: domain minute race for message %s", message.id)
                return False
        if policy.daily_limit:
            day_start, day_end = local_day_bounds(message.tenant, now)
            if _domain_day_slot_count(td, start=day_start, end=day_end) >= int(policy.daily_limit):
                logger.warning("record_send_attempt: domain daily race for message %s", message.id)
                return False

    DispatchRateSlot.objects.create(
        tenant=message.tenant,
        tenant_domain=td if (policy and policy.enabled) else None,
        outbound_message=message,
    )
    return True
