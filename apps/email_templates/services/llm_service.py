import logging

from django.db import transaction
from django.db.models import Max

from apps.email_templates.models import (
    ApprovalStatus,
    CreatedByType,
    EmailTemplate,
    EmailTemplateVersion,
    LLMGenerationRecord,
    TemplateVariable,
    VersionSourceType,
)
from apps.llm.prompts.template_prompts import (
    build_template_generation_system,
    build_template_generation_user,
    build_template_revision_system,
    build_template_revision_user,
)
from apps.llm.router import get_llm_client
from apps.llm.schemas import TemplateGenerationBriefSchema, TemplateGenerationOutputSchema
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)


def _default_model_for_tenant(tenant: Tenant) -> str:
    from django.conf import settings

    d = tenant.llm_defaults or {}
    return d.get("default_model") or getattr(
        settings, "SKYMAILR_DEFAULT_LLM_MODEL", "gpt-4o-mini"
    )


def _temperature_for_tenant(tenant: Tenant) -> float:
    d = tenant.llm_defaults or {}
    try:
        return float(d.get("temperature", 0.35))
    except (TypeError, ValueError):
        return 0.35


class TemplateLLMService:
    """LLM-assisted drafts — never sends email."""

    def __init__(self):
        self.client = get_llm_client()

    def generate_draft_version(
        self,
        *,
        template: EmailTemplate,
        brief: TemplateGenerationBriefSchema,
        created_by_llm: bool = True,
    ) -> EmailTemplateVersion:
        tenant = template.tenant
        model = _default_model_for_tenant(tenant)
        temp = _temperature_for_tenant(tenant)
        extra = ""
        voice = (tenant.llm_defaults or {}).get("brand_voice_notes") or ""
        if voice:
            extra = f"Tenant brand voice notes: {voice}"

        system = build_template_generation_system()
        user = build_template_generation_user(tenant.name, brief, extra_context=extra)

        parsed, usage = self.client.complete_json(
            system_prompt=system,
            user_prompt=user,
            model=model,
            temperature=temp,
        )
        raw = str(parsed)
        try:
            validated = TemplateGenerationOutputSchema.model_validate(parsed)
        except Exception as e:
            LLMGenerationRecord.objects.create(
                tenant=tenant,
                operation="template_generate",
                prompt=user[:20000],
                model=model,
                temperature=temp,
                raw_output=raw,
                validation_status="invalid",
                failure_reason=str(e),
            )
            raise

        with transaction.atomic():
            next_v = (
                EmailTemplateVersion.objects.filter(template=template).aggregate(
                    m=Max("version_number")
                )["m"]
                or 0
            ) + 1
            version = EmailTemplateVersion.objects.create(
                template=template,
                version_number=next_v,
                created_by_type=CreatedByType.LLM if created_by_llm else CreatedByType.USER,
                source_type=VersionSourceType.LLM_GENERATED,
                subject_template=validated.subject_template,
                preview_text_template=validated.preview_text_template,
                html_template=validated.html_template,
                text_template=validated.text_template,
                llm_prompt=user[:50000],
                model_used=model,
                generation_params={"temperature": temp},
                approval_status=ApprovalStatus.PENDING,
                changelog=validated.reasoning_summary[:2000],
            )
            LLMGenerationRecord.objects.create(
                tenant=tenant,
                operation="template_generate",
                prompt=user[:20000],
                model=model,
                temperature=temp,
                raw_output=raw,
                parsed_output=validated.model_dump(),
                token_usage=usage,
                validation_status="ok",
                template_version=version,
            )
            req = set(brief.required_variables or [])
            for var in validated.variables:
                TemplateVariable.objects.update_or_create(
                    template=template,
                    name=var,
                    defaults={"is_required": var in req},
                )
        return version

    def revise_template_version(
        self,
        *,
        template: EmailTemplate,
        base_version: EmailTemplateVersion,
        instructions: str,
    ) -> EmailTemplateVersion:
        tenant = template.tenant
        model = _default_model_for_tenant(tenant)
        temp = _temperature_for_tenant(tenant)
        system = build_template_revision_system()
        user = build_template_revision_user(
            tenant.name,
            instructions,
            base_version.subject_template,
            base_version.html_template,
            base_version.text_template,
            list(base_version.locked_sections or []),
        )
        parsed, usage = self.client.complete_json(
            system_prompt=system,
            user_prompt=user,
            model=model,
            temperature=temp,
        )
        raw = str(parsed)
        try:
            validated = TemplateGenerationOutputSchema.model_validate(parsed)
        except Exception as e:
            LLMGenerationRecord.objects.create(
                tenant=tenant,
                operation="template_revise",
                prompt=user[:20000],
                model=model,
                temperature=temp,
                raw_output=raw,
                validation_status="invalid",
                failure_reason=str(e),
            )
            raise

        with transaction.atomic():
            next_v = (
                EmailTemplateVersion.objects.filter(template=template).aggregate(
                    m=Max("version_number")
                )["m"]
                or 0
            ) + 1
            version = EmailTemplateVersion.objects.create(
                template=template,
                version_number=next_v,
                created_by_type=CreatedByType.LLM,
                source_type=VersionSourceType.LLM_REVISED,
                subject_template=validated.subject_template,
                preview_text_template=validated.preview_text_template,
                html_template=validated.html_template,
                text_template=validated.text_template,
                locked_sections=base_version.locked_sections,
                llm_prompt=user[:50000],
                model_used=model,
                generation_params={"temperature": temp},
                approval_status=ApprovalStatus.PENDING,
                changelog=validated.reasoning_summary[:2000],
            )
            LLMGenerationRecord.objects.create(
                tenant=tenant,
                operation="template_revise",
                prompt=user[:20000],
                model=model,
                temperature=temp,
                raw_output=raw,
                parsed_output=validated.model_dump(),
                token_usage=usage,
                validation_status="ok",
                template_version=version,
            )
        return version
