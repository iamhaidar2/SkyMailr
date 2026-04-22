from rest_framework import serializers

from apps.email_templates.models import EmailTemplate, EmailTemplateVersion
from apps.messages.models import OutboundMessage

# API clients must not set internal dispatch flags via metadata.
_FORBIDDEN_METADATA_KEYS = frozenset({"bypass_domain_verification"})


def _sanitize_api_metadata(meta: dict) -> dict:
    if not meta:
        return {}
    return {k: v for k, v in meta.items() if k not in _FORBIDDEN_METADATA_KEYS}


class SendTemplateSerializer(serializers.Serializer):
    template_key = serializers.SlugField()
    to_email = serializers.EmailField()
    to_name = serializers.CharField(required=False, default="")
    message_type = serializers.CharField(default="transactional")
    context = serializers.DictField(default=dict)
    metadata = serializers.DictField(required=False, default=dict)
    tags = serializers.DictField(required=False, default=dict)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)
    scheduled_for = serializers.DateTimeField(required=False, allow_null=True)
    source_app = serializers.CharField(default="unknown")

    def validate_metadata(self, value):
        return _sanitize_api_metadata(value or {})


class SendRawSerializer(serializers.Serializer):
    to_email = serializers.EmailField()
    to_name = serializers.CharField(required=False, default="")
    subject = serializers.CharField()
    html_body = serializers.CharField()
    text_body = serializers.CharField(required=False, default="")
    message_type = serializers.CharField(default="transactional")
    metadata = serializers.DictField(required=False, default=dict)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)
    source_app = serializers.CharField(default="unknown")

    def validate_metadata(self, value):
        return _sanitize_api_metadata(value or {})


class TemplateGenerateSerializer(serializers.Serializer):
    template_key = serializers.SlugField()
    name = serializers.CharField()
    category = serializers.CharField()
    brief = serializers.DictField()


class TemplateReviseSerializer(serializers.Serializer):
    instructions = serializers.CharField()


class ApproveVersionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, default="")


class PreviewSerializer(serializers.Serializer):
    context = serializers.DictField(default=dict)


class WorkflowEnrollSerializer(serializers.Serializer):
    recipient_email = serializers.EmailField()
    recipient_name = serializers.CharField(required=False, default="")
    external_user_id = serializers.CharField(required=False, default="")
    metadata = serializers.DictField(required=False, default=dict)


class UnsubscribeSerializer(serializers.Serializer):
    email = serializers.EmailField()
    channel = serializers.CharField(default="marketing")


class OutboundMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = OutboundMessage
        fields = [
            "id",
            "source_app",
            "message_type",
            "to_email",
            "status",
            "subject_rendered",
            "last_error",
            "provider_name",
            "provider_message_id",
            "created_at",
        ]


class EmailTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = [
            "id",
            "key",
            "name",
            "category",
            "status",
            "description",
            "tags",
            "created_at",
        ]


class EmailTemplateVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplateVersion
        fields = [
            "id",
            "version_number",
            "approval_status",
            "source_type",
            "subject_template",
            "preview_text_template",
            "created_at",
        ]
