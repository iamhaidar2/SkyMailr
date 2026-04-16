"""Customer portal: members, invites, membership edit."""

from __future__ import annotations

import logging

from django.contrib import messages as django_messages
from django.contrib.auth import get_user_model
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import (
    AccountInvite,
    AccountInviteStatus,
    AccountMembership,
    AccountRole,
)
from apps.accounts.services import invite_service
from apps.accounts.services.membership_policy import (
    actor_role,
    admin_may_touch_target,
    may_assign_role,
    would_remove_last_owner,
)
from apps.ui.decorators import customer_login_required, portal_account_required, portal_manage_required
from apps.ui.forms_customer import PortalInviteForm, PortalMembershipEditForm
from apps.ui.services.portal_account import get_active_portal_account, set_active_portal_account
from apps.ui.services.portal_mail import send_account_invite_email
from apps.ui.views.customer_portal import _portal_ctx

User = get_user_model()
logger = logging.getLogger("apps.accounts.audit")


def _account(request):
    return get_active_portal_account(request)


def _membership_for_actor(request, account, membership_id):
    m = get_object_or_404(
        AccountMembership.objects.select_related("user", "account"),
        pk=membership_id,
        account=account,
    )
    ar = actor_role(request.user, account)
    if ar not in (AccountRole.OWNER, AccountRole.ADMIN):
        return None, m
    if not admin_may_touch_target(ar, m):
        return False, m
    return True, m


@customer_login_required
@portal_account_required
def members_list(request):
    account = _account(request)
    assert account is not None
    memberships = (
        AccountMembership.objects.filter(account=account)
        .select_related("user")
        .order_by("user__email")
    )
    invites = (
        AccountInvite.objects.filter(account=account)
        .filter(status=AccountInviteStatus.PENDING)
        .select_related("invited_by")
        .order_by("-created_at")
    )
    ctx = _portal_ctx(request, "Members", "members")
    ctx.update(
        {
            "memberships": memberships,
            "pending_invites": invites,
        }
    )
    return render(request, "ui/customer/members_list.html", ctx)


@customer_login_required
@portal_manage_required
def members_invite(request):
    account = _account(request)
    assert account is not None
    ar = actor_role(request.user, account)
    if request.method == "POST":
        form = PortalInviteForm(request.POST, inviter_role=ar or "")
        if form.is_valid():
            try:
                inv, raw = invite_service.create_invite(
                    account=account,
                    email=form.cleaned_data["email"],
                    role=form.cleaned_data["role"],
                    invited_by=request.user,
                )
                try:
                    send_account_invite_email(request=request, invite=inv, raw_token=raw)
                    django_messages.success(request, f"Invitation sent to {inv.email}.")
                except Exception as exc:
                    logger.exception("invite_email_failed invite_id=%s", inv.id)
                    django_messages.warning(
                        request,
                        f"Invite created but email could not be sent ({exc}). Share the link manually or resend.",
                    )
                return redirect("portal:members_list")
            except ValueError as e:
                django_messages.error(request, str(e))
    else:
        form = PortalInviteForm(inviter_role=ar or "")
    ctx = _portal_ctx(request, "Invite member", "members")
    ctx.update({"form": form})
    return render(request, "ui/customer/members_invite.html", ctx)


@customer_login_required
@portal_manage_required
def member_edit(request, membership_id):
    account = _account(request)
    assert account is not None
    ok, m = _membership_for_actor(request, account, membership_id)
    if ok is None:
        return HttpResponseForbidden("You do not have permission to manage members.")
    if ok is False:
        return HttpResponseForbidden("Admins cannot change owner memberships.")

    ar = actor_role(request.user, account)
    if request.method == "POST":
        form = PortalMembershipEditForm(
            request.POST,
            instance=m,
            actor_role=ar or "",
        )
        if form.is_valid():
            new_role = form.cleaned_data["role"]
            active = form.cleaned_data["is_active"]
            if not may_assign_role(ar or "", new_role):
                django_messages.error(request, "You cannot assign that role.")
            elif not active and would_remove_last_owner(
                account=account, target=m, deactivate=True
            ):
                django_messages.error(
                    request,
                    "Cannot deactivate the only active owner for this account.",
                )
            elif active and new_role != m.role and would_remove_last_owner(
                account=account, target=m, new_role=new_role
            ):
                django_messages.error(
                    request,
                    "Cannot remove the last owner — promote another owner first.",
                )
            else:
                m.role = new_role
                m.is_active = active
                m.save(update_fields=["role", "is_active", "updated_at"])
                logger.info(
                    "membership_updated account_id=%s membership_id=%s role=%s active=%s by=%s",
                    account.id,
                    m.id,
                    m.role,
                    m.is_active,
                    request.user.pk,
                )
                django_messages.success(request, "Membership updated.")
                return redirect("portal:members_list")
    else:
        form = PortalMembershipEditForm(
            instance=m,
            actor_role=ar or "",
        )
    ctx = _portal_ctx(request, f"Edit {m.user.email}", "members")
    ctx.update({"form": form, "membership": m})
    return render(request, "ui/customer/member_edit.html", ctx)


@customer_login_required
@portal_manage_required
@require_POST
def member_deactivate(request, membership_id):
    account = _account(request)
    assert account is not None
    ok, m = _membership_for_actor(request, account, membership_id)
    if ok is None:
        return HttpResponseForbidden("You do not have permission.")
    if ok is False:
        return HttpResponseForbidden("Admins cannot deactivate owners.")
    if m.user_id == request.user.id:
        django_messages.error(request, "Use leave-account flow (coming soon) or ask another owner.")
        return redirect("portal:members_list")
    if would_remove_last_owner(account=account, target=m, deactivate=True):
        django_messages.error(request, "Cannot deactivate the only active owner.")
        return redirect("portal:members_list")
    m.is_active = False
    m.save(update_fields=["is_active", "updated_at"])
    logger.info(
        "membership_deactivated account_id=%s membership_id=%s by=%s",
        account.id,
        m.id,
        request.user.pk,
    )
    django_messages.success(request, "Member deactivated.")
    return redirect("portal:members_list")


@customer_login_required
@portal_manage_required
@require_POST
def invite_cancel(request, invite_id):
    account = _account(request)
    assert account is not None
    inv = get_object_or_404(AccountInvite, pk=invite_id, account=account)
    try:
        invite_service.cancel_invite(invite=inv)
        django_messages.success(request, "Invite cancelled.")
    except ValueError as e:
        django_messages.error(request, str(e))
    return redirect("portal:members_list")


@customer_login_required
@portal_manage_required
@require_POST
def invite_resend(request, invite_id):
    account = _account(request)
    assert account is not None
    inv = get_object_or_404(AccountInvite, pk=invite_id, account=account)
    try:
        raw = invite_service.resend_invite(invite=inv)
        try:
            send_account_invite_email(request=request, invite=inv, raw_token=raw)
            django_messages.success(request, "Invitation resent.")
        except Exception as exc:
            logger.exception("invite_resend_email_failed invite_id=%s", inv.id)
            django_messages.warning(request, f"Token refreshed but email failed: {exc}")
    except ValueError as e:
        django_messages.error(request, str(e))
    return redirect("portal:members_list")
