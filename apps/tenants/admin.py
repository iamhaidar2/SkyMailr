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
        "postal_provision_status",
        "postal_provision_last_attempt_at",
        "dns_source",
        "dns_last_synced_at",
        "spf_status",
        "dkim_status",
        "dmarc_status",
        "last_checked_at",
    )
    list_filter = ("verification_status", "verified", "is_primary", "dns_source", "postal_provision_status")
    search_fields = ("domain", "tenant__name", "tenant__slug")
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "tenant",
                    "domain",
                    "verified",
                    "is_primary",
                    "verification_status",
                    "spf_status",
                    "dkim_status",
                    "dmarc_status",
                    "last_checked_at",
                    "verification_notes",
                    "postal_provision_status",
                    "postal_provision_error",
                    "postal_provision_last_attempt_at",
                    "postal_provider_domain_id",
                )
            },
        ),
        (
            "Expected DNS (provider / overrides)",
            {
                "fields": (
                    "spf_txt_expected",
                    "dkim_selector",
                    "dkim_txt_value",
                    "return_path_cname_name",
                    "return_path_cname_target",
                    "dmarc_txt_expected",
                    "postal_verification_txt_expected",
                    "postal_verification_bridge_at",
                    "dns_source",
                    "dns_last_synced_at",
                ),
                "description": "Leave blank when unknown. Do not paste placeholder tokens — use NULL and set dns source to Unknown.",
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(SenderProfile)
class SenderProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "category", "from_email", "is_default")


@admin.register(TenantAPIKey)
class TenantAPIKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "created_at", "revoked_at")
    readonly_fields = ("id", "key_hash", "created_at")
