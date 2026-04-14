import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.email_templates.models import EmailTemplate
from apps.messages.models import MessageType
from apps.messages.services.send_pipeline import create_templated_message
from apps.workflows.models import (
    EnrollmentStatus,
    ExecutionStatus,
    WorkflowEnrollment,
    WorkflowExecution,
    WorkflowStepRun,
    WorkflowStepType,
)

logger = logging.getLogger(__name__)


def next_linear_step(workflow, after_order: int):
    return workflow.steps.filter(order__gt=after_order).order_by("order").first()


@transaction.atomic
def enroll_workflow(*, enrollment: WorkflowEnrollment) -> WorkflowExecution:
    wf = enrollment.workflow
    first = wf.steps.order_by("order").first()
    if not first:
        raise ValueError("Workflow has no steps")
    ex, _ = WorkflowExecution.objects.get_or_create(
        enrollment=enrollment,
        defaults={
            "status": ExecutionStatus.RUNNING,
            "current_step": first,
            "next_run_at": timezone.now(),
        },
    )
    return ex


def process_due_executions(limit: int = 50) -> int:
    now = timezone.now()
    qs = WorkflowExecution.objects.filter(
        status__in=[ExecutionStatus.RUNNING, ExecutionStatus.WAITING],
        next_run_at__lte=now,
    ).select_related("enrollment", "enrollment__workflow", "current_step")[:limit]
    count = 0
    for ex in qs:
        try:
            _process_one_execution(ex)
            count += 1
        except Exception:
            logger.exception("workflow execution %s failed", ex.id)
            ex.status = ExecutionStatus.FAILED
            ex.last_error = "step processing failed"
            ex.save(update_fields=["status", "last_error"])
    return count


def _complete(ex: WorkflowExecution) -> None:
    ex.status = ExecutionStatus.COMPLETED
    ex.completed_at = timezone.now()
    ex.current_step = None
    ex.save(update_fields=["status", "completed_at", "current_step"])
    ex.enrollment.status = EnrollmentStatus.COMPLETED
    ex.enrollment.save(update_fields=["status"])


def _process_one_execution(ex: WorkflowExecution) -> None:
    step = ex.current_step
    wf = ex.enrollment.workflow
    tenant = ex.enrollment.tenant
    now = timezone.now()

    if not step:
        _complete(ex)
        return

    if step.step_type == WorkflowStepType.WAIT_DURATION:
        nxt = next_linear_step(wf, step.order)
        ex.current_step = nxt
        ex.next_run_at = now
        ex.status = ExecutionStatus.RUNNING
        ex.save(update_fields=["current_step", "next_run_at", "status"])
        WorkflowStepRun.objects.create(execution=ex, step=step, status="wait_elapsed")
        if not nxt:
            _complete(ex)
            return
        _process_one_execution(ex)
        return

    if step.step_type == WorkflowStepType.SEND_TEMPLATE:
        tpl = step.template
        if not tpl and step.template_key:
            tpl = EmailTemplate.objects.filter(
                tenant=tenant, key=step.template_key
            ).first()
        if not tpl:
            raise ValueError("Workflow step missing template")
        meta = dict(ex.enrollment.metadata or {})
        ctx = meta.get("template_context") or {}
        create_templated_message(
            tenant=tenant,
            template=tpl,
            source_app=meta.get("source_app", "workflow"),
            message_type=MessageType.LIFECYCLE,
            to_email=ex.enrollment.recipient_email,
            to_name=ex.enrollment.recipient_name,
            context=ctx,
            metadata={"workflow_id": str(wf.id), "enrollment_id": str(ex.enrollment.id)},
            tags={},
            idempotency_key=None,
            workflow_execution=ex,
        )
        WorkflowStepRun.objects.create(execution=ex, step=step, status="sent")
        nxt = next_linear_step(wf, step.order)
        if not nxt:
            _complete(ex)
            return
        if nxt.step_type == WorkflowStepType.WAIT_DURATION:
            wait_s = int(nxt.wait_seconds or 0)
            ex.current_step = nxt
            ex.next_run_at = now + timedelta(seconds=wait_s)
            ex.status = ExecutionStatus.WAITING
            ex.save(update_fields=["current_step", "next_run_at", "status"])
            return
        ex.current_step = nxt
        ex.next_run_at = now
        ex.status = ExecutionStatus.RUNNING
        ex.save(update_fields=["current_step", "next_run_at", "status"])
        _process_one_execution(ex)
        return

    if step.step_type == WorkflowStepType.END:
        _complete(ex)
        return

    nxt = next_linear_step(wf, step.order)
    if not nxt:
        _complete(ex)
        return
    ex.current_step = nxt
    ex.next_run_at = now
    ex.save(update_fields=["current_step", "next_run_at"])
    _process_one_execution(ex)
