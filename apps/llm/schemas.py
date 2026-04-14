from typing import Any

from pydantic import BaseModel, Field, field_validator


class TemplateGenerationBriefSchema(BaseModel):
    """Structured brief for LLM template generation (API/management)."""

    template_purpose: str
    audience: str = ""
    email_category: str = "transactional"
    tone: str = "professional"
    desired_cta: str = ""
    mandatory_facts: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)
    required_variables: list[str] = Field(default_factory=list)
    legal_compliance_notes: str = ""
    brand_voice_notes: str = ""
    max_length_hint: str = "medium"
    html_layout_style: str = "single_column"
    include_images: bool = False
    is_marketing: bool = False


class TemplateGenerationOutputSchema(BaseModel):
    """Strict structured output for template drafts — validated before persisting."""

    subject_template: str
    preview_text_template: str = ""
    html_template: str
    text_template: str = ""
    variables: list[str] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    prohibited_claims_checked: list[str] = Field(default_factory=list)
    recommended_cta: str = ""
    tone_notes: str = ""
    reasoning_summary: str = ""

    @field_validator("html_template")
    @classmethod
    def html_non_empty(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("html_template must not be empty")
        return v


class SubjectVariantOutputSchema(BaseModel):
    subjects: list[str] = Field(min_length=1)


class SequenceStepDraftSchema(BaseModel):
    step_order: int
    wait_seconds: int = 0
    template_purpose: str
    template_key_suggestion: str = ""
    notes: str = ""


class SequenceDraftOutputSchema(BaseModel):
    name: str
    description: str = ""
    steps: list[SequenceStepDraftSchema] = Field(default_factory=list)


def parse_json_safe(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    raise TypeError("Expected dict payload")
