from django.contrib import admin

from apps.workflows.models import (
    ScheduledSendWindow,
    Workflow,
    WorkflowEnrollment,
    WorkflowExecution,
    WorkflowStep,
    WorkflowStepRun,
)


class WorkflowStepInline(admin.TabularInline):
    model = WorkflowStep
    extra = 0


@admin.register(Workflow)
class WorkflowAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "tenant", "is_active")
    inlines = [WorkflowStepInline]


@admin.register(WorkflowStep)
class WorkflowStepAdmin(admin.ModelAdmin):
    list_display = ("workflow", "order", "step_type")


@admin.register(WorkflowEnrollment)
class WorkflowEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("workflow", "recipient_email", "status", "created_at")


@admin.register(WorkflowExecution)
class WorkflowExecutionAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "status", "next_run_at", "started_at")


@admin.register(WorkflowStepRun)
class WorkflowStepRunAdmin(admin.ModelAdmin):
    list_display = ("execution", "step", "status", "run_at")


@admin.register(ScheduledSendWindow)
class ScheduledSendWindowAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant")
