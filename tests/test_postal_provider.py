"""Postal provider send_message: HTTP + JSON body semantics."""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from apps.providers.base import EmailMessageDTO
from apps.providers.postal import PostalEmailProvider


def _minimal_dto():
    return EmailMessageDTO(
        to_email="u@example.com",
        subject="S",
        html_body="<p>h</p>",
        text_body="h",
        from_email="noreply@example.com",
    )


def _mock_post_response(*, status_code, json_body=None, text="", json_content=True):
    m = MagicMock()
    m.status_code = status_code
    if text:
        m.text = text
    elif json_body is not None:
        m.text = json.dumps(json_body)
    else:
        m.text = ""
    if json_content:
        m.headers = {"content-type": "application/json"}
        if json_body is not None:
            m.json.return_value = json_body
    else:
        m.headers = {"content-type": "text/plain"}
    return m


@override_settings(
    POSTAL_BASE_URL="https://postal.example.com",
    POSTAL_SERVER_API_KEY="secret",
)
def test_postal_send_returns_failure_when_http_200_body_has_status_error():
    body = {"status": "error", "message": "Domain not permitted"}
    with patch("apps.providers.postal.httpx.post") as post:
        post.return_value = _mock_post_response(status_code=200, json_body=body)
        p = PostalEmailProvider()
        r = p.send_message(_minimal_dto())
    assert r.success is False
    assert r.error_code == "postal_error"
    assert r.provider_message_id == ""
    assert r.raw_response.get("status") == "error"
    assert "Domain not permitted" in (r.error_detail or "")


@override_settings(
    POSTAL_BASE_URL="https://postal.example.com",
    POSTAL_SERVER_API_KEY="secret",
)
def test_postal_send_returns_success_when_http_200_body_has_message_id():
    body = {"status": "success", "message_id": "abc123"}
    with patch("apps.providers.postal.httpx.post") as post:
        post.return_value = _mock_post_response(status_code=200, json_body=body)
        p = PostalEmailProvider()
        r = p.send_message(_minimal_dto())
    assert r.success is True
    assert r.provider_message_id == "abc123"


@override_settings(
    POSTAL_BASE_URL="https://postal.example.com",
    POSTAL_SERVER_API_KEY="secret",
)
def test_postal_send_returns_failure_on_http_4xx():
    with patch("apps.providers.postal.httpx.post") as post:
        post.return_value = _mock_post_response(
            status_code=422,
            json_body={"status": "error", "message": "bad"},
        )
        p = PostalEmailProvider()
        r = p.send_message(_minimal_dto())
    assert r.success is False
    assert r.error_code == "http_422"

    with patch("apps.providers.postal.httpx.post") as post:
        m = MagicMock()
        m.status_code = 400
        m.text = "Bad Request"
        m.headers = {"content-type": "application/json"}
        m.json.return_value = {}
        post.return_value = m
        p = PostalEmailProvider()
        r = p.send_message(_minimal_dto())
    assert r.success is False
    assert r.error_code == "http_400"


@override_settings(
    POSTAL_BASE_URL="https://postal.example.com",
    POSTAL_SERVER_API_KEY="secret",
)
def test_postal_send_returns_failure_on_http_200_without_message_id():
    body = {"status": "ok"}
    with patch("apps.providers.postal.httpx.post") as post:
        post.return_value = _mock_post_response(status_code=200, json_body=body)
        p = PostalEmailProvider()
        r = p.send_message(_minimal_dto())
    assert r.success is False
    assert r.error_code == "postal_unexpected_response"


@pytest.mark.django_db
@override_settings(
    POSTAL_BASE_URL="https://postal.example.com",
    POSTAL_SERVER_API_KEY="secret",
)
def test_dispatch_marks_failed_when_postal_returns_postal_error():
    """Service-level: failed SendResult must not leave message as SENT."""
    from apps.messages.models import MessageType, OutboundStatus
    from apps.messages.services.dispatch import EmailDispatchService
    from apps.accounts.defaults import get_or_create_internal_account
    from apps.tenants.models import Tenant, TenantStatus

    tenant = Tenant.objects.create(
        account=get_or_create_internal_account(),
        name="T",
        slug="t-postal-dispatch",
        status=TenantStatus.ACTIVE,
        default_sender_email="a@b.com",
        default_sender_name="T",
    )
    msg = tenant.outbound_messages.create(
        source_app="test",
        message_type=MessageType.TRANSACTIONAL,
        to_email="x@y.com",
        subject_rendered="S",
        html_rendered="<p>x</p>",
        text_rendered="x",
        status=OutboundStatus.QUEUED,
    )

    failed = MagicMock()
    failed.success = False
    failed.provider_message_id = ""
    failed.raw_response = {"status": "error"}
    failed.error_code = "postal_error"
    failed.error_detail = "Domain not permitted"

    provider = MagicMock()
    provider.name = "postal"
    provider.send_message.return_value = failed

    with patch("apps.messages.services.dispatch.get_email_provider", return_value=provider):
        EmailDispatchService().dispatch(msg)

    msg.refresh_from_db()
    assert msg.status == OutboundStatus.FAILED
    assert msg.last_error
    assert msg.provider_message_id == ""
