from functools import wraps

from django.contrib import messages as django_messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import resolve

from apps.accounts.models import AccountStatus
from apps.ui.services.portal_account import get_active_portal_account
from apps.ui.services.portal_permissions import (
    portal_user_can_approve_templates,
    portal_user_can_edit_content,
)

# POST allowed while account is not active (e.g. switch to another membership).
ALLOWED_POST_WHEN_ACCOUNT_INACTIVE = frozenset({"switch_account"})


def _block_inactive_account_mutations(request, account):
    """Block writes for suspended/cancelled accounts; allow GET and account switch."""
    if account is None or account.status == AccountStatus.ACTIVE:
        return None
    if request.method == "GET":
        return None
    try:
        match = resolve(request.path_info)
    except Exception:
        return None
    if match.url_name in ALLOWED_POST_WHEN_ACCOUNT_INACTIVE:
        return None
    django_messages.error(
        request,
        "This account cannot be modified while it is suspended or cancelled. Contact support if you need help.",
    )
    return redirect("portal:dashboard")


def operator_required(view_func):
    """Session-authenticated staff users only."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("ui:login")
        if not request.user.is_staff:
            from django.http import HttpResponseForbidden

            return HttpResponseForbidden("Staff access required.")
        return view_func(request, *args, **kwargs)

    return login_required(_wrapped)


def customer_login_required(view_func):
    """Session-authenticated users only (customer portal; staff may use portal too)."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("portal:login")
        return view_func(request, *args, **kwargs)

    return _wrapped


def portal_account_required(view_func):
    """Requires login and at least one account membership with a resolvable active account."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("portal:login")
        account = get_active_portal_account(request)
        if account is None:
            if request.user.is_staff:
                django_messages.info(
                    request,
                    "You have no customer account memberships. Use the operator dashboard for staff tools.",
                )
                return redirect("ui:dashboard")
            django_messages.info(
                request,
                "You need an account membership to use the app. Create an account or ask to be invited.",
            )
            return redirect("portal:signup")
        blocked = _block_inactive_account_mutations(request, account)
        if blocked is not None:
            return blocked
        return view_func(request, *args, **kwargs)

    return _wrapped


def portal_editor_required(view_func):
    """Owner, admin, or editor — not viewer (templates, workflows, sender profiles)."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("portal:login")
        account = get_active_portal_account(request)
        if account is None:
            if request.user.is_staff:
                django_messages.info(request, "No portal memberships. Use the operator dashboard.")
                return redirect("ui:dashboard")
            return redirect("portal:signup")
        if not portal_user_can_edit_content(request.user, account):
            return HttpResponseForbidden("You do not have permission to edit.")
        blocked = _block_inactive_account_mutations(request, account)
        if blocked is not None:
            return blocked
        return view_func(request, *args, **kwargs)

    return _wrapped


def portal_approve_required(view_func):
    """Owner or admin — template approval."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("portal:login")
        account = get_active_portal_account(request)
        if account is None:
            if request.user.is_staff:
                return redirect("ui:dashboard")
            return redirect("portal:signup")
        if not portal_user_can_approve_templates(request.user, account):
            return HttpResponseForbidden("Only account owners or admins can approve templates.")
        blocked = _block_inactive_account_mutations(request, account)
        if blocked is not None:
            return blocked
        return view_func(request, *args, **kwargs)

    return _wrapped


def portal_manage_required(view_func):
    """Owner/admin on active portal account."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("portal:login")
        from apps.ui.services.portal_permissions import portal_user_can_manage_tenants

        account = get_active_portal_account(request)
        if account is None:
            return redirect("portal:signup")
        if not portal_user_can_manage_tenants(request.user, account):
            return HttpResponseForbidden("You do not have permission to manage this account.")
        blocked = _block_inactive_account_mutations(request, account)
        if blocked is not None:
            return blocked
        return view_func(request, *args, **kwargs)

    return _wrapped
