import difflib
import json

from django.contrib import messages as django_messages
from django.db.models import Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.email_templates.models import (
    ApprovalStatus,
    CreatedByType,
    EmailTemplate,
    EmailTemplateVersion,
    TemplateRenderLog,
    TemplateStatus,
    VersionSourceType,
)
from apps.email_templates.services.html_plain_sync import reconcile_template_bodies
from apps.email_templates.services.llm_service import TemplateLLMService
from apps.email_templates.services.preview_context import placeholder_context_for_preview
from apps.email_templates.services.render_service import TemplateRenderError, render_email_version
from apps.email_templates.services.validation_service import TemplateValidationService
from apps.email_templates.services.version_actions import approve_latest_version
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.ui.forms import NewEmailTemplateForm, TemplateApproveForm, TemplatePreviewForm, TemplateReviseForm
from apps.ui.forms_customer import PortalTemplateVersionForm
from apps.ui.services.operator import get_active_tenant
from apps.tenants.models import Tenant
from apps.workflows.services.template_guard import workflow_steps_reference_template


def _version_form_initial_from_latest(latest: EmailTemplateVersion | None) -> dict:
    if latest is None:
        return {}
    return {
        "subject_template": latest.subject_template or "",
        "preview_text_template": latest.preview_text_template or "",
        "html_template": latest.html_template or "",
        "text_template": latest.text_template or "",
    }


@operator_required
def templates_list(request):
    qs = EmailTemplate.objects.select_related("tenant").all()
    tenant_id = (request.GET.get("tenant") or "").strip()
    tenant_slug = (request.GET.get("tenant_slug") or "").strip()
    q = (request.GET.get("q") or "").strip()
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    elif tenant_slug:
        qs = qs.filter(tenant__slug__iexact=tenant_slug)
    if q:
        qs = qs.filter(Q(key__icontains=q) | Q(name__icontains=q))
    tenant_rows = [
        {"tenant": t, "selected": bool(tenant_id) and str(t.id) == tenant_id}
        for t in Tenant.objects.order_by("name")
    ]
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Templates",
            "nav_active": "templates",
            "templates": qs.order_by("tenant__name", "key")[:500],
            "filter_tenant": tenant_id,
            "filter_tenant_slug": tenant_slug,
            "filter_q": q,
            "tenant_rows": tenant_rows,
        }
    )
    return render(request, "ui/pages/templates_list.html", ctx)


@operator_required
def template_detail(request, template_id):
    tpl = get_object_or_404(
        EmailTemplate.objects.select_related("tenant").prefetch_related(
            "variables", "versions"
        ),
        pk=template_id,
    )
    versions = tpl.versions.order_by("-version_number")
    vers_list = list(versions[:8])
    approved_version = tpl.current_approved_version
    latest_version = vers_list[0] if vers_list else None
    diff_subject = ""
    diff_text = ""
    diff_html = ""
    if len(vers_list) >= 2:
        a, b = vers_list[1], vers_list[0]
        diff_subject = "\n".join(
            difflib.unified_diff(
                (a.subject_template or "").splitlines(),
                (b.subject_template or "").splitlines(),
                fromfile=f"v{a.version_number} subject",
                tofile=f"v{b.version_number} subject",
                lineterm="",
            )
        )
        diff_text = "\n".join(
            difflib.unified_diff(
                (a.text_template or "").splitlines(),
                (b.text_template or "").splitlines(),
                fromfile=f"v{a.version_number} text",
                tofile=f"v{b.version_number} text",
                lineterm="",
            )
        )
        diff_html = "\n".join(
            difflib.unified_diff(
                (a.html_template or "").splitlines(),
                (b.html_template or "").splitlines(),
                fromfile=f"v{a.version_number} html",
                tofile=f"v{b.version_number} html",
                lineterm="",
            )
        )
    preview_form = TemplatePreviewForm()
    revise_form = TemplateReviseForm()
    approve_form = TemplateApproveForm()
    version_form = PortalTemplateVersionForm(initial=_version_form_initial_from_latest(latest_version))
    default_preview_ctx = placeholder_context_for_preview(tpl)
    preview_draft_url = request.build_absolute_uri(
        reverse("ui:template_preview_draft", kwargs={"template_id": tpl.id})
    )
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": tpl.name,
            "nav_active": "templates",
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
            "default_preview_context": default_preview_ctx,
            "preview_draft_url": preview_draft_url,
        }
    )
    return render(request, "ui/pages/template_detail.html", ctx)


@operator_required
def template_new(request):
    tenant = get_active_tenant(request)
    if not tenant:
        django_messages.error(request, "Select an active tenant first.")
        return redirect("ui:templates_list")
    if request.method == "POST":
        form = NewEmailTemplateForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            tpl = EmailTemplate.objects.create(
                tenant=tenant,
                key=d["key"],
                name=d["name"],
                category=d["category"],
                description=d.get("description") or "",
                status=TemplateStatus.DRAFT,
            )
            django_messages.success(request, "Template created.")
            return redirect("ui:template_detail", template_id=tpl.id)
    else:
        form = NewEmailTemplateForm()
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "New template",
            "nav_active": "templates",
            "form": form,
            "show_tenant_banner": True,
            "submit_label": "Next",
        }
    )
    return render(request, "ui/pages/template_new.html", ctx)


@operator_required
@require_POST
def template_version_create(request, template_id):
    tpl = get_object_or_404(EmailTemplate, pk=template_id)
    form = PortalTemplateVersionForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Fix version fields.")
        return redirect("ui:template_detail", template_id=tpl.id)
    d = form.cleaned_data
    max_v = tpl.versions.aggregate(m=Max("version_number")).get("m") or 0
    latest = tpl.versions.order_by("-version_number").first()
    html_out, text_out = reconcile_template_bodies(
        (latest.html_template if latest else "") or "",
        (latest.text_template if latest else "") or "",
        d["html_template"] or "",
        d.get("text_template") or "",
    )
    EmailTemplateVersion.objects.create(
        template=tpl,
        version_number=max_v + 1,
        created_by_type=CreatedByType.USER,
        source_type=VersionSourceType.MANUAL,
        subject_template=d["subject_template"],
        preview_text_template=d.get("preview_text_template") or "",
        html_template=html_out,
        text_template=text_out,
        approval_status=ApprovalStatus.PENDING,
    )
    django_messages.success(request, f"Created version {max_v + 1}.")
    return redirect("ui:template_detail", template_id=tpl.id)


@operator_required
@require_POST
def template_delete(request, template_id):
    tpl = get_object_or_404(EmailTemplate, pk=template_id)
    if workflow_steps_reference_template(tpl):
        django_messages.error(
            request,
            "This template is used by a workflow step; remove or update the workflow first.",
        )
        return redirect("ui:template_detail", template_id=tpl.id)
    name = tpl.name
    tpl.delete()
    django_messages.success(request, f"Deleted template “{name}”.")
    return redirect("ui:templates_list")


@operator_required
@require_POST
def template_preview_draft(request, template_id):
    tpl = get_object_or_404(EmailTemplate, pk=template_id)
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    subject = body.get("subject_template") or ""
    preview = body.get("preview_text_template") or ""
    html = body.get("html_template") or ""
    text = body.get("text_template") or ""
    ctx_data = body.get("context")
    if ctx_data is None:
        ctx_data = placeholder_context_for_preview(tpl)
    elif not isinstance(ctx_data, dict):
        return JsonResponse({"error": "context must be a JSON object"}, status=400)
    try:
        TemplateValidationService.validate_context(tpl, ctx_data)
        out = render_email_version(
            subject_template=subject,
            preview_template=preview,
            html_template=html,
            text_template=text,
            context=ctx_data,
            sanitize=True,
            strict_undefined=False,
        )
    except (TemplateRenderError, ValueError) as e:
        return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse(
        {
            "subject": out["subject"],
            "preview": out["preview"],
            "html": out["html"],
            "text": out["text"],
        }
    )


@operator_required
@require_POST
def template_preview(request, template_id):
    tpl = get_object_or_404(EmailTemplate, pk=template_id)
    form = TemplatePreviewForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Invalid preview context.")
        return redirect("ui:template_detail", template_id=tpl.id)
    ver = tpl.versions.order_by("-version_number").first()
    if not ver:
        django_messages.error(request, "No version to preview.")
        return redirect("ui:template_detail", template_id=tpl.id)
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
        return redirect("ui:template_detail", template_id=tpl.id)
    TemplateRenderLog.objects.create(
        template_version=ver,
        context_snapshot=ctx_data,
        subject_rendered=out["subject"],
        html_rendered=out["html"],
        text_rendered=out["text"],
        success=True,
    )
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": f"Preview — {tpl.name}",
            "nav_active": "templates",
            "template": tpl,
            "rendered": out,
            "context_used": ctx_data,
        }
    )
    return render(request, "ui/pages/template_preview_result.html", ctx)


@operator_required
@require_POST
def template_approve(request, template_id):
    tpl = get_object_or_404(EmailTemplate, pk=template_id)
    try:
        approve_latest_version(template=tpl)
        django_messages.success(request, "Latest version approved.")
    except ValueError as e:
        django_messages.error(request, str(e))
    return redirect("ui:template_detail", template_id=tpl.id)


@operator_required
@require_POST
def template_revise(request, template_id):
    tpl = get_object_or_404(EmailTemplate, pk=template_id)
    form = TemplateReviseForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Invalid revise form.")
        return redirect("ui:template_detail", template_id=tpl.id)
    ver = tpl.versions.order_by("-version_number").first()
    if not ver:
        django_messages.error(request, "No version to revise.")
        return redirect("ui:template_detail", template_id=tpl.id)
    try:
        TemplateLLMService().revise_template_version(
            template=tpl,
            base_version=ver,
            instructions=form.cleaned_data["instructions"],
        )
        django_messages.success(request, "New draft version created via LLM.")
    except Exception as e:
        django_messages.error(request, str(e))
    return redirect("ui:template_detail", template_id=tpl.id)
