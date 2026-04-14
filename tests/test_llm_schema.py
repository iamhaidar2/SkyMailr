import pytest

from apps.llm.schemas import TemplateGenerationOutputSchema


def test_template_generation_schema_accepts_valid():
    data = {
        "subject_template": "Hi {{ name }}",
        "preview_text_template": "x",
        "html_template": "<p>{{ name }}</p>",
        "text_template": "{{ name }}",
        "variables": ["name"],
        "required_facts": [],
        "prohibited_claims_checked": [],
        "recommended_cta": "Go",
        "tone_notes": "",
        "reasoning_summary": "",
    }
    m = TemplateGenerationOutputSchema.model_validate(data)
    assert m.subject_template.startswith("Hi")


def test_template_generation_schema_rejects_empty_html():
    with pytest.raises(Exception):
        TemplateGenerationOutputSchema.model_validate(
            {"subject_template": "x", "html_template": ""}
        )
