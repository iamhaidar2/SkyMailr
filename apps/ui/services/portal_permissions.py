"""Authorization for customer portal actions (membership roles; no implicit staff override)."""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

from apps.accounts.models import Account, AccountMembership, AccountRole


def portal_user_can_manage_tenants(user: AbstractBaseUser | AnonymousUser, account: Account) -> bool:
    """Owner or admin may create/edit tenants and API keys."""
    if not user.is_authenticated:
        return False
    return AccountMembership.objects.filter(
        account_id=account.id,
        user_id=user.pk,
        is_active=True,
        role__in=(AccountRole.OWNER, AccountRole.ADMIN),
    ).exists()


def portal_membership_role(user: AbstractBaseUser | AnonymousUser, account: Account) -> str | None:
    if not user.is_authenticated:
        return None
    m = (
        AccountMembership.objects.filter(
            account_id=account.id,
            user_id=user.pk,
            is_active=True,
        )
        .values_list("role", flat=True)
        .first()
    )
    return m
