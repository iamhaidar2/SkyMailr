from django.contrib import admin

from apps.email_templates.models import (
    EmailTemplate,
    EmailTemplateVersion,
    LLMGenerationRecord,
    TemplateApproval,
    TemplateRenderLog,
    TemplateVariable,
)


class TemplateVariableInline(admin.TabularInline):
    model = TemplateVariable
    extra = 0


class EmailTemplateVersionInline(admin.TabularInline):
    model = EmailTemplateVersion
    extra = 0
    readonly_fields = ("version_number", "approval_status", "created_at")
    show_change_link = True


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "tenant", "category", "status")
    list_filter = ("category", "status")
    search_fields = ("key", "name")
    inlines = [TemplateVariableInline, EmailTemplateVersionInline]


@admin.register(EmailTemplateVersion)
class EmailTemplateVersionAdmin(admin.ModelAdmin):
    list_display = ("template", "version_number", "approval_status", "source_type", "created_at")
    list_filter = ("approval_status", "source_type")
    readonly_fields = ("id", "created_at")


@admin.register(TemplateApproval)
class TemplateApprovalAdmin(admin.ModelAdmin):
    list_display = ("version", "action", "created_at")


@admin.register(TemplateRenderLog)
class TemplateRenderLogAdmin(admin.ModelAdmin):
    list_display = ("template_version", "success", "created_at")


@admin.register(LLMGenerationRecord)
class LLMGenerationRecordAdmin(admin.ModelAdmin):
    list_display = ("operation", "tenant", "model", "validation_status", "created_at")
    list_filter = ("validation_status", "operation")
