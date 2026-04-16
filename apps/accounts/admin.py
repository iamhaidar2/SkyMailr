import logging

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.utils.html import format_html

from apps.accounts.models import Account, AccountInvite, AccountMembership, AccountStatus
from apps.accounts.plans import PLAN_FREE, PLAN_GROWTH, PLAN_INTERNAL, PLAN_STARTER

logger = logging.getLogger("apps.accounts.audit")


@admin.action(description="Suspend selected accounts")
def account_admin_suspend(modeladmin, request, queryset):
    for acc in queryset:
        if acc.status != AccountStatus.SUSPENDED:
            acc.status = AccountStatus.SUSPENDED
            acc.save(update_fields=["status", "updated_at"])
            logger.info(
                "admin_account_suspend account_id=%s by_user_id=%s",
                acc.id,
                request.user.pk,
            )


@admin.action(description="Reactivate selected accounts")
def account_admin_reactivate(modeladmin, request, queryset):
    for acc in queryset:
        if acc.status != AccountStatus.ACTIVE:
            acc.status = AccountStatus.ACTIVE
            acc.save(update_fields=["status", "updated_at"])
            logger.info(
                "admin_account_reactivate account_id=%s by_user_id=%s",
                acc.id,
                request.user.pk,
            )


def _set_plan(modeladmin, request, queryset, plan_code: str):
    for acc in queryset:
        if acc.plan_code != plan_code:
            acc.plan_code = plan_code
            acc.save(update_fields=["plan_code", "updated_at"])
            logger.info(
                "admin_account_set_plan account_id=%s plan=%s by_user_id=%s",
                acc.id,
                plan_code,
                request.user.pk,
            )


@admin.action(description="Set plan: Free")
def account_admin_set_plan_free(modeladmin, request, queryset):
    _set_plan(modeladmin, request, queryset, PLAN_FREE)


@admin.action(description="Set plan: Starter")
def account_admin_set_plan_starter(modeladmin, request, queryset):
    _set_plan(modeladmin, request, queryset, PLAN_STARTER)


@admin.action(description="Set plan: Growth")
def account_admin_set_plan_growth(modeladmin, request, queryset):
    _set_plan(modeladmin, request, queryset, PLAN_GROWTH)


@admin.action(description="Set plan: Internal")
def account_admin_set_plan_internal(modeladmin, request, queryset):
    _set_plan(modeladmin, request, queryset, PLAN_INTERNAL)


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
    list_filter = ("status", "plan_code")
    search_fields = ("name", "slug", "billing_email", "plan_code")
    readonly_fields = ("id", "created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}
    actions = (
        account_admin_suspend,
        account_admin_reactivate,
        account_admin_set_plan_free,
        account_admin_set_plan_starter,
        account_admin_set_plan_growth,
        account_admin_set_plan_internal,
    )
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
