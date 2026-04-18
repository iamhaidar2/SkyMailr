"""Mutations for workflow step ordering and deletion (portal / operator UIs)."""

from __future__ import annotations

from django.db import transaction

from apps.workflows.models import Workflow, WorkflowStep


@transaction.atomic
def apply_step_order(*, workflow: Workflow, step: WorkflowStep, new_order: int) -> None:
    """Move `step` to 1-based position `new_order` among all steps in this workflow."""
    steps = list(WorkflowStep.objects.filter(workflow=workflow).order_by("order"))
    n = len(steps)
    if n == 0:
        return
    new_order = max(1, min(int(new_order), n))
    moving = next(s for s in steps if s.id == step.id)
    rest = [s for s in steps if s.id != step.id]
    idx = new_order - 1
    rest[idx:idx] = [moving]
    for i, s in enumerate(rest, start=1):
        if s.order != i:
            WorkflowStep.objects.filter(pk=s.pk).update(order=i)


@transaction.atomic
def delete_step_and_renumber(*, workflow: Workflow, step: WorkflowStep) -> None:
    """Remove a step and compact order values to 1..n."""
    step.delete()
    for i, s in enumerate(WorkflowStep.objects.filter(workflow=workflow).order_by("order"), start=1):
        if s.order != i:
            WorkflowStep.objects.filter(pk=s.pk).update(order=i)
