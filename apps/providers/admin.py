from django.contrib import admin

from apps.providers.models import DummyStoredEmail


@admin.register(DummyStoredEmail)
class DummyStoredEmailAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at")
    readonly_fields = ("id", "payload", "created_at")
