import pytest

from apps.email_templates.models import TemplateVariable
from apps.email_templates.services.render_service import render_email_version, TemplateRenderError


@pytest.mark.django_db
def test_render_success(approved_template):
    tpl, ver = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=True)
    out = render_email_version(
        subject_template=ver.subject_template,
        preview_template=ver.preview_text_template,
        html_template=ver.html_template,
        text_template=ver.text_template,
        context={"user_name": "Ada"},
        sanitize=True,
    )
    assert "Ada" in out["html"]


@pytest.mark.django_db
def test_render_missing_variable(approved_template):
    tpl, ver = approved_template
    TemplateVariable.objects.create(template=tpl, name="user_name", is_required=True)
    with pytest.raises(TemplateRenderError):
        render_email_version(
            subject_template=ver.subject_template,
            preview_template="",
            html_template=ver.html_template,
            text_template="",
            context={},
            sanitize=True,
        )


def test_render_lenient_undefined_fills_missing_with_empty():
    """Draft preview uses lenient Jinja so undeclared {{ vars }} do not hard-fail."""
    out = render_email_version(
        subject_template="Hi {{ missing }}",
        preview_template="",
        html_template="<p>{{ foo }}</p>",
        text_template="",
        context={},
        sanitize=False,
        strict_undefined=False,
    )
    assert out["subject"] == "Hi"  # stripped; missing var renders empty
    assert "<p></p>" in out["html"] or out["html"] == "<p></p>"
