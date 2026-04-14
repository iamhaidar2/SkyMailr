"""
Reusable prompt builders for template / sequence LLM operations.
"""

from apps.llm.schemas import TemplateGenerationBriefSchema


def build_template_generation_system() -> str:
    return """You are an expert transactional and lifecycle email copywriter.
You output ONLY valid JSON matching the schema described by the user message.
Rules:
- Use Jinja2-style placeholders like {{ variable_name }} — double braces, names are snake_case.
- Never invent legal text, refund policies, or regulatory claims unless explicitly provided in mandatory facts.
- Do not include server-side code, Django tags, or script tags.
- Keep HTML email-safe: inline-friendly, no external scripts.
- For transactional email, prioritize clarity and brevity.
- If marketing, still avoid deceptive urgency; honor prohibited claims.
"""


def build_template_generation_user(
    tenant_name: str,
    brief: TemplateGenerationBriefSchema,
    extra_context: str = "",
) -> str:
    return f"""Generate one email template draft as JSON with keys:
subject_template, preview_text_template, html_template, text_template,
variables (array of placeholder names without braces),
required_facts, prohibited_claims_checked,
recommended_cta, tone_notes, reasoning_summary.

Tenant: {tenant_name}
Purpose: {brief.template_purpose}
Audience: {brief.audience or "general"}
Category: {brief.email_category}
Tone: {brief.tone}
Desired CTA: {brief.desired_cta}
Mandatory facts (must be reflected truthfully, not expanded): {brief.mandatory_facts}
Prohibited claims (never include): {brief.prohibited_claims}
Required variables (include all of these): {brief.required_variables}
Legal/compliance notes: {brief.legal_compliance_notes}
Brand voice notes: {brief.brand_voice_notes}
Length hint: {brief.max_length_hint}
HTML layout: {brief.html_layout_style}
Include images (placeholders only if true): {brief.include_images}
Marketing mode: {brief.is_marketing}

{extra_context}
"""


def build_template_revision_system() -> str:
    return build_template_generation_system()


def build_template_revision_user(
    tenant_name: str,
    revision_instructions: str,
    current_subject: str,
    current_html: str,
    current_text: str,
    locked_sections: list[str],
) -> str:
    locked = ", ".join(locked_sections) if locked_sections else "(none)"
    return f"""Revise the email template. Return the SAME JSON shape as generation output.

Tenant: {tenant_name}
Locked sections (do not modify content for these): {locked}

Current subject_template:
{current_subject}

Current html_template:
{current_html}

Current text_template:
{current_text}

Revision instructions:
{revision_instructions}
"""


def build_sequence_draft_system() -> str:
    return """You design onboarding / lifecycle email sequences.
Respond with JSON only: name, description, steps (array of objects with
step_order, wait_seconds, template_purpose, template_key_suggestion, notes).
wait_seconds is delay BEFORE that step's email from previous send (0 for first email).
Do not include marketing deception or invented legal claims."""


def build_sequence_draft_user(goal: str, tenant_name: str, brand_notes: str = "") -> str:
    return f"""Tenant: {tenant_name}
Brand notes: {brand_notes}

Sequence goal:
{goal}
"""
