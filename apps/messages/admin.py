from django.contrib import admin

from apps.messages.models import (
    BounceRecord,
    ComplaintRecord,
    IdempotencyKeyRecord,
    MessageEvent,
    OutboundAttempt,
    OutboundMessage,
    ProviderWebhookEvent,
)


class MessageEventInline(admin.TabularInline):
    model = MessageEvent
    extra = 0
    readonly_fields = ("event_type", "payload", "created_at")


@admin.register(OutboundMessage)
class OutboundMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "to_email", "status", "message_type", "created_at")
    list_filter = ("status", "message_type")
    search_fields = ("to_email", "subject_rendered")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [MessageEventInline]


@admin.register(OutboundAttempt)
class OutboundAttemptAdmin(admin.ModelAdmin):
    list_display = ("message", "attempt_number", "provider_name", "status", "created_at")


@admin.register(MessageEvent)
class MessageEventAdmin(admin.ModelAdmin):
    list_display = ("message", "event_type", "created_at")


@admin.register(ProviderWebhookEvent)
class ProviderWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "signature_valid", "created_at")


@admin.register(IdempotencyKeyRecord)
class IdempotencyKeyRecordAdmin(admin.ModelAdmin):
    list_display = ("tenant", "key_hash", "message", "created_at")


@admin.register(BounceRecord)
class BounceRecordAdmin(admin.ModelAdmin):
    list_display = ("email", "tenant", "bounce_type", "created_at")


@admin.register(ComplaintRecord)
class ComplaintRecordAdmin(admin.ModelAdmin):
    list_display = ("email", "tenant", "created_at")
