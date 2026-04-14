from django.contrib import admin

from apps.tenants.models import SenderProfile, Tenant, TenantAPIKey, TenantDomain


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "status", "transactional_enabled", "marketing_enabled")
    search_fields = ("name", "slug")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(TenantDomain)
class TenantDomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "verified", "is_primary")


@admin.register(SenderProfile)
class SenderProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "category", "from_email", "is_default")


@admin.register(TenantAPIKey)
class TenantAPIKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "created_at", "revoked_at")
    readonly_fields = ("id", "key_hash", "created_at")
