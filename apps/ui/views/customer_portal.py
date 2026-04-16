"""Customer-facing portal: signup, login, account-scoped tenants and API keys."""

from __future__ import annotations

from django.contrib import messages as django_messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST

from apps.accounts.models import Account, AccountMembership, AccountRole, AccountStatus
from apps.messages.models import OutboundMessage
from apps.tenants.crypto import generate_api_key, hash_api_key
from apps.tenants.models import Tenant, TenantAPIKey
from apps.ui.decorators import customer_login_required, portal_account_required, portal_manage_required
from apps.ui.forms_customer import CustomerSignupForm, PortalApiKeyForm, PortalTenantForm
from apps.ui.services.portal_account import (
    clear_active_portal_account,
    get_active_portal_account,
    get_portal_accounts_for_user,
    set_active_portal_account,
)
from apps.ui.services.portal_permissions import portal_membership_role, portal_user_can_manage_tenants

SESSION_PORTAL_NEW_API_KEY = "_portal_new_api_key_once"


def _portal_ctx(request, page_title: str, nav_active: str):
    account = get_active_portal_account(request)
    role = portal_membership_role(request.user, account) if account else None
    can_manage = portal_user_can_manage_tenants(request.user, account) if account else False
    return {
        "page_title": page_title,
        "portal_nav_active": nav_active,
        "portal_account": account,
        "portal_role": role,
        "portal_can_manage": can_manage,
        "portal_accounts": get_portal_accounts_for_user(request.user),
    }


def signup(request):
    if request.user.is_authenticated:
        return redirect("portal:dashboard")
    if request.method == "POST":
        form = CustomerSignupForm(request.POST)
        if form.is_valid():
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
                account = Account.objects.create(
                    name=data["account_name"],
                    slug=data["account_slug"],
                    status=AccountStatus.ACTIVE,
                    billing_email=data["email"],
                )
                AccountMembership.objects.create(
                    account=account,
                    user=user,
                    role=AccountRole.OWNER,
                    is_active=True,
                )
            login(request, user)
            set_active_portal_account(request.session, account)
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
    account = get_active_portal_account(request)
    assert account is not None
    tenants = Tenant.objects.filter(account=account).annotate(
        api_key_count=Count("api_keys", filter=Q(api_keys__revoked_at__isnull=True)),
    )
    tenant_ids = list(tenants.values_list("id", flat=True))
    total_keys = (
        TenantAPIKey.objects.filter(tenant__account=account, revoked_at__isnull=True).count()
    )
    msg_count = OutboundMessage.objects.filter(tenant__account=account).count()
    ctx = _portal_ctx(request, "Dashboard", "dashboard")
    ctx.update(
        {
            "tenants": tenants,
            "tenant_count": tenants.count(),
            "total_api_keys": total_keys,
            "message_count": msg_count,
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
    ctx = _portal_ctx(request, "Apps & tenants", "tenants")
    ctx.update({"tenants": tenants})
    return render(request, "ui/customer/tenant_list.html", ctx)


@customer_login_required
@portal_manage_required
def tenant_new(request):
    account = get_active_portal_account(request)
    assert account is not None
    if request.method == "POST":
        form = PortalTenantForm(request.POST)
        if form.is_valid():
            tenant = form.save(commit=False)
            tenant.account = account
            tenant.save()
            django_messages.success(request, f"Created “{tenant.name}”.")
            return redirect("portal:tenant_detail", tenant_id=tenant.id)
    else:
        form = PortalTenantForm()
    ctx = _portal_ctx(request, "New app / tenant", "tenants")
    ctx.update({"form": form, "submit_label": "Create tenant"})
    return render(request, "ui/customer/tenant_form.html", ctx)


@customer_login_required
@portal_account_required
def tenant_detail(request, tenant_id):
    account = get_active_portal_account(request)
    assert account is not None
    tenant = get_object_or_404(
        Tenant.objects.prefetch_related("api_keys", "sender_profiles"),
        pk=tenant_id,
        account=account,
    )
    keys = tenant.api_keys.order_by("-created_at")[:50]
    new_key = request.session.pop(SESSION_PORTAL_NEW_API_KEY, None)
    can_manage = portal_user_can_manage_tenants(request.user, account)
    ctx = _portal_ctx(request, tenant.name, "tenants")
    ctx.update(
        {
            "tenant": tenant,
            "api_keys": keys,
            "new_api_key": new_key,
            "api_key_form": PortalApiKeyForm(),
            "can_manage": can_manage,
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
def placeholder(request, slug: str):
    titles = {
        "templates": "Templates",
        "workflows": "Workflows",
        "sender-profiles": "Sender profiles",
    }
    nav = {
        "templates": "templates",
        "workflows": "workflows",
        "sender-profiles": "sender_profiles",
    }
    title = titles.get(slug, "Coming soon")
    ctx = _portal_ctx(request, title, nav.get(slug, "dashboard"))
    ctx.update({"feature_title": title})
    return render(request, "ui/customer/placeholder.html", ctx)
