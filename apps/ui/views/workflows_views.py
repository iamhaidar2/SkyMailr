from django.contrib import messages as django_messages
from django.db.models import Count, Max
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.email_templates.models import EmailTemplate
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.ui.forms import WorkflowAddStepForm, WorkflowCreateForm, WorkflowEnrollForm
from apps.ui.services.operator import get_active_tenant
from apps.workflows.models import (
    Workflow,
    WorkflowEnrollment,
    WorkflowExecution,
    WorkflowStep,
    WorkflowStepType,
)
from apps.workflows.services.workflow_engine import enroll_workflow


@operator_required
def workflows_list(request):
    qs = (
        Workflow.objects.select_related("tenant")
        .annotate(
            step_count=Count("steps", distinct=True),
            enrollment_count=Count("enrollments", distinct=True),
        )
        .order_by("tenant__name", "slug")
    )
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Workflows",
            "nav_active": "workflows",
            "workflows": qs[:500],
            "create_form": WorkflowCreateForm(),
        }
    )
    return render(request, "ui/pages/workflows_list.html", ctx)


@operator_required
def workflow_new(request):
    tenant = get_active_tenant(request)
    if not tenant:
        django_messages.error(request, "Select an active tenant first.")
        return redirect("ui:workflows_list")
    if request.method != "POST":
        return redirect("ui:workflows_list")
    form = WorkflowCreateForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Invalid workflow form.")
        return redirect("ui:workflows_list")
    d = form.cleaned_data
    wf, created = Workflow.objects.get_or_create(
        tenant=tenant,
        slug=d["slug"],
        defaults={"name": d["name"]},
    )
    if not created:
        django_messages.info(request, "Workflow already exists — opening it.")
    else:
        django_messages.success(request, "Workflow created.")
    return redirect("ui:workflow_detail", workflow_id=wf.id)


@operator_required
def workflow_detail(request, workflow_id):
    wf = get_object_or_404(
        Workflow.objects.select_related("tenant").prefetch_related("steps"),
        pk=workflow_id,
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
    step_form = WorkflowAddStepForm(initial={"order": max_order + 1})
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": wf.name,
            "nav_active": "workflows",
            "workflow": wf,
            "steps": steps,
            "enrollments": enrollments,
            "executions": executions,
            "enroll_form": enroll_form,
            "step_form": step_form,
        }
    )
    return render(request, "ui/pages/workflow_detail.html", ctx)


@operator_required
@require_POST
def workflow_enroll(request, workflow_id):
    wf = get_object_or_404(Workflow, pk=workflow_id)
    form = WorkflowEnrollForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Invalid enrollment.")
        return redirect("ui:workflow_detail", workflow_id=wf.id)
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
    return redirect("ui:workflow_detail", workflow_id=wf.id)


@operator_required
@require_POST
def workflow_add_step(request, workflow_id):
    wf = get_object_or_404(Workflow, pk=workflow_id)
    form = WorkflowAddStepForm(request.POST)
    if not form.is_valid():
        django_messages.error(request, "Invalid step.")
        return redirect("ui:workflow_detail", workflow_id=wf.id)
    d = form.cleaned_data
    st = d["step_type"]
    tpl = None
    tkey = (d.get("template_key") or "").strip()
    if st == WorkflowStepType.SEND_TEMPLATE and tkey:
        tpl = EmailTemplate.objects.filter(tenant=wf.tenant, key=tkey).first()
    WorkflowStep.objects.create(
        workflow=wf,
        order=d["order"],
        step_type=st,
        template=tpl,
        template_key=tkey if not tpl else "",
        wait_seconds=d.get("wait_seconds") or None,
    )
    django_messages.success(request, "Step added.")
    return redirect("ui:workflow_detail", workflow_id=wf.id)
