import difflib

from django.contrib import messages as django_messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.email_templates.models import EmailTemplate, TemplateRenderLog, TemplateStatus
from apps.email_templates.services.llm_service import TemplateLLMService
from apps.email_templates.services.render_service import TemplateRenderError, render_email_version
from apps.email_templates.services.validation_service import TemplateValidationService
from apps.email_templates.services.version_actions import approve_latest_version
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.ui.forms import NewEmailTemplateForm, TemplateApproveForm, TemplatePreviewForm, TemplateReviseForm
from apps.ui.services.operator import get_active_tenant
from apps.tenants.models import Tenant


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
            "preview_form": preview_form,
            "revise_form": revise_form,
            "approve_form": approve_form,
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
        }
    )
    return render(request, "ui/pages/template_new.html", ctx)


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
