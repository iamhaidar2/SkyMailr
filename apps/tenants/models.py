import uuid

from django.db import models


class TenantStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"


class SenderCategory(models.TextChoices):
    TRANSACTIONAL = "transactional", "Transactional"
    MARKETING = "marketing", "Marketing / lifecycle"


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.PROTECT,
        related_name="tenants",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=64)
    status = models.CharField(
        max_length=32, choices=TenantStatus.choices, default=TenantStatus.ACTIVE
    )
    default_sender_name = models.CharField(max_length=200, blank=True)
    default_sender_email = models.EmailField(blank=True)
    reply_to = models.EmailField(blank=True)
    sending_domain = models.CharField(
        max_length=255,
        blank=True,
        help_text="Expected outbound domain / subdomain metadata for DNS alignment.",
    )
    transactional_enabled = models.BooleanField(default=True)
    marketing_enabled = models.BooleanField(default=True)
    timezone = models.CharField(max_length=64, default="UTC")
    rate_limit_per_minute = models.PositiveIntegerField(
        default=120, help_text="Soft cap; enforced in dispatcher."
    )
    webhook_secret = models.CharField(max_length=128, blank=True)
    branding = models.JSONField(default=dict, blank=True)
    llm_defaults = models.JSONField(
        default=dict,
        blank=True,
        help_text="Keys: default_model, temperature, tone_profile, brand_voice_notes",
    )
    compliance_footer_html = models.TextField(
        blank=True,
        help_text="Appended to marketing HTML when tenant requires legal block.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class DomainVerificationStatus(models.TextChoices):
    UNVERIFIED = "unverified", "Unverified"
    DNS_PENDING = "dns_pending", "DNS pending"
    PARTIALLY_VERIFIED = "partially_verified", "Partially verified"
    VERIFIED = "verified", "Verified"
    FAILED_CHECK = "failed_check", "Check failed"


class DnsMetadataSource(models.TextChoices):
    """Where expected DNS values were last set (staff/admin visibility)."""

    UNKNOWN = "unknown", "Unknown"
    POSTAL_API = "postal_api", "Postal API"
    SETTINGS = "settings", "Operator settings"
    ADMIN = "admin", "Admin"


class PostalProvisionStatus(models.TextChoices):
    """Whether the domain exists in Postal / could be provisioned automatically."""

    PENDING = "pending", "Pending"
    CREATED = "created", "Created in mail server"
    EXISTS = "exists", "Already in mail server"
    FAILED = "failed", "Provisioning failed"


class TenantDomain(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="domains")
    domain = models.CharField(
        max_length=255,
        help_text="Root domain or subdomain used for outbound mail (lowercase).",
    )
    verified = models.BooleanField(default=False)
    is_primary = models.BooleanField(default=False)
    verification_status = models.CharField(
        max_length=32,
        choices=DomainVerificationStatus.choices,
        default=DomainVerificationStatus.UNVERIFIED,
        db_index=True,
    )
    dkim_status = models.CharField(max_length=64, blank=True)
    spf_status = models.CharField(max_length=64, blank=True)
    dmarc_status = models.CharField(max_length=64, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    verification_notes = models.TextField(blank=True)
    # Expected DNS (from Postal sync, operator settings merge, or admin). NULL = unknown; never store placeholder tokens.
    spf_txt_expected = models.TextField(
        blank=True,
        null=True,
        help_text="Full SPF TXT value customers should publish at the domain name (e.g. v=spf1 include:… ~all).",
    )
    dkim_selector = models.CharField(max_length=255, blank=True, null=True)
    dkim_txt_value = models.TextField(
        blank=True,
        null=True,
        help_text="Full DKIM TXT record value (v=DKIM1; …).",
    )
    return_path_cname_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Return-path hostname (FQDN). If empty, defaults to rp.<domain> when a target exists.",
    )
    return_path_cname_target = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="CNAME target for return-path/bounce handling.",
    )
    dmarc_txt_expected = models.TextField(
        blank=True,
        null=True,
        help_text="Full DMARC TXT for _dmarc.<domain>.",
    )
    postal_verification_txt_expected = models.TextField(
        blank=True,
        null=True,
        help_text="Full Postal domain-control TXT (e.g. postal-verification <token>) at the domain apex, when required.",
    )
    postal_verification_bridge_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when the provisioning bridge returned DNS at least once (stops repeat fetch when Postal omits verification TXT).",
    )
    dns_source = models.CharField(
        max_length=32,
        choices=DnsMetadataSource.choices,
        default=DnsMetadataSource.UNKNOWN,
        db_index=True,
    )
    dns_last_synced_at = models.DateTimeField(null=True, blank=True)
    postal_provision_status = models.CharField(
        max_length=32,
        choices=PostalProvisionStatus.choices,
        default=PostalProvisionStatus.PENDING,
        db_index=True,
    )
    postal_provision_error = models.TextField(
        blank=True,
        help_text="Last provisioning error detail (staff diagnostics; customer copy is templated).",
    )
    postal_provision_last_attempt_at = models.DateTimeField(null=True, blank=True)
    postal_provider_domain_id = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant", "domain"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "domain"],
                name="tenants_tenantdomain_tenant_domain_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.domain} ({self.tenant.slug})"


class SenderProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sender_profiles")
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=32, choices=SenderCategory.choices)
    from_name = models.CharField(max_length=200)
    from_email = models.EmailField()
    reply_to = models.EmailField(blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant", "category", "name"]

    def __str__(self):
        return f"{self.tenant.slug}:{self.name} ({self.category})"

    def save(self, *args, **kwargs):
        if self.is_default:
            SenderProfile.objects.filter(
                tenant=self.tenant, category=self.category, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class TenantAPIKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=120)
    key_hash = models.CharField(max_length=128, unique=True, editable=False)
    prefix = models.CharField(max_length=16, default="sk_live_")
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Tenant API key"
        verbose_name_plural = "Tenant API keys"

    def __str__(self):
        return f"{self.tenant.slug}:{self.name}"

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None
