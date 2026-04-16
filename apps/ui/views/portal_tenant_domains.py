"""Customer portal: tenant sending domains, DNS instructions, verification."""

from __future__ import annotations

import logging

from django.contrib import messages as django_messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.policy import PolicyError
from apps.accounts.services.enforcement import assert_tenant_operational
from apps.tenants.models import DomainVerificationStatus, Tenant, TenantDomain
from apps.tenants.services.domain_dns_instructions import build_dns_instructions_for_domain
from apps.tenants.services.domain_dns_sync import sync_domain_dns_metadata
from apps.tenants.services.domain_verification import check_tenant_domain_dns
from apps.tenants.services.sending_readiness import compute_sending_readiness
from apps.ui.decorators import customer_login_required, portal_account_required, portal_manage_required
from apps.ui.forms_customer import PortalTenantDomainForm
from apps.ui.services.portal_account import get_active_portal_account
from apps.ui.services.portal_permissions import portal_user_can_manage_tenants
from apps.ui.views.customer_portal import _portal_ctx

logger = logging.getLogger("apps.tenants.audit")


def _tenant(request, tenant_id):
    account = get_active_portal_account(request)
    assert account is not None
    return get_object_or_404(Tenant, pk=tenant_id, account=account)


def _tenant_and_domain(request, tenant_id, domain_id):
    tenant = _tenant(request, tenant_id)
    td = get_object_or_404(TenantDomain.objects.select_related("tenant"), pk=domain_id, tenant=tenant)
    return tenant, td


def _redirect_if_tenant_suspended(request, tenant):
    try:
        assert_tenant_operational(tenant)
    except PolicyError as e:
        django_messages.error(request, e.detail)
        return redirect("portal:tenant_detail", tenant_id=tenant.id)
    return None


@customer_login_required
@portal_account_required
def tenant_domain_list(request, tenant_id):
    tenant = _tenant(request, tenant_id)
    account = get_active_portal_account(request)
    assert account is not None
    domains = tenant.domains.order_by("-is_primary", "domain")
    readiness = compute_sending_readiness(tenant)
    ctx = _portal_ctx(request, f"Domains — {tenant.name}", "tenants")
    ctx.update(
        {
            "tenant": tenant,
            "domains": domains,
            "readiness": readiness,
            "can_manage": portal_user_can_manage_tenants(request.user, account),
        }
    )
    return render(request, "ui/customer/tenant_domain_list.html", ctx)


@customer_login_required
@portal_manage_required
def tenant_domain_new(request, tenant_id):
    tenant = _tenant(request, tenant_id)
    if request.method == "POST":
        denied = _redirect_if_tenant_suspended(request, tenant)
        if denied is not None:
            return denied
        form = PortalTenantDomainForm(request.POST, tenant=tenant)
        if form.is_valid():
            d = form.cleaned_data["domain"]
            with transaction.atomic():
                is_first = not tenant.domains.exists()
                td = TenantDomain.objects.create(
                    tenant=tenant,
                    domain=d,
                    verification_status=DomainVerificationStatus.UNVERIFIED,
                )
                if sync_domain_dns_metadata(td, timeout=5.0):
                    td.save(
                        update_fields=[
                            "spf_txt_expected",
                            "dkim_selector",
                            "dkim_txt_value",
                            "return_path_cname_name",
                            "return_path_cname_target",
                            "dmarc_txt_expected",
                            "dns_source",
                            "dns_last_synced_at",
                            "updated_at",
                        ]
                    )
                if is_first and not (tenant.sending_domain or "").strip():
                    tenant.sending_domain = d
                    tenant.save(update_fields=["sending_domain", "updated_at"])
                if is_first:
                    td.is_primary = True
                    td.save(update_fields=["is_primary", "updated_at"])
            logger.info(
                "tenant_domain_created tenant_id=%s domain=%s user_id=%s",
                tenant.id,
                d,
                request.user.pk,
            )
            django_messages.success(request, f"Added domain {d}. Publish DNS records, then check verification.")
            return redirect("portal:tenant_domain_detail", tenant_id=tenant.id, domain_id=td.id)
    else:
        form = PortalTenantDomainForm(tenant=tenant)
    ctx = _portal_ctx(request, f"Add domain — {tenant.name}", "tenants")
    ctx.update({"tenant": tenant, "form": form})
    return render(request, "ui/customer/tenant_domain_form.html", ctx)


@customer_login_required
@portal_account_required
def tenant_domain_detail(request, tenant_id, domain_id):
    tenant, td = _tenant_and_domain(request, tenant_id, domain_id)
    account = get_active_portal_account(request)
    assert account is not None
    if sync_domain_dns_metadata(td, timeout=4.0):
        td.save(
            update_fields=[
                "spf_txt_expected",
                "dkim_selector",
                "dkim_txt_value",
                "return_path_cname_name",
                "return_path_cname_target",
                "dmarc_txt_expected",
                "dns_source",
                "dns_last_synced_at",
                "updated_at",
            ]
        )
    dns_instruction_set = build_dns_instructions_for_domain(td)
    # Always show rows we can derive (at least DMARC); gap notice explains missing SPF/DKIM.
    dns_rows = dns_instruction_set.rows
    readiness = compute_sending_readiness(tenant)
    ctx = _portal_ctx(request, td.domain, "tenants")
    ctx.update(
        {
            "tenant": tenant,
            "td": td,
            "dns_instruction_set": dns_instruction_set,
            "dns_rows": dns_rows,
            "readiness": readiness,
            "can_manage": portal_user_can_manage_tenants(request.user, account),
            "DomainVerificationStatus": DomainVerificationStatus,
        }
    )
    return render(request, "ui/customer/tenant_domain_detail.html", ctx)


@customer_login_required
@portal_manage_required
@require_POST
def tenant_domain_verify(request, tenant_id, domain_id):
    tenant, td = _tenant_and_domain(request, tenant_id, domain_id)
    denied = _redirect_if_tenant_suspended(request, tenant)
    if denied is not None:
        return denied
    check_tenant_domain_dns(td)
    td.save(
        update_fields=[
            "verified",
            "verification_status",
            "verification_notes",
            "spf_status",
            "dkim_status",
            "dmarc_status",
            "last_checked_at",
            "updated_at",
        ]
    )
    logger.info(
        "tenant_domain_verify tenant_id=%s domain_id=%s status=%s user_id=%s",
        tenant.id,
        td.id,
        td.verification_status,
        request.user.pk,
    )
    django_messages.info(request, f"Check complete: {td.get_verification_status_display()}.")
    return redirect("portal:tenant_domain_detail", tenant_id=tenant.id, domain_id=td.id)


@customer_login_required
@portal_manage_required
@require_POST
def tenant_domain_make_primary(request, tenant_id, domain_id):
    tenant, td = _tenant_and_domain(request, tenant_id, domain_id)
    denied = _redirect_if_tenant_suspended(request, tenant)
    if denied is not None:
        return denied
    if td.verification_status != DomainVerificationStatus.VERIFIED or not td.verified:
        django_messages.error(request, "Only verified domains can be set as primary.")
        return redirect("portal:tenant_domain_detail", tenant_id=tenant.id, domain_id=td.id)
    with transaction.atomic():
        TenantDomain.objects.filter(tenant=tenant).exclude(pk=td.pk).update(is_primary=False)
        td.is_primary = True
        td.save(update_fields=["is_primary", "updated_at"])
        tenant.sending_domain = td.domain
        tenant.save(update_fields=["sending_domain", "updated_at"])
    logger.info(
        "tenant_domain_primary tenant_id=%s domain_id=%s user_id=%s",
        tenant.id,
        td.id,
        request.user.pk,
    )
    django_messages.success(request, "Primary domain updated.")
    return redirect("portal:tenant_domain_list", tenant_id=tenant.id)


@customer_login_required
@portal_manage_required
@require_POST
def tenant_domain_delete(request, tenant_id, domain_id):
    tenant, td = _tenant_and_domain(request, tenant_id, domain_id)
    denied = _redirect_if_tenant_suspended(request, tenant)
    if denied is not None:
        return denied
    dom = td.domain
    with transaction.atomic():
        tid = tenant.id
        td.delete()
        tenant = Tenant.objects.select_for_update().get(pk=tid)
        qs = tenant.domains.all()
        if not qs.exists():
            tenant.sending_domain = ""
            tenant.save(update_fields=["sending_domain", "updated_at"])
        else:
            cand = (
                qs.filter(verification_status=DomainVerificationStatus.VERIFIED).first() or qs.order_by("domain").first()
            )
            qs.update(is_primary=False)
            cand.is_primary = True
            cand.save(update_fields=["is_primary", "updated_at"])
            tenant.sending_domain = cand.domain
            tenant.save(update_fields=["sending_domain", "updated_at"])
    logger.info(
        "tenant_domain_deleted tenant_id=%s domain=%s user_id=%s",
        tenant.id,
        dom,
        request.user.pk,
    )
    django_messages.success(request, f"Removed {dom}.")
    return redirect("portal:tenant_domain_list", tenant_id=tenant.id)
