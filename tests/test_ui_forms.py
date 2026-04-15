"""Operator UI form validation (no DB for pure form tests)."""

from apps.ui.forms import SendRawForm, SendTemplateForm


def test_json_object_field_empty_metadata_raw_send():
    """Regression: JsonObjectField must use Field.clean(self, value), not clean(self)."""
    f = SendRawForm(
        data={
            "source_app": "operator_ui",
            "message_type": "transactional",
            "to_email": "user@example.com",
            "to_name": "",
            "subject": "Test",
            "html_body": "<p>Hi</p>",
            "text_body": "",
            "metadata": "",
            "idempotency_key": "",
            "sender_profile": "",
        }
    )
    assert f.is_valid(), f.errors
    assert f.cleaned_data["metadata"] == {}


def test_json_object_field_object_metadata_raw_send():
    f = SendRawForm(
        data={
            "source_app": "operator_ui",
            "message_type": "transactional",
            "to_email": "user@example.com",
            "subject": "Test",
            "html_body": "<p>Hi</p>",
            "metadata": '{"foo": 1}',
            "sender_profile": "",
        }
    )
    assert f.is_valid(), f.errors
    assert f.cleaned_data["metadata"] == {"foo": 1}


def test_send_template_form_json_fields():
    f = SendTemplateForm(
        data={
            "template_key": "t",
            "source_app": "operator_ui",
            "message_type": "transactional",
            "to_email": "u@example.com",
            "context": "{}",
            "metadata": "",
            "tags": "{}",
            "sender_profile": "",
        }
    )
    assert f.is_valid(), f.errors
    assert f.cleaned_data["context"] == {}
    assert f.cleaned_data["metadata"] == {}
    assert f.cleaned_data["tags"] == {}
