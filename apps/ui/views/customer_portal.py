"""Customer-facing portal: signup, login, account-scoped tenants and API keys."""

from __future__ import annotations

import logging

from django.contrib import messages as django_messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST

from apps.accounts.models import (
    Account,
    AccountInvite,
    AccountInviteStatus,
    AccountMembership,
    AccountRole,
    AccountStatus,
)
from apps.accounts.plans import DEFAULT_PLAN_CODE, get_effective_limits, plan_display_name
from apps.accounts.policy import PolicyError
from apps.accounts.services.enforcement import (
    assert_can_create_api_key,
    assert_can_create_tenant,
    assert_tenant_operational,
)
from apps.accounts.services.usage import usage_snapshot
from apps.accounts.services.email_verification import create_verification_token
from apps.accounts.services.invite_service import ensure_user_profile
from apps.messages.models import OutboundMessage
from apps.tenants.crypto import generate_api_key, hash_api_key
from apps.tenants.models import Tenant, TenantAPIKey, TenantStatus
from apps.tenants.services.sending_readiness import compute_sending_readiness
from apps.ui.decorators import customer_login_required, portal_account_required, portal_manage_required
from apps.ui.forms_customer import (
    CustomerSignupForm,
    PortalApiKeyForm,
    PortalTenantCreateForm,
    PortalTenantSettingsForm,
)
from apps.ui.services.portal_account import (
    clear_active_portal_account,
    get_active_portal_account,
    get_portal_accounts_for_user,
    set_active_portal_account,
)
from apps.email_templates.starter_pack import seed_customer_starter_templates
from apps.ui.services.portal_default_tenant import ensure_default_tenant_for_account
from apps.ui.services.portal_mail import send_email_verification_email
from apps.ui.services.rate_limit import allow_request
from apps.ui.services.portal_permissions import (
    portal_membership_role,
    portal_user_can_approve_templates,
    portal_user_can_edit_content,
    portal_user_can_manage_members,
    portal_user_can_manage_tenants,
    portal_user_is_viewer_only,
)

SESSION_PORTAL_NEW_API_KEY = "_portal_new_api_key_once"

logger = logging.getLogger("apps.accounts.audit")


def portal_nav_items() -> list[dict[str, str]]:
    """Sidebar nav for customer portal (label, url, name matches portal_nav_active)."""
    tenant_link = {
        "label": "Connected apps",
        "url": reverse("portal:tenant_list"),
        "name": "tenants",
    }
    return [
        {"label": "Dashboard", "url": reverse("portal:dashboard"), "name": "dashboard"},
        {"label": "Usage", "url": reverse("portal:account_usage"), "name": "usage"},
        {"label": "Billing", "url": reverse("portal:account_billing"), "name": "billing"},
        {"label": "Members", "url": reverse("portal:members_list"), "name": "members"},
        tenant_link,
        {"label": "API keys", "url": reverse("portal:api_keys"), "name": "api_keys"},
        {"label": "Sender profiles", "url": reverse("portal:sender_profile_list"), "name": "sender_profiles"},
        {"label": "Templates", "url": reverse("portal:template_list"), "name": "templates"},
        {"label": "Workflows", "url": reverse("portal:workflow_list"), "name": "workflows"},
        {"label": "Messages", "url": reverse("portal:messages_list"), "name": "messages"},
    ]


def _portal_ctx(request, page_title: str, nav_active: str):
    account = get_active_portal_account(request)
    role = portal_membership_role(request.user, account) if account else None
    can_manage = portal_user_can_manage_tenants(request.user, account) if account else False
    can_manage_members = portal_user_can_manage_members(request.user, account) if account else False
    can_edit = portal_user_can_edit_content(request.user, account) if account else False
    can_approve = portal_user_can_approve_templates(request.user, account) if account else False
    is_viewer = portal_user_is_viewer_only(request.user, account) if account else False
    plan_label = plan_display_name(account) if account else None
    effective_limits = get_effective_limits(account) if account else None
    usage = usage_snapshot(account) if account else None
    account_unhealthy = bool(account and account.status != AccountStatus.ACTIVE)
    tenant_count = 0
    if account:
        ensure_default_tenant_for_account(account)
        tenant_count = Tenant.objects.filter(account=account).count()
    usage_alerts: list[str] = []
    if account and effective_limits and usage and account.status == AccountStatus.ACTIVE:
        def _warn(label: str, current: int, limit: int) -> None:
            if limit <= 0:
                return
            if current >= limit:
                usage_alerts.append(f"{label} is at your plan limit ({current}/{limit}).")
            elif current >= max(1, int(limit * 0.8)):
                usage_alerts.append(f"{label} is approaching your plan limit ({current}/{limit}).")

        _warn("Monthly sends", usage.monthly_send_count, effective_limits.max_monthly_sends)
        _warn("Connected apps", usage.tenant_count, effective_limits.max_tenants)
        _warn("API keys", usage.active_api_key_count, effective_limits.max_active_api_keys)
        _warn("Templates", usage.template_count, effective_limits.max_templates)
        _warn("Workflows", usage.workflow_count, effective_limits.max_workflows)
        _warn("Members", usage.active_member_count, effective_limits.max_members)
    return {
        "page_title": page_title,
        "portal_nav_active": nav_active,
        "portal_account": account,
        "portal_role": role,
        "portal_can_manage": can_manage,
        "portal_can_manage_members": can_manage_members,
        "portal_can_edit": can_edit,
        "portal_can_approve": can_approve,
        "portal_is_viewer": is_viewer,
        "portal_accounts": get_portal_accounts_for_user(request.user),
        "portal_plan_label": plan_label,
        "portal_effective_limits": effective_limits,
        "portal_usage": usage,
        "portal_account_unhealthy": account_unhealthy,
        "portal_usage_alerts": usage_alerts,
        "portal_nav_items": portal_nav_items(),
        "portal_tenant_count": tenant_count,
    }


def signup(request):
    if request.user.is_authenticated:
        return redirect("portal:dashboard")
    if request.method == "POST":
        form = CustomerSignupForm(request.POST)
        ip = (
            (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
            or request.META.get("REMOTE_ADDR")
            or "unknown"
        )
        if not allow_request(f"portal:signup:ip:{ip}", limit=10, window_seconds=3600):
            django_messages.error(request, "Too many signup attempts from this network. Try again later.")
        elif form.is_valid():
            email = form.cleaned_data["email"]
            if not allow_request(f"portal:signup:email:{email}", limit=5, window_seconds=3600):
                django_messages.error(request, "Too many signup attempts for this email. Try again later.")
            else:
                from django.contrib.auth import get_user_model

                User = get_user_model()
                data = form.cleaned_data
                with transaction.atomic():
                    user = User.objects.create_user(
                        username=data["email"],
                        email=data["email"],
                        password=data["password1"],
                        first_name=data["display_name"][:150],
                    )
                    ensure_user_profile(user)
                    account = Account.objects.create(
                        name=data["account_name"],
                        slug=data["account_slug"],
                        status=AccountStatus.ACTIVE,
                        billing_email=data["email"],
                        plan_code=DEFAULT_PLAN_CODE,
                    )
                    AccountMembership.objects.create(
                        account=account,
                        user=user,
                        role=AccountRole.OWNER,
                        is_active=True,
                    )
                    ensure_default_tenant_for_account(account)
                login(request, user)
                set_active_portal_account(request.session, account)
                try:
                    _tok, raw_v = create_verification_token(user)
                    send_email_verification_email(request=request, user=user, raw_token=raw_v)
                except Exception as exc:
                    logger.warning("signup_verification_email_failed user_id=%s err=%s", user.pk, exc)
                logger.info(
                    "signup_completed user_id=%s account_id=%s slug=%s",
                    user.pk,
                    account.id,
                    account.slug,
                )
                django_messages.success(request, "Welcome! Your account is ready.")
                return redirect("portal:dashboard")
    else:
        form = CustomerSignupForm()
    return render(
        request,
        "ui/customer/signup.html",
        {"form": form, "page_title": "Create account"},
    )


class CustomerLoginView(LoginView):
    template_name = "ui/customer/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        """Used for already-authenticated redirect and post-login."""
        return reverse("portal:dashboard")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if "username" in form.fields:
            form.fields["username"].label = "Email"
            form.fields["username"].widget.attrs.setdefault("class", "w-full rounded-md border border-surface-600 bg-surface-800 px-3 py-2 text-sm text-white")
            form.fields["username"].widget.attrs.setdefault("autocomplete", "email")
        if "password" in form.fields:
            form.fields["password"].widget.attrs.setdefault("class", "w-full rounded-md border border-surface-600 bg-surface-800 px-3 py-2 text-sm text-white")
        return form


class CustomerLogoutView(LogoutView):
    next_page = reverse_lazy("portal:login")

    def dispatch(self, request, *args, **kwargs):
        clear_active_portal_account(request.session)
        return super().dispatch(request, *args, **kwargs)


@customer_login_required
@portal_account_required
def dashboard(request):
    from apps.ui.services.portal_dashboard_data import build_portal_dashboard_context

    account = get_active_portal_account(request)
    assert account is not None
    ensure_default_tenant_for_account(account)
    tenant_count = Tenant.objects.filter(account=account).count()
    pending_invite_count = AccountInvite.objects.filter(
        account=account, status=AccountInviteStatus.PENDING
    ).count()
    ctx = _portal_ctx(request, "Dashboard", "dashboard")
    ctx.update(build_portal_dashboard_context(account))
    ctx.update(
        {
            "tenant_count": tenant_count,
            "pending_invite_count": pending_invite_count,
        }
    )
    return render(request, "ui/customer/dashboard.html", ctx)


@customer_login_required
@portal_account_required
def switch_account(request):
    if request.method != "POST":
        return redirect("portal:dashboard")
    aid = request.POST.get("account_id")
    if not aid:
        return redirect("portal:dashboard")
    accounts = {str(a.id): a for a in get_portal_accounts_for_user(request.user)}
    if aid in accounts:
        set_active_portal_account(request.session, accounts[aid])
        django_messages.info(request, f"Switched to {accounts[aid].name}.")
    return redirect("portal:dashboard")


@customer_login_required
@portal_account_required
def tenant_list(request):
    account = get_active_portal_account(request)
    assert account is not None
    tenants = Tenant.objects.filter(account=account).order_by("name")
    ctx = _portal_ctx(request, "Connected apps", "tenants")
    ctx.update({"tenants": tenants})
    return render(request, "ui/customer/tenant_list.html", ctx)


@customer_login_required
@portal_manage_required
def tenant_new(request):
    account = get_active_portal_account(request)
    assert account is not None
    if request.method == "GET":
        try:
            assert_can_create_tenant(account)
        except PolicyError as e:
            django_messages.error(request, e.detail)
            return redirect("portal:tenant_list")
    if request.method == "POST":
        form = PortalTenantCreateForm(request.POST)
        if form.is_valid():
            try:
                assert_can_create_tenant(account)
            except PolicyError as e:
                django_messages.error(request, e.detail)
            else:
                tenant = form.save(commit=False)
                tenant.account = account
                tenant.save()
                seed_customer_starter_templates(tenant)
                django_messages.success(request, f"Created “{tenant.name}”.")
                return redirect("portal:tenant_detail", tenant_id=tenant.id)
    else:
        form = PortalTenantCreateForm()
    ctx = _portal_ctx(request, "New connected app", "tenants")
    ctx.update({"form": form, "submit_label": "Create connected app"})
    return render(request, "ui/customer/tenant_form.html", ctx)


@customer_login_required
@portal_account_required
def tenant_detail(request, tenant_id):
    account = get_active_portal_account(request)
    assert account is not None
    tenant = get_object_or_404(
        Tenant.objects.prefetch_related("api_keys", "sender_profiles", "domains"),
        pk=tenant_id,
        account=account,
    )
    can_manage = portal_user_can_manage_tenants(request.user, account)
    settings_form = PortalTenantSettingsForm(instance=tenant)
    if request.method == "POST" and request.POST.get("save_app_settings"):
        if not can_manage:
            django_messages.error(request, "You do not have permission to change connected app settings.")
            return redirect("portal:tenant_detail", tenant_id=tenant.id)
        settings_form = PortalTenantSettingsForm(request.POST, instance=tenant)
        if settings_form.is_valid():
            settings_form.save()
            django_messages.success(request, "Connected app settings saved.")
            return redirect("portal:tenant_detail", tenant_id=tenant.id)
        django_messages.error(request, "Fix the errors below and try again.")
    keys = tenant.api_keys.order_by("-created_at")[:50]
    new_key = request.session.pop(SESSION_PORTAL_NEW_API_KEY, None)
    readiness = compute_sending_readiness(tenant)
    ctx = _portal_ctx(request, tenant.name, "tenants")
    ctx.update(
        {
            "tenant": tenant,
            "api_keys": keys,
            "new_api_key": new_key,
            "api_key_form": PortalApiKeyForm(),
            "settings_form": settings_form,
            "can_manage": can_manage,
            "readiness": readiness,
            "tenant_suspended": tenant.status != TenantStatus.ACTIVE,
        }
    )
    return render(request, "ui/customer/tenant_detail.html", ctx)


@customer_login_required
@portal_manage_required
@require_POST
def tenant_create_api_key(request, tenant_id):
    account = get_active_portal_account(request)
    assert account is not None
    tenant = get_object_or_404(Tenant, pk=tenant_id, account=account)
    try:
        assert_can_create_api_key(account)
        assert_tenant_operational(tenant)
    except PolicyError as e:
        django_messages.error(request, e.detail)
        return redirect("portal:tenant_detail", tenant_id=tenant.id)
    form = PortalApiKeyForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Invalid label.")
        return redirect("portal:tenant_detail", tenant_id=tenant.id)
    raw = generate_api_key()
    TenantAPIKey.objects.create(
        tenant=tenant,
        name=form.cleaned_data["name"],
        key_hash=hash_api_key(raw),
    )
    request.session[SESSION_PORTAL_NEW_API_KEY] = raw
    django_messages.warning(request, "API key created. Copy it now — it will not be shown again.")
    return redirect("portal:tenant_detail", tenant_id=tenant.id)


@customer_login_required
@portal_account_required
def api_keys_hub(request):
    account = get_active_portal_account(request)
    ensure_default_tenant_for_account(account)
    tenants = (
        Tenant.objects.filter(account=account)
        .annotate(active_key_count=Count("api_keys", filter=Q(api_keys__revoked_at__isnull=True)))
        .order_by("name")
    )
    ctx = _portal_ctx(request, "API keys", "api_keys")
    ctx.update({"tenants": tenants})
    return render(request, "ui/customer/api_keys_hub.html", ctx)


@customer_login_required
@portal_account_required
def messages_list(request):
    account = get_active_portal_account(request)
    qs = (
        OutboundMessage.objects.filter(tenant__account=account)
        .select_related("tenant")
        .order_by("-created_at")[:100]
    )
    ctx = _portal_ctx(request, "Messages", "messages")
    ctx.update({"messages": qs})
    return render(request, "ui/customer/messages_list.html", ctx)


@customer_login_required
@portal_account_required
def account_usage(request):
    account = get_active_portal_account(request)
    assert account is not None
    ctx = _portal_ctx(request, "Usage & plan", "usage")
    return render(request, "ui/customer/account_usage.html", ctx)


@customer_login_required
@portal_account_required
def account_billing(request):
    account = get_active_portal_account(request)
    assert account is not None
    ctx = _portal_ctx(request, "Billing", "billing")
    ctx.update({"billing_email": account.billing_email})
    return render(request, "ui/customer/account_billing.html", ctx)
