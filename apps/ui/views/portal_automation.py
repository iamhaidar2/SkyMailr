"""Customer portal: sender profiles, templates, workflows (account-scoped)."""

from __future__ import annotations

import difflib
import json

from django.contrib import messages as django_messages
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.policy import PolicyError
from apps.accounts.services.enforcement import (
    assert_can_create_template,
    assert_can_create_workflow,
    assert_tenant_operational,
)
from apps.email_templates.models import (
    ApprovalStatus,
    CreatedByType,
    EmailTemplate,
    EmailTemplateVersion,
    TemplateRenderLog,
    TemplateStatus,
    VersionSourceType,
)
from apps.email_templates.services.llm_service import TemplateLLMService
from apps.email_templates.services.render_service import TemplateRenderError, render_email_version
from apps.email_templates.services.validation_service import TemplateValidationService
from apps.email_templates.services.version_actions import approve_latest_version
from apps.tenants.models import DomainVerificationStatus, SenderProfile, Tenant
from apps.tenants.services.domain_verification import email_domain_matches_verified_tenant_domain
from apps.ui.decorators import (
    customer_login_required,
    portal_account_required,
    portal_approve_required,
    portal_editor_required,
)
from apps.ui.forms import TemplateApproveForm, TemplatePreviewForm, TemplateReviseForm, WorkflowEnrollForm
from apps.ui.forms_customer import (
    PortalNewEmailTemplateForm,
    PortalSenderProfileForm,
    PortalTemplateVersionForm,
    PortalWorkflowStepForm,
)
from apps.ui.forms import WorkflowCreateForm
from apps.ui.views.customer_portal import _portal_ctx
from apps.ui.services.portal_account import get_active_portal_account
from apps.ui.services.portal_permissions import (
    portal_user_can_approve_templates,
    portal_user_can_edit_content,
)
from apps.workflows.models import Workflow, WorkflowEnrollment, WorkflowExecution, WorkflowStep, WorkflowStepType
from apps.workflows.services.workflow_engine import enroll_workflow


def _account(request):
    return get_active_portal_account(request)


# --- Sender profiles ---


@customer_login_required
@portal_account_required
def sender_profile_list(request):
    account = _account(request)
    assert account is not None
    qs = SenderProfile.objects.filter(tenant__account=account).select_related("tenant").order_by(
        "tenant__name", "category", "name"
    )
    tid = (request.GET.get("tenant") or "").strip()
    if tid:
        qs = qs.filter(tenant_id=tid)
    ctx = _portal_ctx(request, "Sender profiles", "sender_profiles")
    ctx.update(
        {
            "profiles": qs,
            "filter_tenant_id": tid,
            "tenants": Tenant.objects.filter(account=account).order_by("name"),
        }
    )
    return render(request, "ui/customer/sender_profile_list.html", ctx)


@customer_login_required
@portal_editor_required
def sender_profile_new(request):
    account = _account(request)
    assert account is not None
    if request.method == "POST":
        form = PortalSenderProfileForm(request.POST, account=account)
        if form.is_valid():
            form.save()
            django_messages.success(request, "Sender profile saved.")
            return redirect("portal:sender_profile_detail", profile_id=form.instance.id)
    else:
        form = PortalSenderProfileForm(account=account)
    ctx = _portal_ctx(request, "New sender profile", "sender_profiles")
    ctx.update({"form": form, "submit_label": "Create profile", "editing": False})
    return render(request, "ui/customer/sender_profile_form.html", ctx)


@customer_login_required
@portal_account_required
def sender_profile_detail(request, profile_id):
    account = _account(request)
    profile = get_object_or_404(
        SenderProfile.objects.select_related("tenant"),
        pk=profile_id,
        tenant__account=account,
    )
    sd = (profile.tenant.sending_domain or "").strip()
    mismatch_sd = bool(
        sd and profile.from_email and profile.from_email.split("@")[-1].lower() != sd.lower()
    )
    has_verified_domain = profile.tenant.domains.filter(
        verified=True,
        verification_status=DomainVerificationStatus.VERIFIED,
    ).exists()
    verified_from_ok = email_domain_matches_verified_tenant_domain(profile.tenant, profile.from_email)
    ctx = _portal_ctx(request, profile.name, "sender_profiles")
    ctx.update(
        {
            "profile": profile,
            "sending_domain_missing": not sd,
            "domain_mismatch_tenant_sending_domain": mismatch_sd,
            "has_verified_domain": has_verified_domain,
            "from_email_matches_verified_domain": verified_from_ok,
            "can_edit": portal_user_can_edit_content(request.user, account),
        }
    )
    return render(request, "ui/customer/sender_profile_detail.html", ctx)


@customer_login_required
@portal_editor_required
def sender_profile_edit(request, profile_id):
    account = _account(request)
    profile = get_object_or_404(SenderProfile, pk=profile_id, tenant__account=account)
    if request.method == "POST":
        form = PortalSenderProfileForm(request.POST, account=account, instance=profile)
        if form.is_valid():
            form.save()
            django_messages.success(request, "Sender profile updated.")
            return redirect("portal:sender_profile_detail", profile_id=profile.id)
    else:
        form = PortalSenderProfileForm(account=account, instance=profile)
    ctx = _portal_ctx(request, f"Edit {profile.name}", "sender_profiles")
    ctx.update({"form": form, "profile": profile, "submit_label": "Save changes", "editing": True})
    return render(request, "ui/customer/sender_profile_form.html", ctx)


@customer_login_required
@portal_editor_required
def sender_profile_delete(request, profile_id):
    account = _account(request)
    profile = get_object_or_404(SenderProfile, pk=profile_id, tenant__account=account)
    if request.method == "POST":
        name = profile.name
        profile.delete()
        django_messages.success(request, f"Deleted “{name}”.")
        return redirect("portal:sender_profile_list")
    ctx = _portal_ctx(request, f"Delete {profile.name}", "sender_profiles")
    ctx.update({"profile": profile})
    return render(request, "ui/customer/sender_profile_confirm_delete.html", ctx)


# --- Templates ---


@customer_login_required
@portal_account_required
def template_list(request):
    account = _account(request)
    qs = EmailTemplate.objects.filter(tenant__account=account).select_related("tenant")
    tid = (request.GET.get("tenant") or "").strip()
    if tid:
        qs = qs.filter(tenant_id=tid)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(key__icontains=q) | Q(name__icontains=q))
    ctx = _portal_ctx(request, "Email templates", "templates")
    ctx.update(
        {
            "templates": qs.order_by("tenant__name", "key")[:500],
            "filter_tenant_id": tid,
            "filter_q": q,
            "tenants": Tenant.objects.filter(account=account).order_by("name"),
            "can_edit": portal_user_can_edit_content(request.user, account),
        }
    )
    return render(request, "ui/customer/template_list.html", ctx)


@customer_login_required
@portal_editor_required
def template_new(request):
    account = _account(request)
    if request.method == "POST":
        form = PortalNewEmailTemplateForm(request.POST, account=account)
        if form.is_valid():
            d = form.cleaned_data
            try:
                assert_can_create_template(account)
                assert_tenant_operational(d["tenant"])
            except PolicyError as e:
                django_messages.error(request, e.detail)
            else:
                tpl = EmailTemplate.objects.create(
                    tenant=d["tenant"],
                    key=d["key"],
                    name=d["name"],
                    category=d["category"],
                    description=d.get("description") or "",
                    status=TemplateStatus.DRAFT,
                )
                django_messages.success(request, "Template created. Add a version next.")
                return redirect("portal:template_detail", template_id=tpl.id)
    else:
        form = PortalNewEmailTemplateForm(account=account)
    ctx = _portal_ctx(request, "New template", "templates")
    ctx.update({"form": form, "submit_label": "Create template"})
    return render(request, "ui/customer/template_new.html", ctx)


@customer_login_required
@portal_account_required
def template_detail(request, template_id):
    account = _account(request)
    tpl = get_object_or_404(
        EmailTemplate.objects.select_related("tenant").prefetch_related("variables", "versions"),
        pk=template_id,
        tenant__account=account,
    )
    versions = tpl.versions.order_by("-version_number")
    vers_list = list(versions[:8])
    approved_version = tpl.current_approved_version
    latest_version = vers_list[0] if vers_list else None
    diff_subject = diff_text = diff_html = ""
    if len(vers_list) >= 2:
        a, b = vers_list[1], vers_list[0]
        diff_subject = "\n".join(
            difflib.unified_diff(
                (a.subject_template or "").splitlines(),
                (b.subject_template or "").splitlines(),
                lineterm="",
            )
        )
        diff_text = "\n".join(
            difflib.unified_diff(
                (a.text_template or "").splitlines(),
                (b.text_template or "").splitlines(),
                lineterm="",
            )
        )
        diff_html = "\n".join(
            difflib.unified_diff(
                (a.html_template or "").splitlines(),
                (b.html_template or "").splitlines(),
                lineterm="",
            )
        )
    version_form = PortalTemplateVersionForm()
    preview_form = TemplatePreviewForm()
    revise_form = TemplateReviseForm()
    approve_form = TemplateApproveForm()
    can_edit = portal_user_can_edit_content(request.user, account)
    can_approve = portal_user_can_approve_templates(request.user, account)
    ctx = _portal_ctx(request, tpl.name, "templates")
    ctx.update(
        {
            "template": tpl,
            "versions": versions,
            "approved_version": approved_version,
            "latest_version": latest_version,
            "diff_subject": diff_subject,
            "diff_text": diff_text,
            "diff_html": diff_html,
            "version_form": version_form,
            "preview_form": preview_form,
            "revise_form": revise_form,
            "approve_form": approve_form,
            "can_edit": can_edit,
            "can_approve": can_approve,
        }
    )
    return render(request, "ui/customer/template_detail.html", ctx)


@customer_login_required
@portal_editor_required
@require_POST
def template_version_create(request, template_id):
    account = _account(request)
    tpl = get_object_or_404(EmailTemplate, pk=template_id, tenant__account=account)
    form = PortalTemplateVersionForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Fix version fields.")
        return redirect("portal:template_detail", template_id=tpl.id)
    d = form.cleaned_data
    max_v = tpl.versions.aggregate(m=Max("version_number")).get("m") or 0
    EmailTemplateVersion.objects.create(
        template=tpl,
        version_number=max_v + 1,
        created_by_type=CreatedByType.USER,
        source_type=VersionSourceType.MANUAL,
        subject_template=d["subject_template"],
        preview_text_template=d.get("preview_text_template") or "",
        html_template=d["html_template"],
        text_template=d.get("text_template") or "",
        approval_status=ApprovalStatus.PENDING,
    )
    django_messages.success(request, f"Created version {max_v + 1}.")
    return redirect("portal:template_detail", template_id=tpl.id)


@customer_login_required
@portal_editor_required
@require_POST
def template_preview(request, template_id):
    account = _account(request)
    tpl = get_object_or_404(EmailTemplate, pk=template_id, tenant__account=account)
    form = TemplatePreviewForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Invalid preview context.")
        return redirect("portal:template_detail", template_id=tpl.id)
    ver = tpl.versions.order_by("-version_number").first()
    if not ver:
        django_messages.error(request, "No version to preview.")
        return redirect("portal:template_detail", template_id=tpl.id)
    ctx_data = form.cleaned_data.get("context") or {}
    try:
        TemplateValidationService.validate_context(tpl, ctx_data)
        out = render_email_version(
            subject_template=ver.subject_template,
            preview_template=ver.preview_text_template,
            html_template=ver.html_template,
            text_template=ver.text_template,
            context=ctx_data,
            sanitize=True,
        )
    except (TemplateRenderError, ValueError) as e:
        django_messages.error(request, str(e))
        return redirect("portal:template_detail", template_id=tpl.id)
    TemplateRenderLog.objects.create(
        template_version=ver,
        context_snapshot=ctx_data,
        subject_rendered=out["subject"],
        html_rendered=out["html"],
        text_rendered=out["text"],
        success=True,
    )
    ctx = _portal_ctx(request, f"Preview — {tpl.name}", "templates")
    ctx.update(
        {
            "template": tpl,
            "rendered": out,
            "context_used": ctx_data,
            "context_json": json.dumps(ctx_data, indent=2, default=str),
        }
    )
    return render(request, "ui/customer/template_preview_result.html", ctx)


@customer_login_required
@portal_approve_required
@require_POST
def template_approve(request, template_id):
    account = _account(request)
    tpl = get_object_or_404(EmailTemplate, pk=template_id, tenant__account=account)
    try:
        approve_latest_version(template=tpl)
        django_messages.success(request, "Latest version approved.")
    except ValueError as e:
        django_messages.error(request, str(e))
    return redirect("portal:template_detail", template_id=tpl.id)


@customer_login_required
@portal_editor_required
@require_POST
def template_revise(request, template_id):
    account = _account(request)
    tpl = get_object_or_404(EmailTemplate, pk=template_id, tenant__account=account)
    form = TemplateReviseForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Invalid revise form.")
        return redirect("portal:template_detail", template_id=tpl.id)
    ver = tpl.versions.order_by("-version_number").first()
    if not ver:
        django_messages.error(request, "No version to revise.")
        return redirect("portal:template_detail", template_id=tpl.id)
    try:
        TemplateLLMService().revise_template_version(
            template=tpl,
            base_version=ver,
            instructions=form.cleaned_data["instructions"],
        )
        django_messages.success(request, "New draft version created via LLM.")
    except Exception as e:
        django_messages.error(request, str(e))
    return redirect("portal:template_detail", template_id=tpl.id)


# --- Workflows ---


@customer_login_required
@portal_account_required
def workflow_list(request):
    account = _account(request)
    qs = (
        Workflow.objects.filter(tenant__account=account)
        .select_related("tenant")
        .annotate(
            step_count=Count("steps", distinct=True),
            enrollment_count=Count("enrollments", distinct=True),
        )
        .order_by("tenant__name", "slug")
    )
    tid = (request.GET.get("tenant") or "").strip()
    if tid:
        qs = qs.filter(tenant_id=tid)
    ctx = _portal_ctx(request, "Workflows", "workflows")
    ctx.update(
        {
            "workflows": qs[:500],
            "filter_tenant_id": tid,
            "tenants": Tenant.objects.filter(account=account).order_by("name"),
            "can_edit": portal_user_can_edit_content(request.user, account),
        }
    )
    return render(request, "ui/customer/workflow_list.html", ctx)


@customer_login_required
@portal_editor_required
def workflow_new(request):
    account = _account(request)
    tenants = Tenant.objects.filter(account=account).order_by("name")
    if request.method == "POST":
        form = WorkflowCreateForm(request.POST)
        tenant_id = (request.POST.get("tenant") or "").strip()
        tenant = get_object_or_404(Tenant, pk=tenant_id, account=account)
        if form.is_valid():
            d = form.cleaned_data
            existing = Workflow.objects.filter(tenant=tenant, slug=d["slug"]).first()
            if existing is not None:
                django_messages.info(request, "Workflow already exists — opening it.")
                return redirect("portal:workflow_detail", workflow_id=existing.id)
            try:
                assert_can_create_workflow(account)
                assert_tenant_operational(tenant)
            except PolicyError as e:
                django_messages.error(request, e.detail)
            else:
                wf = Workflow.objects.create(
                    tenant=tenant,
                    slug=d["slug"],
                    name=d["name"],
                )
                django_messages.success(request, "Workflow created.")
                return redirect("portal:workflow_detail", workflow_id=wf.id)
        django_messages.error(request, "Invalid workflow.")
    else:
        form = WorkflowCreateForm()
    ctx = _portal_ctx(request, "New workflow", "workflows")
    ctx.update({"form": form, "tenants": tenants})
    return render(request, "ui/customer/workflow_new.html", ctx)


@customer_login_required
@portal_account_required
def workflow_detail(request, workflow_id):
    account = _account(request)
    wf = get_object_or_404(
        Workflow.objects.select_related("tenant").prefetch_related("steps"),
        pk=workflow_id,
        tenant__account=account,
    )
    steps = wf.steps.order_by("order")
    max_order = steps.aggregate(m=Max("order")).get("m") or 0
    enrollments = wf.enrollments.select_related("tenant").order_by("-created_at")[:50]
    executions = (
        WorkflowExecution.objects.filter(enrollment__workflow=wf)
        .select_related("enrollment")
        .order_by("-started_at")[:50]
    )
    enroll_form = WorkflowEnrollForm()
    step_form = PortalWorkflowStepForm(initial={"order": max_order + 1})
    tenant_tpl_keys = list(
        EmailTemplate.objects.filter(tenant=wf.tenant).values_list("key", flat=True)
    )
    can_edit = portal_user_can_edit_content(request.user, account)
    ctx = _portal_ctx(request, wf.name, "workflows")
    ctx.update(
        {
            "workflow": wf,
            "steps": steps,
            "enrollments": enrollments,
            "executions": executions,
            "enroll_form": enroll_form,
            "step_form": step_form,
            "tenant_template_keys": tenant_tpl_keys,
            "can_edit": can_edit,
        }
    )
    return render(request, "ui/customer/workflow_detail.html", ctx)


@customer_login_required
@portal_editor_required
@require_POST
def workflow_enroll(request, workflow_id):
    account = _account(request)
    wf = get_object_or_404(Workflow, pk=workflow_id, tenant__account=account)
    form = WorkflowEnrollForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Invalid enrollment.")
        return redirect("portal:workflow_detail", workflow_id=wf.id)
    d = form.cleaned_data
    en = WorkflowEnrollment.objects.create(
        tenant=wf.tenant,
        workflow=wf,
        recipient_email=d["recipient_email"],
        recipient_name=d.get("recipient_name") or "",
        external_user_id=d.get("external_user_id") or "",
        metadata=d.get("metadata") or {},
    )
    try:
        enroll_workflow(enrollment=en)
        django_messages.success(request, "Enrolled and execution started.")
    except ValueError as e:
        django_messages.error(request, str(e))
    return redirect("portal:workflow_detail", workflow_id=wf.id)


@customer_login_required
@portal_editor_required
@require_POST
def workflow_add_step(request, workflow_id):
    account = _account(request)
    wf = get_object_or_404(Workflow, pk=workflow_id, tenant__account=account)
    form = PortalWorkflowStepForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Invalid step.")
        return redirect("portal:workflow_detail", workflow_id=wf.id)
    d = form.cleaned_data
    st = d["step_type"]
    tpl = None
    tkey = (d.get("template_key") or "").strip()
    if st == WorkflowStepType.SEND_TEMPLATE and tkey:
        tpl = EmailTemplate.objects.filter(tenant=wf.tenant, key=tkey).first()
        if not tpl:
            django_messages.error(request, "Template key not found for this tenant.")
            return redirect("portal:workflow_detail", workflow_id=wf.id)
    wait_seconds = d.get("wait_seconds")
    if st == WorkflowStepType.WAIT_DURATION:
        wait_seconds = wait_seconds if wait_seconds is not None else 0
    else:
        wait_seconds = None
    WorkflowStep.objects.create(
        workflow=wf,
        order=d["order"],
        step_type=st,
        template=tpl,
        template_key=tkey if not tpl else "",
        wait_seconds=wait_seconds,
    )
    django_messages.success(request, "Step added.")
    return redirect("portal:workflow_detail", workflow_id=wf.id)
