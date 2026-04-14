import uuid

from django.db import models

from apps.email_templates.models import EmailTemplate, EmailTemplateVersion
from apps.tenants.models import SenderProfile, Tenant


class MessageType(models.TextChoices):
    TRANSACTIONAL = "transactional", "Transactional"
    LIFECYCLE = "lifecycle", "Lifecycle"
    MARKETING = "marketing", "Marketing"
    SYSTEM = "system", "System"


class MessagePriority(models.IntegerChoices):
    CRITICAL_TX = 0, "Critical transactional"
    NORMAL_TX = 1, "Normal transactional"
    LIFECYCLE = 2, "Lifecycle"
    MARKETING = 3, "Marketing"


class OutboundStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    QUEUED = "queued", "Queued"
    RENDERED = "rendered", "Rendered"
    SENDING = "sending", "Sending"
    SENT = "sent", "Sent"
    DEFERRED = "deferred", "Deferred"
    DELIVERED = "delivered", "Delivered"
    BOUNCED = "bounced", "Bounced"
    COMPLAINED = "complained", "Complained"
    FAILED = "failed", "Failed"
    SUPPRESSED = "suppressed", "Suppressed"
    CANCELLED = "cancelled", "Cancelled"


class MessageEventType(models.TextChoices):
    QUEUED = "queued", "Queued"
    RENDERED = "rendered", "Rendered"
    SENT = "sent", "Sent"
    DEFERRED = "deferred", "Deferred"
    DELIVERED = "delivered", "Delivered"
    BOUNCED = "bounced", "Bounced"
    COMPLAINED = "complained", "Complained"
    FAILED = "failed", "Failed"
    SUPPRESSED = "suppressed", "Suppressed"
    OPENED = "opened", "Opened"
    CLICKED = "clicked", "Clicked"
    UNSUBSCRIBED = "unsubscribed", "Unsubscribed"


class OutboundMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="outbound_messages")
    source_app = models.CharField(max_length=64, db_index=True)
    message_type = models.CharField(max_length=32, choices=MessageType.choices)
    template = models.ForeignKey(
        EmailTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages"
    )
    template_version = models.ForeignKey(
        EmailTemplateVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    sender_profile = models.ForeignKey(
        SenderProfile, on_delete=models.SET_NULL, null=True, blank=True
    )
    to_email = models.EmailField(db_index=True)
    to_name = models.CharField(max_length=200, blank=True)
    cc = models.JSONField(default=list, blank=True)
    bcc = models.JSONField(default=list, blank=True)
    reply_to = models.EmailField(blank=True)
    subject_rendered = models.TextField(blank=True)
    html_rendered = models.TextField(blank=True)
    text_rendered = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=dict, blank=True)
    priority = models.PositiveSmallIntegerField(
        choices=MessagePriority.choices, default=MessagePriority.NORMAL_TX
    )
    scheduled_for = models.DateTimeField(null=True, blank=True, db_index=True)
    send_after = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=OutboundStatus.choices,
        default=OutboundStatus.QUEUED,
        db_index=True,
    )
    provider_name = models.CharField(max_length=64, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=128, blank=True, db_index=True)
    workflow_execution = models.ForeignKey(
        "skymailr_workflows.WorkflowExecution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    retry_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status", "created_at"]),
            models.Index(fields=["tenant", "to_email", "status"]),
            models.Index(fields=["status", "scheduled_for"]),
        ]

    def __str__(self):
        return f"{self.id} -> {self.to_email}"


class OutboundAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        OutboundMessage, on_delete=models.CASCADE, related_name="attempts"
    )
    attempt_number = models.PositiveIntegerField()
    provider_name = models.CharField(max_length=64)
    status = models.CharField(max_length=32)
    provider_message_id = models.CharField(max_length=255, blank=True)
    error_code = models.CharField(max_length=128, blank=True)
    error_detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["message", "attempt_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["message", "attempt_number"],
                name="uniq_attempt_per_message",
            )
        ]


class MessageEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        OutboundMessage, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=32, choices=MessageEventType.choices, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["message", "event_type", "created_at"]),
        ]


class ProviderWebhookEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=64, db_index=True)
    raw_body = models.TextField()
    headers = models.JSONField(default=dict, blank=True)
    signature_valid = models.BooleanField(default=False)
    normalized = models.JSONField(default=dict, blank=True)
    processing_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class IdempotencyKeyRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="idempotency_keys")
    key_hash = models.CharField(max_length=128, db_index=True)
    message = models.OneToOneField(
        OutboundMessage, on_delete=models.CASCADE, related_name="idempotency_record"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key_hash"], name="uniq_idempotency_per_tenant")
        ]


class BounceRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="bounces")
    email = models.EmailField(db_index=True)
    message = models.ForeignKey(
        OutboundMessage, on_delete=models.SET_NULL, null=True, blank=True
    )
    bounce_type = models.CharField(max_length=32, default="hard")
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["tenant", "email"])]


class ComplaintRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="complaints")
    email = models.EmailField(db_index=True)
    message = models.ForeignKey(
        OutboundMessage, on_delete=models.SET_NULL, null=True, blank=True
    )
    feedback_type = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
