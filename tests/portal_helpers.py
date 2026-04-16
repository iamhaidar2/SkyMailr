"""Shared helpers for customer portal tests (session account pinning)."""

from apps.ui.services.portal_account import set_active_portal_account


def bind_portal_account_session(client, user, account) -> None:
    """Log in and set active portal account so views see the expected tenant/account (reuse-db safe)."""
    client.force_login(user)
    # `client.session` is a new SessionStore per attribute access; keep one reference when mutating.
    session = client.session
    set_active_portal_account(session, account)
    session.save()
