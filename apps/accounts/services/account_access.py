"""Lightweight account access checks for views and future portal phases."""

from __future__ import annotations

from collections.abc import Collection

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

from apps.accounts.models import Account, AccountMembership


def _staff_bypass(user: AbstractBaseUser | AnonymousUser) -> bool:
    if isinstance(user, AnonymousUser):
        return False
    return bool(user.is_superuser or user.is_staff)


def get_user_accounts(user: AbstractBaseUser | AnonymousUser):
    """
    Accounts the user may act within.

    Staff and superusers see all accounts (operator-style bypass).
    Others: accounts with an active membership only.
    """
    qs = Account.objects.all()
    if _staff_bypass(user):
        return qs.order_by("name")
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        return Account.objects.none()
    return (
        qs.filter(
            memberships__user_id=user.pk,
            memberships__is_active=True,
        )
        .distinct()
        .order_by("name")
    )


def user_has_account_access(user: AbstractBaseUser | AnonymousUser, account: Account) -> bool:
    """True if user may access this account (active membership, or staff bypass)."""
    if _staff_bypass(user):
        return True
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        return False
    return AccountMembership.objects.filter(
        account_id=account.id,
        user_id=user.pk,
        is_active=True,
    ).exists()


def user_has_account_role(
    user: AbstractBaseUser | AnonymousUser,
    account: Account,
    roles: Collection[str],
) -> bool:
    """
    True if user has one of the given roles on this account, or staff bypass.

    `roles` is an iterable of role string values (e.g. AccountRole values).
    """
    if _staff_bypass(user):
        return True
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        return False
    role_set = set(roles)
    return AccountMembership.objects.filter(
        account_id=account.id,
        user_id=user.pk,
        is_active=True,
        role__in=role_set,
    ).exists()
