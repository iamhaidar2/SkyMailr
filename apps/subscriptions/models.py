import uuid

from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class SuppressionReason(models.TextChoices):
    HARD_BOUNCE = "hard_bounce", "Hard bounce"
    COMPLAINT = "complaint", "Complaint"
    MANUAL = "manual", "Manual"
    UNSUBSCRIBE = "unsubscribe", "Unsubscribe"


class SuppressionRemovalLog(models.Model):
    """Audit trail when an operator or API client removes a DeliverySuppression."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    original_suppression_id = models.UUIDField(db_index=True)
    email = models.EmailField(db_index=True)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reason = models.CharField(max_length=32)
    metadata_snapshot = models.JSONField(default=dict, blank=True)
    removed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-removed_at"]


class DeliverySuppression(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="suppressions", null=True, blank=True
    )
    email = models.EmailField(db_index=True)
    reason = models.CharField(max_length=32, choices=SuppressionReason.choices)
    applies_to_marketing = models.BooleanField(default=True)
    applies_to_transactional = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email", "created_at"]),
            models.Index(fields=["tenant", "email"]),
        ]


class UnsubscribeRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="unsubscribes")
    email = models.EmailField(db_index=True)
    channel = models.CharField(max_length=64, default="marketing")
    source = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "email", "channel"],
                name="uniq_unsub_per_tenant_email_channel",
            )
        ]
