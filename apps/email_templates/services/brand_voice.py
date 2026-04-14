from apps.tenants.models import Tenant


class BrandVoiceService:
    """Surface tenant LLM + branding hints for prompts."""

    @staticmethod
    def notes(tenant: Tenant) -> str:
        d = tenant.llm_defaults or {}
        parts = [
            d.get("tone_profile", ""),
            d.get("brand_voice_notes", ""),
        ]
        return "\n".join(p for p in parts if p)
