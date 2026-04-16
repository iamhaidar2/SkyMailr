"""Rules for who may change memberships and invites (owner vs admin)."""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

from apps.accounts.models import Account, AccountMembership, AccountRole


def count_active_owners(account: Account) -> int:
    return AccountMembership.objects.filter(
        account=account,
        is_active=True,
        role=AccountRole.OWNER,
    ).count()


def actor_role(user: AbstractBaseUser | AnonymousUser, account: Account) -> str | None:
    if not user.is_authenticated:
        return None
    m = (
        AccountMembership.objects.filter(account=account, user_id=user.pk, is_active=True)
        .values_list("role", flat=True)
        .first()
    )
    return m


def admin_may_touch_target(actor_role: str, target: AccountMembership) -> bool:
    """Admin may not change or deactivate owner rows; owner may change anyone (subject to last-owner rule)."""
    if actor_role == AccountRole.OWNER:
        return True
    if actor_role == AccountRole.ADMIN:
        return target.role != AccountRole.OWNER
    return False


def may_assign_role(actor_role: str, new_role: str) -> bool:
    if actor_role == AccountRole.OWNER:
        return True
    if actor_role == AccountRole.ADMIN:
        return new_role != AccountRole.OWNER
    return False


def would_remove_last_owner(
    *,
    account: Account,
    target: AccountMembership,
    new_role: str | None = None,
    deactivate: bool = False,
) -> bool:
    """True if this action would leave the account with zero active owners."""
    if target.role != AccountRole.OWNER or not target.is_active:
        return False
    owners = count_active_owners(account)
    if owners <= 1:
        if deactivate:
            return True
        if new_role is not None and new_role != AccountRole.OWNER:
            return True
    return False
