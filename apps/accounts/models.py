import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


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


class AccountInviteStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


class AccountInvite(models.Model):
    """Invitation to join an account (email link with secret token)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="invites")
    email = models.EmailField(db_index=True)
    role = models.CharField(max_length=32, choices=AccountRole.choices)
    token_hash = models.CharField(max_length=128, unique=True, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="account_invites_sent",
    )
    status = models.CharField(
        max_length=16,
        choices=AccountInviteStatus.choices,
        default=AccountInviteStatus.PENDING,
        db_index=True,
    )
    expires_at = models.DateTimeField(db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "email"],
                condition=models.Q(status=AccountInviteStatus.PENDING),
                name="accounts_invite_unique_pending_email_per_account",
            ),
        ]

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.email} → {self.account.slug} ({self.status})"


class UserProfile(models.Model):
    """Customer-portal profile bits (email verification, etc.)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="portal_profile",
    )
    email_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Profile({self.user_id})"


class EmailVerificationToken(models.Model):
    """One-time token for verifying login email (scaffold for gating later)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_verification_tokens",
    )
    token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def is_valid(self) -> bool:
        if self.consumed_at is not None:
            return False
        return self.expires_at > timezone.now()
