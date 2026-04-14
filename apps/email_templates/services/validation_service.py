from apps.email_templates.models import EmailTemplate


class TemplateValidationService:
    """Placeholder / variable validation against template definitions."""

    @staticmethod
    def required_variable_names(template: EmailTemplate) -> list[str]:
        return list(
            template.variables.filter(is_required=True).values_list("name", flat=True)
        )

    @staticmethod
    def all_variable_names(template: EmailTemplate) -> list[str]:
        return list(template.variables.values_list("name", flat=True))

    @staticmethod
    def validate_context(template: EmailTemplate, context: dict) -> None:
        missing = [
            name
            for name in TemplateValidationService.required_variable_names(template)
            if context.get(name) in (None, "")
        ]
        if missing:
            raise ValueError(f"Missing required template variables: {missing}")
