from django.contrib import admin

from apps.subscriptions.models import DeliverySuppression, SuppressionRemovalLog, UnsubscribeRecord


@admin.register(DeliverySuppression)
class DeliverySuppressionAdmin(admin.ModelAdmin):
    list_display = ("email", "tenant", "reason", "created_at")


@admin.register(SuppressionRemovalLog)
class SuppressionRemovalLogAdmin(admin.ModelAdmin):
    list_display = ("email", "reason", "removed_at", "removed_by", "original_suppression_id")
    readonly_fields = (
        "original_suppression_id",
        "email",
        "tenant",
        "reason",
        "metadata_snapshot",
        "removed_at",
        "removed_by",
    )

    def has_add_permission(self, request):
        return False


@admin.register(UnsubscribeRecord)
class UnsubscribeRecordAdmin(admin.ModelAdmin):
    list_display = ("email", "tenant", "channel", "created_at")
