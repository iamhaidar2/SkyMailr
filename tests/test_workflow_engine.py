from datetime import timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time

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
from apps.messages.models import OutboundMessage
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
    # Immediate Celery sweep runs the first step in eager test settings
    assert OutboundMessage.objects.filter(to_email="u@example.com").exists()


@pytest.mark.django_db
def test_workflow_second_send_after_wait(tenant):
    """After a wait step, the next send runs when next_run_at is due (sweep must run without relying only on Beat)."""

    def _approved_tpl(key: str, name: str) -> EmailTemplate:
        t = EmailTemplate.objects.create(
            tenant=tenant,
            key=key,
            name=name,
            category=TemplateCategory.LIFECYCLE,
            status=TemplateStatus.ACTIVE,
        )
        EmailTemplateVersion.objects.create(
            template=t,
            version_number=1,
            created_by_type=CreatedByType.SYSTEM,
            source_type=VersionSourceType.SEEDED,
            subject_template="Hi",
            html_template="<p>x</p>",
            text_template="x",
            approval_status=ApprovalStatus.APPROVED,
            is_current_approved=True,
        )
        TemplateVariable.objects.create(template=t, name="user_name", is_required=False)
        return t

    t1 = _approved_tpl("wf_first", "First")
    t2 = _approved_tpl("wf_second", "Second")
    wf = Workflow.objects.create(tenant=tenant, name="Drip", slug="drip-wait", is_active=True)
    WorkflowStep.objects.create(
        workflow=wf,
        order=1,
        step_type=WorkflowStepType.SEND_TEMPLATE,
        template=t1,
    )
    WorkflowStep.objects.create(
        workflow=wf,
        order=2,
        step_type=WorkflowStepType.WAIT_DURATION,
        wait_seconds=2,
    )
    WorkflowStep.objects.create(
        workflow=wf,
        order=3,
        step_type=WorkflowStepType.SEND_TEMPLATE,
        template=t2,
    )
    en = WorkflowEnrollment.objects.create(
        tenant=tenant,
        workflow=wf,
        recipient_email="u@example.com",
        metadata={"template_context": {"user_name": "U"}},
        status=EnrollmentStatus.ACTIVE,
    )
    with freeze_time(timezone.now()) as frozen:
        enroll_workflow(enrollment=en)
        assert OutboundMessage.objects.filter(tenant=tenant).count() == 1
        frozen.tick(delta=timedelta(seconds=3))
        process_due_executions(limit=10)
    assert OutboundMessage.objects.filter(tenant=tenant).count() == 2
