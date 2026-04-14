import pytest
from rest_framework.test import APIClient

from apps.email_templates.models import TemplateVariable


@pytest.mark.django_db
def test_send_template_idempotent(api_key, approved_template):
    tpl, _ = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=False)
    client = APIClient()
    url = "/api/v1/messages/send-template/"
    body = {
        "template_key": "email_verification",
        "to_email": "u@example.com",
        "context": {"user_name": "Bob"},
        "source_app": "tests",
        "message_type": "transactional",
        "idempotency_key": "idem-1",
    }
    r1 = client.post(url, body, HTTP_AUTHORIZATION=f"Bearer {api_key}", format="json")
    assert r1.status_code == 201
    r2 = client.post(url, body, HTTP_AUTHORIZATION=f"Bearer {api_key}", format="json")
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
