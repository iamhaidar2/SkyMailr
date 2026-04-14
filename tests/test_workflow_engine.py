import pytest
from django.utils import timezone

from apps.email_templates.models import (
    ApprovalStatus,
    CreatedByType,
    EmailTemplate,
    EmailTemplateVersion,
    TemplateCategory,
    TemplateStatus,
    TemplateVariable,
    VersionSourceType,
)
from apps.workflows.models import (
    EnrollmentStatus,
    Workflow,
    WorkflowEnrollment,
    WorkflowStep,
    WorkflowStepType,
)
from apps.workflows.services.workflow_engine import enroll_workflow, process_due_executions


@pytest.mark.django_db
def test_workflow_enrollment_and_process(tenant):
    tpl = EmailTemplate.objects.create(
        tenant=tenant,
        key="welcome_new_user",
        name="Welcome",
        category=TemplateCategory.LIFECYCLE,
        status=TemplateStatus.ACTIVE,
    )
    EmailTemplateVersion.objects.create(
        template=tpl,
        version_number=1,
        created_by_type=CreatedByType.SYSTEM,
        source_type=VersionSourceType.SEEDED,
        subject_template="Hi {{ user_name }}",
        html_template="<p>{{ user_name }}</p>",
        text_template="{{ user_name }}",
        approval_status=ApprovalStatus.APPROVED,
        is_current_approved=True,
    )
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=False)
    wf = Workflow.objects.create(
        tenant=tenant, name="Onboarding", slug="onboarding", is_active=True
    )
    WorkflowStep.objects.create(
        workflow=wf,
        order=1,
        step_type=WorkflowStepType.SEND_TEMPLATE,
        template=tpl,
    )
    en = WorkflowEnrollment.objects.create(
        tenant=tenant,
        workflow=wf,
        recipient_email="u@example.com",
        metadata={"template_context": {"user_name": "U"}},
        status=EnrollmentStatus.ACTIVE,
    )
    enroll_workflow(enrollment=en)
    n = process_due_executions(limit=5)
    assert n >= 1
