"""Discover template variables needed for workflow test enrollments and build sample context."""

from __future__ import annotations

import re
from typing import Any

from apps.email_templates.models import EmailTemplate, EmailTemplateVersion
from apps.email_templates.services.validation_service import TemplateValidationService
from apps.workflows.models import Workflow, WorkflowStepType

# First identifier after `{{` (covers `{{ var }}` and `{{ var | default(...) }}`).
_JINJA_VAR = re.compile(r"\{\{[-\s]*([a-zA-Z_][a-zA-Z0-9_]*)\b")


def _text_chunks_from_version(ver: EmailTemplateVersion) -> list[str]:
    parts: list[str] = [
        ver.subject_template or "",
        ver.preview_text_template or "",
        ver.html_template or "",
        ver.text_template or "",
    ]
    for vt in ver.subject_variants or []:
        if isinstance(vt, str):
            parts.append(vt)
    return parts


def parse_jinja_variable_names(text: str) -> set[str]:
    """Extract top-level Jinja variable names from template strings (best-effort)."""
    if not text:
        return set()
    out: set[str] = set()
    for m in _JINJA_VAR.finditer(text):
        ident = m.group(1)
        if ident.lower() in ("true", "false", "none"):
            continue
        out.add(ident)
    return out


def email_templates_for_workflow_send_steps(workflow: Workflow) -> list[EmailTemplate]:
    """Resolve EmailTemplate for each send-template step (FK or template_key on tenant)."""
    out: list[EmailTemplate] = []
    for step in workflow.steps.order_by("order"):
        if step.step_type != WorkflowStepType.SEND_TEMPLATE:
            continue
        tpl = step.template
        if tpl is None and (step.template_key or "").strip():
            tpl = EmailTemplate.objects.filter(
                tenant=workflow.tenant, key=step.template_key.strip()
            ).first()
        if tpl is not None:
            out.append(tpl)
    return out


def required_template_context_keys(workflow: Workflow) -> list[str]:
    """Union of declared variables and names found in approved template bodies for all send steps."""
    names: set[str] = set()
    for tpl in email_templates_for_workflow_send_steps(workflow):
        names.update(TemplateValidationService.all_variable_names(tpl))
        ver = tpl.current_approved_version
        if ver:
            for chunk in _text_chunks_from_version(ver):
                names.update(parse_jinja_variable_names(chunk))
    return sorted(names)


def fake_placeholder_value(name: str) -> str:
    """Heuristic sample string for test enrollments (not production-safe)."""
    n = name.lower()
    if "email" in n:
        return "test.recipient@example.com"
    if "url" in n or n.endswith("_link") or n.endswith("_uri"):
        return "https://example.com/sample-path"
    if "name" in n or n in ("user", "recipient", "first_name", "last_name"):
        return "Test User"
    if "phone" in n:
        return "+1 555 0100"
    if n.endswith("_id") or n == "id":
        return "test-id-0001"
    if "amount" in n or "price" in n or "total" in n:
        return "9.99"
    return f"sample_{n}"


def build_default_enrollment_metadata(workflow: Workflow) -> dict[str, Any]:
    """Metadata dict for portal form initial (template_context pre-filled with fake values)."""
    keys = required_template_context_keys(workflow)
    tc = {k: fake_placeholder_value(k) for k in keys}
    return {"template_context": tc}
