"""Approve template versions — shared between API and operator UI."""

from django.utils import timezone

from apps.email_templates.models import (
    ApprovalStatus,
    EmailTemplate,
    EmailTemplateVersion,
    TemplateStatus,
)


def approve_latest_version(*, template: EmailTemplate) -> EmailTemplateVersion:
    ver = template.versions.order_by("-version_number").first()
    if not ver:
        raise ValueError("No version")
    EmailTemplateVersion.objects.filter(template=template).update(is_current_approved=False)
    ver.approval_status = ApprovalStatus.APPROVED
    ver.approved_at = timezone.now()
    ver.is_current_approved = True
    ver.save(update_fields=["approval_status", "approved_at", "is_current_approved"])
    template.status = TemplateStatus.ACTIVE
    template.save(update_fields=["status", "updated_at"])
    return ver
