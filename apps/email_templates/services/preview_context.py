"""Default JSON context for template preview when the user has not supplied values."""

from __future__ import annotations

from apps.email_templates.models import EmailTemplate


def placeholder_context_for_preview(template: EmailTemplate) -> dict[str, str]:
    """Bracket placeholders so Jinja renders and required-variable validation usually passes."""
    out: dict[str, str] = {}
    for v in template.variables.all():
        out[v.name] = f"[{v.name}]"
    return out
