"""Active account context for the customer portal (membership-scoped, not staff-global)."""

from __future__ import annotations

from django.contrib.sessions.backends.base import SessionBase

from apps.accounts.models import Account

SESSION_PORTAL_ACCOUNT_KEY = "customer_portal_account_id"


def get_portal_accounts_for_user(user) -> list[Account]:
    """Accounts the user may access in the portal (active membership only; no staff bypass)."""
    from apps.accounts.models import AccountMembership

    if not user.is_authenticated:
        return []
    return list(
        Account.objects.filter(
            memberships__user_id=user.pk,
            memberships__is_active=True,
        )
        .distinct()
        .order_by("name")
    )


def get_active_portal_account(request) -> Account | None:
    """Resolve current portal account from session, falling back to the user's first membership."""
    user = request.user
    if not user.is_authenticated:
        return None
    accounts = get_portal_accounts_for_user(user)
    if not accounts:
        return None
    raw = request.session.get(SESSION_PORTAL_ACCOUNT_KEY)
    if raw:
        for a in accounts:
            if str(a.id) == str(raw):
                return a
    return accounts[0]


def set_active_portal_account(session: SessionBase, account: Account) -> None:
    session[SESSION_PORTAL_ACCOUNT_KEY] = str(account.pk)
    session.modified = True


def clear_active_portal_account(session: SessionBase) -> None:
    session.pop(SESSION_PORTAL_ACCOUNT_KEY, None)
    session.modified = True
