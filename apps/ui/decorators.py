from functools import wraps

from django.contrib import messages as django_messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from apps.ui.services.portal_account import get_active_portal_account


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
        return view_func(request, *args, **kwargs)

    return _wrapped
