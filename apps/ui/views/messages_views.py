from urllib.parse import urlencode

from django.contrib import messages as django_messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.messages.models import OutboundMessage, OutboundStatus
from apps.messages.services.message_actions import cancel_outbound_message, retry_outbound_message
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.ui.forms import MessageFilterForm


def _apply_filters(qs, form: MessageFilterForm):
    if not form.is_valid():
        return qs
    d = form.cleaned_data
    if t := d.get("tenant"):
        qs = qs.filter(tenant=t)
    if st := d.get("status"):
        qs = qs.filter(status=st)
    if sa := (d.get("source_app") or "").strip():
        qs = qs.filter(source_app__icontains=sa)
    if tk := (d.get("template_key") or "").strip():
        qs = qs.filter(template__key__icontains=tk)
    if q := (d.get("q") or "").strip():
        qs = qs.filter(
            Q(to_email__icontains=q)
            | Q(subject_rendered__icontains=q)
            | Q(idempotency_key__icontains=q)
        )
    if df := d.get("date_from"):
        qs = qs.filter(created_at__date__gte=df)
    if dt := d.get("date_to"):
        qs = qs.filter(created_at__date__lte=dt)
    return qs


@operator_required
def messages_list(request):
    form = MessageFilterForm(request.GET or None)
    qs = OutboundMessage.objects.select_related("tenant", "template").all()
    qs = _apply_filters(qs, form)
    paginator = Paginator(qs.order_by("-created_at"), 50)
    page = paginator.get_page(request.GET.get("page"))
    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Messages",
            "nav_active": "messages",
            "filter_form": form,
            "page_obj": page,
            "filter_query": urlencode(qcopy),
        }
    )
    return render(request, "ui/pages/messages_list.html", ctx)


@operator_required
def message_detail(request, message_id):
    msg = get_object_or_404(
        OutboundMessage.objects.select_related("tenant", "template", "template_version"),
        pk=message_id,
    )
    events = msg.events.order_by("created_at")
    attempts = msg.attempts.order_by("attempt_number")
    idem = getattr(msg, "idempotency_record", None)
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": f"Message {msg.id}",
            "nav_active": "messages",
            "message": msg,
            "events": events,
            "attempts": attempts,
            "idempotency_record": idem,
            "can_retry": msg.status
            in (OutboundStatus.FAILED, OutboundStatus.DEFERRED),
            "can_cancel": msg.status
            in (
                OutboundStatus.QUEUED,
                OutboundStatus.RENDERED,
                OutboundStatus.DEFERRED,
            ),
            "just_created": request.GET.get("created") == "1",
        }
    )
    return render(request, "ui/pages/message_detail.html", ctx)


@operator_required
@require_POST
def message_retry(request, message_id):
    msg = get_object_or_404(OutboundMessage, pk=message_id)
    try:
        retry_outbound_message(msg)
        django_messages.success(request, "Message queued for retry.")
    except ValueError as e:
        django_messages.error(request, str(e))
    if request.headers.get("HX-Request"):
        r = HttpResponse(status=204)
        r["HX-Redirect"] = f"/messages/{msg.id}/"
        return r
    return redirect("ui:message_detail", message_id=msg.id)


@operator_required
@require_POST
def message_cancel(request, message_id):
    msg = get_object_or_404(OutboundMessage, pk=message_id)
    try:
        cancel_outbound_message(msg)
        django_messages.success(request, "Message cancelled.")
    except ValueError as e:
        django_messages.error(request, str(e))
    if request.headers.get("HX-Request"):
        r = HttpResponse(status=204)
        r["HX-Redirect"] = f"/messages/{msg.id}/"
        return r
    return redirect("ui:message_detail", message_id=msg.id)
