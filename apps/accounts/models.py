import uuid

from django.conf import settings
from django.db import models


class AccountStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    CANCELLED = "cancelled", "Cancelled"


class AccountRole(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    EDITOR = "editor", "Editor"
    VIEWER = "viewer", "Viewer"
    BILLING = "billing", "Billing"


class Account(models.Model):
    """Billing/org container above tenants; tenants remain the mail isolation root."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=64)
    status = models.CharField(
        max_length=32,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
    )
    billing_email = models.EmailField(blank=True)
    plan_code = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


class AccountMembership(models.Model):
    """Links a Django user to an account with a role."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_memberships",
    )
    role = models.CharField(max_length=32, choices=AccountRole.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["account", "user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "user"],
                name="accounts_membership_account_user_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.account.slug} ({self.role})"
