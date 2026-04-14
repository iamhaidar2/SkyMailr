from django.contrib import messages as django_messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.email_templates.models import EmailTemplate
from apps.messages.models import IdempotencyKeyRecord, OutboundStatus
from apps.messages.services.idempotency import hash_idempotency_key
from apps.messages.services.send_pipeline import create_raw_message, create_templated_message
from apps.messages.tasks import dispatch_message_task
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.ui.forms import SendRawForm, SendTemplateForm
from apps.ui.services.operator import get_active_tenant


def _idem_attach(tenant, raw_key: str, msg):
    if not raw_key or msg.status == OutboundStatus.SUPPRESSED:
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
    if msg.status == OutboundStatus.QUEUED:
        dispatch_message_task.delay(str(msg.id))
    django_messages.success(request, "Message created.")
    return redirect("ui:message_detail", message_id=msg.id)


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
    except Exception as e:
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
    if msg.status == OutboundStatus.QUEUED:
        dispatch_message_task.delay(str(msg.id))
    django_messages.success(request, "Templated message created.")
    return redirect("ui:message_detail", message_id=msg.id)
