from django.contrib import admin

from apps.tenants.models import SenderProfile, Tenant, TenantAPIKey, TenantDomain


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "account",
        "status",
        "transactional_enabled",
        "marketing_enabled",
    )
    list_filter = ("status", "account")
    search_fields = ("name", "slug", "account__name", "account__slug")
    autocomplete_fields = ("account",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(TenantDomain)
class TenantDomainAdmin(admin.ModelAdmin):
    list_display = (
        "domain",
        "tenant",
        "verification_status",
        "verified",
        "is_primary",
        "spf_status",
        "dkim_status",
        "dmarc_status",
        "last_checked_at",
    )
    list_filter = ("verification_status", "verified", "is_primary")
    search_fields = ("domain", "tenant__name", "tenant__slug")


@admin.register(SenderProfile)
class SenderProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "category", "from_email", "is_default")


@admin.register(TenantAPIKey)
class TenantAPIKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "created_at", "revoked_at")
    readonly_fields = ("id", "key_hash", "created_at")
