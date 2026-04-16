"""Plan limits and suspension enforcement."""

from __future__ import annotations

import logging

from apps.accounts.models import Account, AccountMembership, AccountStatus
from apps.accounts.plans import get_effective_limits
from apps.accounts.policy import PolicyError
from apps.accounts.services.usage import usage_snapshot
from apps.tenants.models import Tenant, TenantAPIKey, TenantStatus

logger = logging.getLogger("apps.accounts.audit")


def assert_account_operational(account: Account) -> None:
    if account.status == AccountStatus.ACTIVE:
        return
    if account.status == AccountStatus.SUSPENDED:
        raise PolicyError(
            "account_suspended",
            "This account is suspended. Contact support.",
            status_code=403,
        )
    raise PolicyError(
        "account_inactive",
        "This account is not active.",
        status_code=403,
    )


def assert_tenant_operational(tenant: Tenant) -> None:
    if tenant.status == TenantStatus.ACTIVE:
        return
    raise PolicyError(
        "tenant_suspended",
        "This app (tenant) is suspended.",
        status_code=403,
    )


def assert_send_allowed(
    tenant: Tenant,
    *,
    bypass_quota: bool = False,
    bypass_suspension: bool = False,
) -> None:
    """
    Enforce account/tenant status and monthly send quota before creating outbound mail.
    Operator UI may pass bypass_quota / bypass_suspension for staff-only recovery paths.
    """
    account = tenant.account
    if not bypass_suspension:
        assert_account_operational(account)
        assert_tenant_operational(tenant)
    if bypass_quota:
        return

    limits = get_effective_limits(account)
    usage = usage_snapshot(account)
    if usage.monthly_send_count >= limits.max_monthly_sends:
        logger.info(
            "plan_limit_hit type=monthly_sends account_id=%s count=%s limit=%s",
            account.id,
            usage.monthly_send_count,
            limits.max_monthly_sends,
        )
        raise PolicyError(
            "monthly_send_limit",
            f"Monthly send limit reached ({limits.max_monthly_sends}). Upgrade your plan or wait until next month.",
            status_code=429,
        )


def _check_cap(account: Account, current: int, limit: int, code: str, message: str) -> None:
    if current >= limit:
        logger.info(
            "plan_limit_hit type=%s account_id=%s current=%s limit=%s",
            code,
            account.id,
            current,
            limit,
        )
        raise PolicyError(code, message, status_code=403)


def assert_can_create_tenant(account: Account) -> None:
    assert_account_operational(account)
    limits = get_effective_limits(account)
    n = Tenant.objects.filter(account=account).count()
    _check_cap(
        account,
        n,
        limits.max_tenants,
        "tenant_limit",
        f"Tenant limit reached ({limits.max_tenants}) for your plan.",
    )


def assert_can_create_api_key(account: Account) -> None:
    assert_account_operational(account)
    limits = get_effective_limits(account)
    n = TenantAPIKey.objects.filter(tenant__account=account, revoked_at__isnull=True).count()
    _check_cap(
        account,
        n,
        limits.max_active_api_keys,
        "api_key_limit",
        f"Active API key limit reached ({limits.max_active_api_keys}) for your plan.",
    )


def assert_can_create_template(account: Account) -> None:
    assert_account_operational(account)
    from apps.email_templates.models import EmailTemplate

    limits = get_effective_limits(account)
    n = EmailTemplate.objects.filter(tenant__account=account).count()
    _check_cap(
        account,
        n,
        limits.max_templates,
        "template_limit",
        f"Template limit reached ({limits.max_templates}) for your plan.",
    )


def assert_can_create_workflow(account: Account) -> None:
    assert_account_operational(account)
    from apps.workflows.models import Workflow

    limits = get_effective_limits(account)
    n = Workflow.objects.filter(tenant__account=account).count()
    _check_cap(
        account,
        n,
        limits.max_workflows,
        "workflow_limit",
        f"Workflow limit reached ({limits.max_workflows}) for your plan.",
    )


def assert_can_invite_member(account: Account) -> None:
    assert_account_operational(account)
    limits = get_effective_limits(account)
    n = AccountMembership.objects.filter(account=account, is_active=True).count()
    _check_cap(
        account,
        n,
        limits.max_members,
        "member_limit",
        f"Member limit reached ({limits.max_members}) for your plan.",
    )
