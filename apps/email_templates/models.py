import uuid

from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class TemplateCategory(models.TextChoices):
    TRANSACTIONAL = "transactional", "Transactional"
    LIFECYCLE = "lifecycle", "Lifecycle"
    MARKETING = "marketing", "Marketing"
    SYSTEM = "system", "System"


class TemplateStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class VersionSourceType(models.TextChoices):
    MANUAL = "manual", "Manual"
    LLM_GENERATED = "llm_generated", "LLM generated"
    LLM_REVISED = "llm_revised", "LLM revised"
    SEEDED = "seeded", "Seeded"


class CreatedByType(models.TextChoices):
    SYSTEM = "system", "System"
    USER = "user", "User"
    LLM = "llm", "LLM"


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class EmailTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="email_templates")
    key = models.SlugField(max_length=128)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=32, choices=TemplateCategory.choices)
    status = models.CharField(
        max_length=32, choices=TemplateStatus.choices, default=TemplateStatus.DRAFT
    )
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    sends_total = models.PositiveIntegerField(default=0)
    delivered_total = models.PositiveIntegerField(default=0)
    opens_total = models.PositiveIntegerField(default=0)
    clicks_total = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant", "key"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key"], name="uniq_template_key_per_tenant")
        ]

    def __str__(self):
        return f"{self.tenant.slug}:{self.key}"

    @property
    def current_approved_version(self):
        return self.versions.filter(is_current_approved=True).order_by("-version_number").first()


class TemplateVariable(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        EmailTemplate, on_delete=models.CASCADE, related_name="variables"
    )
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=500, blank=True)
    is_required = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["template", "name"], name="uniq_var_per_template")
        ]

    def __str__(self):
        return f"{self.template.key}.{self.name}"


class EmailTemplateVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        EmailTemplate, on_delete=models.CASCADE, related_name="versions"
    )
    version_number = models.PositiveIntegerField()
    created_by_type = models.CharField(
        max_length=16, choices=CreatedByType.choices, default=CreatedByType.SYSTEM
    )
    source_type = models.CharField(
        max_length=32, choices=VersionSourceType.choices, default=VersionSourceType.MANUAL
    )
    subject_template = models.TextField()
    preview_text_template = models.TextField(blank=True)
    html_template = models.TextField()
    text_template = models.TextField(blank=True)
    subject_variants = models.JSONField(
        default=list,
        blank=True,
        help_text="Optional A/B subject line variants (list of template strings).",
    )
    design_schema = models.JSONField(default=dict, blank=True)
    compliance_flags = models.JSONField(default=dict, blank=True)
    locked_sections = models.JSONField(
        default=list,
        blank=True,
        help_text="Sections LLM must not edit: header, body, cta, footer, compliance.",
    )
    changelog = models.TextField(blank=True)
    llm_prompt = models.TextField(blank=True)
    model_used = models.CharField(max_length=128, blank=True)
    generation_params = models.JSONField(default=dict, blank=True)
    approval_status = models.CharField(
        max_length=16, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_template_versions",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    archived = models.BooleanField(default=False)
    is_current_approved = models.BooleanField(
        default=False,
        help_text="The single version used for sending (approved, active).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["template", "-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["template", "version_number"],
                name="uniq_version_number_per_template",
            ),
            models.UniqueConstraint(
                fields=["template"],
                condition=models.Q(is_current_approved=True),
                name="uniq_current_approved_per_template",
            ),
        ]

    def __str__(self):
        return f"{self.template.key} v{self.version_number}"


class TemplateApproval(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(
        EmailTemplateVersion, on_delete=models.CASCADE, related_name="approval_events"
    )
    action = models.CharField(max_length=32)
    note = models.TextField(blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class TemplateRenderLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template_version = models.ForeignKey(
        EmailTemplateVersion, on_delete=models.CASCADE, related_name="render_logs"
    )
    context_snapshot = models.JSONField(default=dict)
    subject_rendered = models.TextField(blank=True)
    html_rendered = models.TextField(blank=True)
    text_rendered = models.TextField(blank=True)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class LLMGenerationRecord(models.Model):
    """Audit trail for LLM template/sequence generations (never used for sending)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="llm_generations")
    operation = models.CharField(max_length=64)
    prompt = models.TextField()
    model = models.CharField(max_length=128)
    temperature = models.FloatField(default=0.4)
    raw_output = models.TextField(blank=True)
    parsed_output = models.JSONField(default=dict, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    validation_status = models.CharField(max_length=32, default="pending")
    failure_reason = models.TextField(blank=True)
    template_version = models.ForeignKey(
        "EmailTemplateVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="llm_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
