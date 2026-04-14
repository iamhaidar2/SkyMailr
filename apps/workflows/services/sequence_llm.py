from apps.llm.prompts.template_prompts import build_sequence_draft_system, build_sequence_draft_user
from apps.llm.router import get_llm_client
from apps.llm.schemas import SequenceDraftOutputSchema
from apps.tenants.models import Tenant


class SequenceLLMService:
    def draft_sequence(self, *, tenant: Tenant, goal: str) -> SequenceDraftOutputSchema:
        client = get_llm_client()
        model = (tenant.llm_defaults or {}).get("default_model") or "gpt-4o-mini"
        temp = float((tenant.llm_defaults or {}).get("temperature", 0.4))
        system = build_sequence_draft_system()
        user = build_sequence_draft_user(
            goal, tenant.name, brand_notes=(tenant.llm_defaults or {}).get("brand_voice_notes", "")
        )
        parsed, _ = client.complete_json(
            system_prompt=system,
            user_prompt=user,
            model=model,
            temperature=temp,
        )
        return SequenceDraftOutputSchema.model_validate(parsed)
