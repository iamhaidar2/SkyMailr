"""API and backend-path tests for MVP readiness (auth, sends, webhooks, workflows)."""

import json
import uuid

import pytest
from rest_framework.test import APIClient

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
from apps.messages.models import (
    MessageEventType,
    OutboundMessage,
    OutboundStatus,
    ProviderWebhookEvent,
)
from apps.messages.services.message_actions import cancel_outbound_message, retry_outbound_message
from apps.workflows.models import Workflow, WorkflowEnrollment, WorkflowStep, WorkflowStepType


@pytest.mark.django_db
def test_health_and_provider_health():
    c = APIClient()
    r = c.get("/api/v1/health/")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"
    r2 = c.get("/api/v1/providers/health/")
    assert r2.status_code == 200
    body = r2.json()
    assert "provider" in body and "ok" in body


@pytest.mark.django_db
def test_send_raw_success(api_key, tenant):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r = c.post(
        "/api/v1/messages/send/",
        {
            "to_email": "raw@example.com",
            "subject": "Hello",
            "html_body": "<p>Hi</p>",
            "text_body": "Hi",
            "source_app": "tests",
            "message_type": "transactional",
        },
        format="json",
    )
    assert r.status_code == 201
    data = r.json()
    assert data["status"] in (OutboundStatus.QUEUED, OutboundStatus.SENT)
    assert data["to_email"] == "raw@example.com"


@pytest.mark.django_db
def test_send_template_success(api_key, approved_template):
    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=False)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r = c.post(
        "/api/v1/messages/send-template/",
        {
            "template_key": "email_verification",
            "to_email": "t@example.com",
            "context": {"user_name": "Bob"},
            "source_app": "tests",
            "message_type": "transactional",
        },
        format="json",
    )
    assert r.status_code == 201
    assert r.json()["to_email"] == "t@example.com"


@pytest.mark.django_db
def test_idempotency_replays_same_message(api_key, approved_template):
    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=False)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    body = {
        "template_key": "email_verification",
        "to_email": "u@example.com",
        "context": {"user_name": "Bob"},
        "source_app": "tests",
        "message_type": "transactional",
        "idempotency_key": "idem-api-core-1",
    }
    r1 = c.post("/api/v1/messages/send-template/", body, format="json")
    r2 = c.post("/api/v1/messages/send-template/", body, format="json")
    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.django_db
def test_idempotency_failed_render_replays(api_key, approved_template):
    """Failed renders persist; same idempotency key returns the stored failed message."""
    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=True)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    body = {
        "template_key": "email_verification",
        "to_email": "fail@example.com",
        "context": {},
        "source_app": "tests",
        "message_type": "transactional",
        "idempotency_key": "idem-fail-1",
    }
    r1 = c.post("/api/v1/messages/send-template/", body, format="json")
    assert r1.status_code == 400
    r2 = c.post("/api/v1/messages/send-template/", body, format="json")
    assert r2.status_code == 200
    om = OutboundMessage.objects.get()
    assert r2.json()["id"] == str(om.id)


@pytest.mark.django_db
def test_message_detail_tenant_isolation(api_key, api_key_other, tenant):
    msg = OutboundMessage.objects.create(
        tenant=tenant,
        source_app="tests",
        message_type="transactional",
        to_email="x@example.com",
        status=OutboundStatus.SENT,
    )
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    assert c.get(f"/api/v1/messages/{msg.id}/").status_code == 200
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key_other}")
    assert c.get(f"/api/v1/messages/{msg.id}/").status_code == 404


@pytest.mark.django_db
def test_templates_list_scoped_to_tenant(api_key, api_key_other, tenant, other_tenant):
    EmailTemplate.objects.create(
        tenant=tenant,
        key="only_a",
        name="A",
        category=TemplateCategory.TRANSACTIONAL,
        status=TemplateStatus.ACTIVE,
    )
    EmailTemplate.objects.create(
        tenant=other_tenant,
        key="only_b",
        name="B",
        category=TemplateCategory.TRANSACTIONAL,
        status=TemplateStatus.ACTIVE,
    )
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r = c.get("/api/v1/templates/")
    assert r.status_code == 200
    keys = {x["key"] for x in r.json()}
    assert "only_a" in keys
    assert "only_b" not in keys


@pytest.mark.django_db
def test_retry_only_when_failed(api_key, tenant):
    msg = OutboundMessage.objects.create(
        tenant=tenant,
        source_app="tests",
        message_type="transactional",
        to_email="r@example.com",
        status=OutboundStatus.SENT,
    )
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r = c.post(f"/api/v1/messages/{msg.id}/retry/", {}, format="json")
    assert r.status_code == 400

    msg.status = OutboundStatus.FAILED
    msg.save(update_fields=["status"])
    retry_outbound_message(msg)
    msg.refresh_from_db()
    # Eager Celery runs dispatch immediately; dummy provider marks SENT.
    assert msg.status == OutboundStatus.SENT


@pytest.mark.django_db
def test_cancel_only_when_cancellable(api_key, tenant):
    msg = OutboundMessage.objects.create(
        tenant=tenant,
        source_app="tests",
        message_type="transactional",
        to_email="c@example.com",
        status=OutboundStatus.SENT,
    )
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r = c.post(f"/api/v1/messages/{msg.id}/cancel/", {}, format="json")
    assert r.status_code == 400

    msg.status = OutboundStatus.QUEUED
    msg.save(update_fields=["status"])
    cancel_outbound_message(msg)
    msg.refresh_from_db()
    assert msg.status == OutboundStatus.CANCELLED


@pytest.mark.django_db
def test_template_preview_valid_and_invalid(api_key, approved_template):
    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=True)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r_ok = c.post(
        f"/api/v1/templates/{tpl.id}/preview/",
        {"context": {"user_name": "Ada"}},
        format="json",
    )
    assert r_ok.status_code == 200
    assert "Ada" in r_ok.json().get("html", "")
    r_bad = c.post(
        f"/api/v1/templates/{tpl.id}/preview/",
        {"context": {}},
        format="json",
    )
    assert r_bad.status_code == 400


@pytest.mark.django_db
def test_template_approve_latest(api_key, tenant):
    tpl = EmailTemplate.objects.create(
        tenant=tenant,
        key="draft_only",
        name="Draft",
        category=TemplateCategory.TRANSACTIONAL,
        status=TemplateStatus.DRAFT,
    )
    EmailTemplateVersion.objects.create(
        template=tpl,
        version_number=1,
        created_by_type=CreatedByType.SYSTEM,
        source_type=VersionSourceType.SEEDED,
        subject_template="S",
        html_template="<p>x</p>",
        text_template="x",
        approval_status=ApprovalStatus.PENDING,
        is_current_approved=False,
    )
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r = c.post(f"/api/v1/templates/{tpl.id}/approve/", {}, format="json")
    assert r.status_code == 200
    tpl.refresh_from_db()
    assert tpl.current_approved_version is not None


@pytest.mark.django_db
def test_webhook_persists_and_updates_message(api_key, tenant):
    mid = str(uuid.uuid4())
    msg = OutboundMessage.objects.create(
        tenant=tenant,
        source_app="tests",
        message_type="transactional",
        to_email="w@example.com",
        status=OutboundStatus.SENT,
        provider_message_id=mid,
    )
    c = APIClient()
    body = json.dumps({"message_id": mid, "event": "delivered"})
    r = c.post(
        f"/api/v1/webhooks/provider/postal/",
        body,
        content_type="application/json",
    )
    assert r.status_code == 200
    assert ProviderWebhookEvent.objects.filter(provider="postal").exists()
    msg.refresh_from_db()
    assert msg.status == OutboundStatus.DELIVERED
    assert msg.events.filter(event_type=MessageEventType.DELIVERED).exists()


@pytest.mark.django_db
def test_webhook_invalid_json_safe():
    c = APIClient()
    r = c.post(
        "/api/v1/webhooks/provider/postal/",
        b"not-json-{",
        content_type="application/json",
    )
    assert r.status_code == 200
    ev = ProviderWebhookEvent.objects.order_by("-id").first()
    assert ev is not None
    assert ev.normalized == {}


@pytest.mark.django_db
def test_workflow_create_enroll_and_dispatch(api_key, tenant, approved_template):
    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=False)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    wr = c.post(
        "/api/v1/workflows/",
        {"name": "Onboarding", "slug": "onb"},
        format="json",
    )
    assert wr.status_code == 200
    wf_id = wr.json()["id"]
    wf = Workflow.objects.get(id=wf_id)
    WorkflowStep.objects.create(
        workflow=wf,
        order=1,
        step_type=WorkflowStepType.SEND_TEMPLATE,
        template=tpl,
    )
    er = c.post(
        f"/api/v1/workflows/{wf_id}/enroll/",
        {
            "recipient_email": "wf@example.com",
            "metadata": {"template_context": {"user_name": "Wf"}},
        },
        format="json",
    )
    assert er.status_code == 200
    WorkflowEnrollment.objects.get()
    # API enroll calls enroll_workflow; engine schedules an immediate sweep
    assert OutboundMessage.objects.filter(tenant=tenant, to_email="wf@example.com").exists()
    om = OutboundMessage.objects.get(to_email="wf@example.com")
    assert om.status == OutboundStatus.SENT


@pytest.mark.django_db
def test_workflow_enrollment_other_tenant_cannot_enroll(api_key_other, tenant, approved_template):
    tpl, _ = approved_template
    wf = Workflow.objects.create(
        tenant=tenant, name="T", slug="t-isolation", is_active=True
    )
    WorkflowStep.objects.create(
        workflow=wf,
        order=1,
        step_type=WorkflowStepType.SEND_TEMPLATE,
        template=tpl,
    )
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key_other}")
    r = c.post(
        f"/api/v1/workflows/{wf.id}/enroll/",
        {"recipient_email": "x@example.com"},
        format="json",
    )
    assert r.status_code == 404
