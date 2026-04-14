from typing import Any

from apps.llm.base import BaseLLMClient


class DummyLLMClient(BaseLLMClient):
    """Deterministic JSON for tests and offline development."""

    name = "dummy"

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float = 0.3,
        timeout_seconds: float = 120,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        out = {
            "subject_template": "Hello {{ user_name }}",
            "preview_text_template": "Quick update from our team.",
            "html_template": "<p>Hi {{ user_name }},</p><p>This is a dummy template body.</p>",
            "text_template": "Hi {{ user_name }},\n\nThis is a dummy template body.",
            "variables": ["user_name"],
            "required_facts": [],
            "prohibited_claims_checked": [],
            "recommended_cta": "Open the app",
            "tone_notes": "neutral",
            "reasoning_summary": "dummy provider",
        }
        return out, {"prompt_tokens": 0, "completion_tokens": 0}
