from django.contrib import admin
from django.contrib.auth import get_user_model
from django.utils.html import format_html

from apps.accounts.models import Account, AccountInvite, AccountMembership


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "status",
        "plan_code",
        "billing_email",
        "tenant_count",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("name", "slug", "billing_email", "plan_code")
    readonly_fields = ("id", "created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (
        (None, {"fields": ("id", "name", "slug", "status")}),
        ("Billing / plan", {"fields": ("billing_email", "plan_code", "metadata")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Tenants")
    def tenant_count(self, obj: Account) -> str:
        n = obj.tenants.count()
        return format_html("<span>{}</span>", n)


@admin.register(AccountMembership)
class AccountMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "account", "role", "is_active", "created_at")
    list_filter = ("role", "is_active", "account")
    search_fields = (
        "user__username",
        "user__email",
        "account__name",
        "account__slug",
    )
    autocomplete_fields = ("user", "account")
    readonly_fields = ("id", "created_at", "updated_at")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = get_user_model().objects.order_by("username")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(AccountInvite)
class AccountInviteAdmin(admin.ModelAdmin):
    list_display = ("email", "account", "role", "status", "expires_at", "created_at")
    list_filter = ("status", "role", "account")
    search_fields = ("email", "account__name", "account__slug")
    readonly_fields = ("id", "token_hash", "created_at", "updated_at", "accepted_at")
