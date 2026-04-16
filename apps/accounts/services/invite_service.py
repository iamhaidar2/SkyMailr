"""Account invite lifecycle (create, cancel, resend, accept)."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import (
    Account,
    AccountInvite,
    AccountInviteStatus,
    AccountMembership,
    AccountRole,
    UserProfile,
)
from apps.accounts.policy import PolicyError
from apps.accounts.services.enforcement import assert_can_invite_member

logger = logging.getLogger("apps.accounts.audit")

User = get_user_model()

INVITE_EXPIRY_DAYS = 14


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def active_membership_for_email(account: Account, email: str) -> AccountMembership | None:
    e = _normalize_email(email)
    return (
        AccountMembership.objects.filter(
            account=account,
            user__email__iexact=e,
            is_active=True,
        )
        .select_related("user")
        .first()
    )


@transaction.atomic
def create_invite(
    *,
    account: Account,
    email: str,
    role: str,
    invited_by: User,
) -> tuple[AccountInvite, str]:
    """Create a pending invite; returns (invite, raw_token) for the email link only."""
    email_n = _normalize_email(email)
    if not email_n:
        raise ValueError("Email is required.")

    if AccountMembership.objects.filter(account=account, user__email__iexact=email_n).exists():
        raise ValueError("A user with that email is already linked to this account.")

    if AccountInvite.objects.filter(
        account=account,
        email=email_n,
        status=AccountInviteStatus.PENDING,
    ).exists():
        raise ValueError("There is already a pending invite for this email.")

    try:
        assert_can_invite_member(account)
    except PolicyError as e:
        raise ValueError(e.detail) from e

    raw = secrets.token_urlsafe(32)
    inv = AccountInvite.objects.create(
        account=account,
        email=email_n,
        role=role,
        token_hash=_hash_token(raw),
        invited_by=invited_by,
        status=AccountInviteStatus.PENDING,
        expires_at=timezone.now() + timedelta(days=INVITE_EXPIRY_DAYS),
    )
    logger.info(
        "invite_created account_id=%s invite_id=%s email=%s role=%s by=%s",
        account.id,
        inv.id,
        email_n,
        role,
        invited_by.pk,
    )
    return inv, raw


@transaction.atomic
def cancel_invite(*, invite: AccountInvite) -> None:
    if invite.status != AccountInviteStatus.PENDING:
        raise ValueError("Only pending invites can be cancelled.")
    invite.status = AccountInviteStatus.CANCELLED
    invite.save(update_fields=["status", "updated_at"])
    logger.info("invite_cancelled invite_id=%s account_id=%s", invite.id, invite.account_id)


@transaction.atomic
def resend_invite(*, invite: AccountInvite) -> str:
    if invite.status != AccountInviteStatus.PENDING:
        raise ValueError("Only pending invites can be resent.")
    raw = secrets.token_urlsafe(32)
    invite.token_hash = _hash_token(raw)
    invite.expires_at = timezone.now() + timedelta(days=INVITE_EXPIRY_DAYS)
    invite.save(update_fields=["token_hash", "expires_at", "updated_at"])
    logger.info("invite_resent invite_id=%s account_id=%s", invite.id, invite.account_id)
    return raw


def get_pending_invite_by_raw_token(raw: str) -> AccountInvite | None:
    if not raw:
        return None
    h = _hash_token(raw)
    inv = AccountInvite.objects.filter(token_hash=h).select_related("account").first()
    if not inv:
        return None
    if inv.status != AccountInviteStatus.PENDING:
        return inv
    if inv.expires_at <= timezone.now():
        AccountInvite.objects.filter(pk=inv.pk, status=AccountInviteStatus.PENDING).update(
            status=AccountInviteStatus.EXPIRED,
            updated_at=timezone.now(),
        )
        inv.refresh_from_db()
        return inv
    return inv


@transaction.atomic
def accept_invite(*, raw_token: str, user: User) -> AccountMembership:
    """Attach user to account from invite; invite email must match user email."""
    inv = get_pending_invite_by_raw_token(raw_token)
    if not inv:
        raise ValueError("Invalid or unknown invite.")
    if inv.status != AccountInviteStatus.PENDING:
        if inv.status == AccountInviteStatus.ACCEPTED:
            raise ValueError("This invite was already accepted.")
        if inv.status == AccountInviteStatus.CANCELLED:
            raise ValueError("This invite was cancelled.")
        if inv.status == AccountInviteStatus.EXPIRED:
            raise ValueError("This invite has expired.")
        raise ValueError("This invite is no longer valid.")

    u_email = _normalize_email(user.email or "")
    if u_email != inv.email:
        raise ValueError("Signed-in email must match the invite address.")

    if active_membership_for_email(inv.account, inv.email):
        raise ValueError("You are already a member of this account.")

    m_existing = AccountMembership.objects.filter(account=inv.account, user=user).first()
    if m_existing is None or not m_existing.is_active:
        try:
            assert_can_invite_member(inv.account)
        except PolicyError as e:
            raise ValueError(e.detail) from e

    m, created = AccountMembership.objects.get_or_create(
        account=inv.account,
        user=user,
        defaults={"role": inv.role, "is_active": True},
    )
    if not created:
        m.role = inv.role
        m.is_active = True
        m.save(update_fields=["role", "is_active", "updated_at"])

    inv.status = AccountInviteStatus.ACCEPTED
    inv.accepted_at = timezone.now()
    inv.save(update_fields=["status", "accepted_at", "updated_at"])
    logger.info(
        "invite_accepted invite_id=%s account_id=%s user_id=%s",
        inv.id,
        inv.account_id,
        user.pk,
    )
    return m


def ensure_user_profile(user: User) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile
