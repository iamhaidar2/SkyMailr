"""Workflow enrollment template_context discovery and fake placeholders."""

import pytest

from apps.email_templates.models import (
    ApprovalStatus,
    CreatedByType,
    EmailTemplate,
    EmailTemplateVersion,
    TemplateCategory,
    TemplateStatus,
    VersionSourceType,
)
from apps.workflows.models import Workflow, WorkflowStep, WorkflowStepType
from apps.workflows.services.enrollment_context import (
    build_default_enrollment_metadata,
    fake_placeholder_value,
    parse_jinja_variable_names,
    required_template_context_keys,
)


def test_parse_jinja_variable_names_finds_simple_vars():
    assert parse_jinja_variable_names("Hi {{ user_name }} — {{ billing_page_url }}") == {
        "user_name",
        "billing_page_url",
    }


def test_fake_placeholder_value_heuristics():
    assert "example.com" in fake_placeholder_value("billing_page_url")
    assert "@" in fake_placeholder_value("user_email")


@pytest.mark.django_db
def test_required_keys_from_approved_body(tenant):
    tpl = EmailTemplate.objects.create(
        tenant=tenant,
        key="t1",
        name="T",
        category=TemplateCategory.LIFECYCLE,
        status=TemplateStatus.ACTIVE,
    )
    EmailTemplateVersion.objects.create(
        template=tpl,
        version_number=1,
        created_by_type=CreatedByType.SYSTEM,
        source_type=VersionSourceType.SEEDED,
        subject_template="S",
        html_template="<p>{{ alpha }}</p><a href='{{ billing_page_url }}'>x</a>",
        text_template="",
        approval_status=ApprovalStatus.APPROVED,
        is_current_approved=True,
    )
    wf = Workflow.objects.create(tenant=tenant, name="W", slug="w1")
    WorkflowStep.objects.create(
        workflow=wf,
        order=1,
        step_type=WorkflowStepType.SEND_TEMPLATE,
        template=tpl,
    )
    keys = required_template_context_keys(wf)
    assert "billing_page_url" in keys
    assert "alpha" in keys
    md = build_default_enrollment_metadata(wf)
    assert md["template_context"]["billing_page_url"]
    assert md["template_context"]["alpha"]
