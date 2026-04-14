import uuid

from django.db import models

from apps.email_templates.models import EmailTemplate
from apps.tenants.models import Tenant


class WorkflowStepType(models.TextChoices):
    SEND_TEMPLATE = "send_template", "Send template"
    WAIT_DURATION = "wait_duration", "Wait duration"
    CONDITIONAL_BRANCH = "conditional_branch", "Conditional branch"
    SET_TAG = "set_tag", "Set tag"
    UNSUBSCRIBE_IF_CONDITION = "unsubscribe_if_condition", "Unsubscribe if condition"
    END = "end", "End"


class EnrollmentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class ExecutionStatus(models.TextChoices):
    RUNNING = "running", "Running"
    WAITING = "waiting", "Waiting"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class Workflow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="workflows")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=128)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant", "slug"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "slug"], name="uniq_workflow_slug_per_tenant")
        ]

    def __str__(self):
        return f"{self.tenant.slug}:{self.slug}"


class WorkflowStep(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveIntegerField()
    step_type = models.CharField(max_length=64, choices=WorkflowStepType.choices)
    template = models.ForeignKey(
        EmailTemplate, on_delete=models.SET_NULL, null=True, blank=True
    )
    template_key = models.CharField(
        max_length=128,
        blank=True,
        help_text="Fallback lookup if template FK not set.",
    )
    wait_seconds = models.PositiveIntegerField(null=True, blank=True)
    condition = models.JSONField(default=dict, blank=True)
    tag_value = models.CharField(max_length=120, blank=True)
    next_step = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["workflow", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "order"], name="uniq_step_order_per_workflow"
            )
        ]


class WorkflowEnrollment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="enrollments")
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="enrollments")
    recipient_email = models.EmailField(db_index=True)
    recipient_name = models.CharField(max_length=200, blank=True)
    external_user_id = models.CharField(max_length=128, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=32, choices=EnrollmentStatus.choices, default=EnrollmentStatus.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "workflow", "recipient_email"]),
        ]


class WorkflowExecution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enrollment = models.OneToOneField(
        WorkflowEnrollment, on_delete=models.CASCADE, related_name="execution"
    )
    status = models.CharField(
        max_length=32, choices=ExecutionStatus.choices, default=ExecutionStatus.RUNNING
    )
    current_step = models.ForeignKey(
        WorkflowStep, on_delete=models.SET_NULL, null=True, blank=True
    )
    state = models.JSONField(default=dict, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status", "next_run_at"]),
        ]


class WorkflowStepRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.ForeignKey(
        WorkflowExecution, on_delete=models.CASCADE, related_name="step_runs"
    )
    step = models.ForeignKey(WorkflowStep, on_delete=models.CASCADE)
    status = models.CharField(max_length=32)
    detail = models.TextField(blank=True)
    run_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["run_at"]


class ScheduledSendWindow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="send_windows")
    name = models.CharField(max_length=120)
    weekdays = models.JSONField(default=list, help_text="0=Monday .. 6=Sunday")
    start_hour_local = models.PositiveSmallIntegerField(default=9)
    end_hour_local = models.PositiveSmallIntegerField(default=17)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.tenant.slug}:{self.name}"
