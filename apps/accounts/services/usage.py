"""Account-level usage derived from existing models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import Account, AccountMembership
from apps.email_templates.models import EmailTemplate
from apps.messages.models import OutboundMessage, OutboundStatus
from apps.tenants.models import TenantAPIKey
from apps.workflows.models import Workflow


@dataclass(frozen=True)
class UsageSnapshot:
    tenant_count: int
    active_api_key_count: int
    template_count: int
    workflow_count: int
    active_member_count: int
    monthly_send_count: int
    period_start: datetime
    period_end: datetime


def _month_bounds(now=None):
    """Calendar month in the active timezone."""
    now = now or timezone.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def counts_toward_monthly_send_quota() -> Q:
    """
    Count outbound rows that represent a billable send attempt.
    Excludes drafts and cancelled; includes suppressed/failed (attempt was made).
    """
    return ~Q(
        status__in=(
            OutboundStatus.DRAFT,
            OutboundStatus.CANCELLED,
        )
    )


def usage_snapshot(account: Account) -> UsageSnapshot:
    start, end = _month_bounds()

    tenant_count = account.tenants.count()

    active_api_key_count = TenantAPIKey.objects.filter(
        tenant__account=account, revoked_at__isnull=True
    ).count()

    template_count = EmailTemplate.objects.filter(tenant__account=account).count()
    workflow_count = Workflow.objects.filter(tenant__account=account).count()
    active_member_count = AccountMembership.objects.filter(
        account=account, is_active=True
    ).count()

    monthly_send_count = OutboundMessage.objects.filter(
        tenant__account=account,
        created_at__gte=start,
        created_at__lt=end,
    ).filter(counts_toward_monthly_send_quota()).count()

    return UsageSnapshot(
        tenant_count=tenant_count,
        active_api_key_count=active_api_key_count,
        template_count=template_count,
        workflow_count=workflow_count,
        active_member_count=active_member_count,
        monthly_send_count=monthly_send_count,
        period_start=start,
        period_end=end,
    )
