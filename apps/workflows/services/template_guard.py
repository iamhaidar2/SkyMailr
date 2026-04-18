"""Checks whether an email template is referenced by workflows before destructive actions."""

from __future__ import annotations

from apps.email_templates.models import EmailTemplate
from apps.workflows.models import WorkflowStep, WorkflowStepType


def workflow_steps_reference_template(tpl: EmailTemplate) -> bool:
    """True if any workflow step points at this template by FK or by template_key on the same tenant."""
    if WorkflowStep.objects.filter(template=tpl).exists():
        return True
    key = (tpl.key or "").strip()
    if not key:
        return False
    return WorkflowStep.objects.filter(
        workflow__tenant_id=tpl.tenant_id,
        step_type=WorkflowStepType.SEND_TEMPLATE,
        template_key=key,
    ).exists()
