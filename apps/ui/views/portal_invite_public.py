"""Public invite acceptance and invite-based signup."""

from __future__ import annotations

import logging

from django.contrib import messages as django_messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.models import AccountInviteStatus
from apps.accounts.services import invite_service
from apps.accounts.services.email_verification import create_verification_token
from apps.accounts.services.invite_service import ensure_user_profile
from apps.ui.forms_customer import InviteSignupForm
from apps.ui.services.portal_account import set_active_portal_account
from apps.ui.services.portal_mail import send_email_verification_email
from apps.ui.services.rate_limit import allow_request

User = get_user_model()
logger = logging.getLogger("apps.accounts.audit")


@require_http_methods(["GET", "POST"])
def invite_accept(request, token: str):
    """Accept an account invite (logged-in user must match invite email)."""
    inv = invite_service.get_pending_invite_by_raw_token(token)
    if not inv:
        return render(
            request,
            "ui/customer/invite_invalid.html",
            {"reason": "This invitation link is invalid."},
            status=404,
        )
    if inv.status != AccountInviteStatus.PENDING:
        reason = {
            AccountInviteStatus.ACCEPTED: "This invitation was already accepted.",
            AccountInviteStatus.CANCELLED: "This invitation was cancelled.",
            AccountInviteStatus.EXPIRED: "This invitation has expired.",
        }.get(inv.status, "This invitation is no longer valid.")
        return render(request, "ui/customer/invite_invalid.html", {"reason": reason}, status=400)

    if request.method == "POST":
        if not allow_request(f"portal:invite_accept:{token[:24]}", limit=30, window_seconds=3600):
            django_messages.error(request, "Too many attempts. Try again later.")
            return redirect("portal:invite_accept", token=token)
        if not request.user.is_authenticated:
            django_messages.info(request, "Sign in to accept the invitation.")
            return redirect("portal:login")
        try:
            invite_service.accept_invite(raw_token=token, user=request.user)
        except ValueError as e:
            django_messages.error(request, str(e))
            return redirect("portal:invite_accept", token=token)
        set_active_portal_account(request.session, inv.account)
        logger.info(
            "invite_accept_portal user_id=%s account_id=%s",
            request.user.pk,
            inv.account_id,
        )
        django_messages.success(request, f"You joined {inv.account.name}.")
        return redirect("portal:dashboard")

    # GET
    ctx = {
        "invite": inv,
        "page_title": "Accept invitation",
        "token": token,
        "email_match": (
            request.user.is_authenticated
            and (request.user.email or "").strip().lower() == inv.email
        ),
        "login_next": request.get_full_path(),
    }
    return render(request, "ui/customer/invite_accept.html", ctx)


@require_http_methods(["GET", "POST"])
def signup_via_invite(request, token: str):
    """Create a user account from an invite (no new org — joins existing account)."""
    inv = invite_service.get_pending_invite_by_raw_token(token)
    if not inv or inv.status != AccountInviteStatus.PENDING:
        return render(
            request,
            "ui/customer/invite_invalid.html",
            {"reason": "This invitation is not valid or has expired."},
            status=400,
        )
    if request.user.is_authenticated:
        return redirect("portal:invite_accept", token=token)

    if request.method == "POST":
        ip = (
            (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
            or request.META.get("REMOTE_ADDR")
            or "unknown"
        )
        if not allow_request(f"portal:signup_invite:ip:{ip}", limit=10, window_seconds=3600):
            django_messages.error(request, "Too many attempts from this network. Try again later.")
            form = InviteSignupForm(request.POST, invite_email=inv.email)
        else:
            form = InviteSignupForm(request.POST, invite_email=inv.email)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        user = User.objects.create_user(
                            username=inv.email,
                            email=inv.email,
                            password=form.cleaned_data["password1"],
                            first_name=form.cleaned_data["display_name"][:150],
                        )
                        ensure_user_profile(user)
                        invite_service.accept_invite(raw_token=token, user=user)
                except IntegrityError:
                    django_messages.error(
                        request,
                        "That email is already registered. Sign in, then open your invite link again.",
                    )
                    return render(
                        request,
                        "ui/customer/signup_invite.html",
                        {
                            "form": form,
                            "invite": inv,
                            "page_title": "Create account from invite",
                            "token": token,
                        },
                    )
                except ValueError as e:
                    django_messages.error(request, str(e))
                else:
                    try:
                        _tok, raw_v = create_verification_token(user)
                        send_email_verification_email(request=request, user=user, raw_token=raw_v)
                    except Exception as exc:
                        logger.warning("verification_email_skipped user_id=%s err=%s", user.pk, exc)
                    login(request, user)
                    set_active_portal_account(request.session, inv.account)
                    logger.info(
                        "signup_via_invite user_id=%s account_id=%s",
                        user.pk,
                        inv.account_id,
                    )
                    django_messages.success(request, "Welcome! Your account is ready.")
                    return redirect("portal:dashboard")
    else:
        form = InviteSignupForm(invite_email=inv.email)
    return render(
        request,
        "ui/customer/signup_invite.html",
        {"form": form, "invite": inv, "page_title": "Create account from invite", "token": token},
    )
