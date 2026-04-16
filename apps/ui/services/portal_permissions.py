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


def portal_user_can_manage_members(user: AbstractBaseUser | AnonymousUser, account: Account) -> bool:
    """Owner or admin may invite members and change roles (same privilege tier as tenant management)."""
    return portal_user_can_manage_tenants(user, account)


def portal_user_can_edit_content(user: AbstractBaseUser | AnonymousUser, account: Account) -> bool:
    """Owner, admin, or editor may edit automation content (not viewer)."""
    if not user.is_authenticated:
        return False
    return AccountMembership.objects.filter(
        account_id=account.id,
        user_id=user.pk,
        is_active=True,
        role__in=(AccountRole.OWNER, AccountRole.ADMIN, AccountRole.EDITOR),
    ).exists()


def portal_user_can_approve_templates(user: AbstractBaseUser | AnonymousUser, account: Account) -> bool:
    """Approve template versions: owner or admin only."""
    if not user.is_authenticated:
        return False
    return AccountMembership.objects.filter(
        account_id=account.id,
        user_id=user.pk,
        is_active=True,
        role__in=(AccountRole.OWNER, AccountRole.ADMIN),
    ).exists()


def portal_user_is_viewer_only(user: AbstractBaseUser | AnonymousUser, account: Account) -> bool:
    if not user.is_authenticated:
        return False
    return AccountMembership.objects.filter(
        account_id=account.id,
        user_id=user.pk,
        is_active=True,
        role=AccountRole.VIEWER,
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
