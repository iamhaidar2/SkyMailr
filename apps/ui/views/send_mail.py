from django.contrib import messages as django_messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.email_templates.models import EmailTemplate
from apps.email_templates.services.render_service import TemplateRenderError, render_email_version, sanitize_html
from apps.email_templates.services.validation_service import TemplateValidationService
from apps.messages.models import IdempotencyKeyRecord, OutboundStatus
from apps.messages.services.idempotency import hash_idempotency_key
from apps.messages.services.send_pipeline import create_raw_message, create_templated_message
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.ui.forms import SendRawForm, SendTemplateForm
from apps.ui.services.operator import get_active_tenant


def _idem_attach(tenant, raw_key: str, msg):
    if not raw_key:
        return
    IdempotencyKeyRecord.objects.get_or_create(
        tenant=tenant,
        key_hash=hash_idempotency_key(str(tenant.id), raw_key),
        defaults={"message": msg},
    )


@operator_required
def send_email(request):
    tenant = get_active_tenant(request)
    raw_form = SendRawForm()
    tpl_form = SendTemplateForm()
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Send email",
            "nav_active": "send",
            "active_tenant": tenant,
            "raw_form": raw_form,
            "tpl_form": tpl_form,
            "no_tenant": tenant is None,
        }
    )
    return render(request, "ui/pages/send_email.html", ctx)


@operator_required
@require_POST
def send_raw(request):
    tenant = get_active_tenant(request)
    if not tenant:
        django_messages.error(request, "Select an active tenant first.")
        return redirect("ui:send_email")
    form = SendRawForm(request.POST)
    if not form.is_valid():
        ctx = operator_shell_context(request)
        ctx.update(
            {
                "page_title": "Send email",
                "nav_active": "send",
                "active_tenant": tenant,
                "raw_form": form,
                "tpl_form": SendTemplateForm(),
            }
        )
        return render(request, "ui/pages/send_email.html", ctx, status=400)
    d = form.cleaned_data
    raw_idem = (d.get("idempotency_key") or "").strip()
    if raw_idem:
        h = hash_idempotency_key(str(tenant.id), raw_idem)
        existing = IdempotencyKeyRecord.objects.filter(tenant=tenant, key_hash=h).first()
        if existing:
            django_messages.info(request, "Idempotent replay — existing message.")
            return redirect("ui:message_detail", message_id=existing.message_id)
    msg = create_raw_message(
        tenant=tenant,
        source_app=d["source_app"],
        message_type=d["message_type"],
        to_email=d["to_email"],
        to_name=d.get("to_name") or "",
        subject=d["subject"],
        html_body=d["html_body"],
        text_body=d.get("text_body") or "",
        metadata=d.get("metadata") or {},
        idempotency_key=raw_idem or None,
    )
    _idem_attach(tenant, raw_idem, msg)
    django_messages.success(
        request,
        "Message created — queued for sending (or suppressed). Open the detail below to track status.",
    )
    url = reverse("ui:message_detail", kwargs={"message_id": msg.id}) + "?created=1"
    return HttpResponseRedirect(url)


@operator_required
@require_POST
def send_template(request):
    tenant = get_active_tenant(request)
    if not tenant:
        django_messages.error(request, "Select an active tenant first.")
        return redirect("ui:send_email")
    form = SendTemplateForm(request.POST)
    if not form.is_valid():
        ctx = operator_shell_context(request)
        ctx.update(
            {
                "page_title": "Send email",
                "nav_active": "send",
                "active_tenant": tenant,
                "raw_form": SendRawForm(),
                "tpl_form": form,
            }
        )
        return render(request, "ui/pages/send_email.html", ctx, status=400)
    d = form.cleaned_data
    tpl = EmailTemplate.objects.filter(tenant=tenant, key=d["template_key"]).first()
    if not tpl:
        form.add_error("template_key", "Unknown template key for this tenant.")
        ctx = operator_shell_context(request)
        ctx.update(
            {
                "page_title": "Send email",
                "nav_active": "send",
                "active_tenant": tenant,
                "raw_form": SendRawForm(),
                "tpl_form": form,
                "show_tenant_banner": True,
            }
        )
        return render(request, "ui/pages/send_email.html", ctx, status=400)
    raw_idem = (d.get("idempotency_key") or "").strip()
    if raw_idem:
        h = hash_idempotency_key(str(tenant.id), raw_idem)
        existing = IdempotencyKeyRecord.objects.filter(tenant=tenant, key_hash=h).first()
        if existing:
            django_messages.info(request, "Idempotent replay — existing message.")
            return redirect("ui:message_detail", message_id=existing.message_id)
    try:
        msg = create_templated_message(
            tenant=tenant,
            template=tpl,
            source_app=d["source_app"],
            message_type=d["message_type"],
            to_email=d["to_email"],
            to_name=d.get("to_name") or "",
            context=d.get("context") or {},
            metadata=d.get("metadata") or {},
            tags=d.get("tags") or {},
            idempotency_key=raw_idem or None,
            scheduled_for=d.get("scheduled_for"),
        )
    except ValueError as e:
        form.add_error(None, str(e))
        ctx = operator_shell_context(request)
        ctx.update(
            {
                "page_title": "Send email",
                "nav_active": "send",
                "active_tenant": tenant,
                "raw_form": SendRawForm(),
                "tpl_form": form,
            }
        )
        return render(request, "ui/pages/send_email.html", ctx, status=400)
    _idem_attach(tenant, raw_idem, msg)
    if msg.status == OutboundStatus.FAILED:
        form.add_error(None, msg.last_error or "Send failed")
        ctx = operator_shell_context(request)
        ctx.update(
            {
                "page_title": "Send email",
                "nav_active": "send",
                "active_tenant": tenant,
                "raw_form": SendRawForm(),
                "tpl_form": form,
                "show_tenant_banner": True,
            }
        )
        return render(request, "ui/pages/send_email.html", ctx, status=400)
    django_messages.success(
        request,
        "Templated message created — queued for sending (or suppressed). Track it on the detail page.",
    )
    url = reverse("ui:message_detail", kwargs={"message_id": msg.id}) + "?created=1"
    return HttpResponseRedirect(url)


@operator_required
@require_POST
def send_preview_raw(request):
    tenant = get_active_tenant(request)
    if not tenant:
        return render(
            request,
            "ui/partials/send_preview_error.html",
            {"error": "Select an active tenant first."},
            status=400,
        )
    form = SendRawForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "ui/partials/send_preview_error.html",
            {"error": str(form.errors)},
            status=400,
        )
    d = form.cleaned_data
    html = sanitize_html(d["html_body"])
    return render(
        request,
        "ui/partials/send_preview_raw.html",
        {
            "subject": d["subject"],
            "html": html,
            "text": d.get("text_body") or "",
        },
    )


@operator_required
@require_POST
def send_preview_template(request):
    tenant = get_active_tenant(request)
    if not tenant:
        return render(
            request,
            "ui/partials/send_preview_error.html",
            {"error": "Select an active tenant first."},
            status=400,
        )
    form = SendTemplateForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "ui/partials/send_preview_error.html",
            {"error": str(form.errors)},
            status=400,
        )
    d = form.cleaned_data
    tpl = EmailTemplate.objects.filter(tenant=tenant, key=d["template_key"]).first()
    if not tpl:
        return render(
            request,
            "ui/partials/send_preview_error.html",
            {"error": "Unknown template key for this tenant."},
            status=400,
        )
    ver = tpl.versions.order_by("-version_number").first()
    if not ver:
        return render(
            request,
            "ui/partials/send_preview_error.html",
            {"error": "No template version to render."},
            status=400,
        )
    ctx_data = d.get("context") or {}
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
        return render(
            request,
            "ui/partials/send_preview_error.html",
            {"error": str(e)},
            status=400,
        )
    return render(request, "ui/partials/send_preview_template.html", {"rendered": out})
