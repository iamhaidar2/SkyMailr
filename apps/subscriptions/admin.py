from django.contrib import admin

from apps.subscriptions.models import DeliverySuppression, UnsubscribeRecord


@admin.register(DeliverySuppression)
class DeliverySuppressionAdmin(admin.ModelAdmin):
    list_display = ("email", "tenant", "reason", "created_at")


@admin.register(UnsubscribeRecord)
class UnsubscribeRecordAdmin(admin.ModelAdmin):
    list_display = ("email", "tenant", "channel", "created_at")
