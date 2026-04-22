# Generated manually for per-domain send caps / warmup

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0011_tenantdomain_mx_targets"),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantDomainSendingPolicy",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("enabled", models.BooleanField(default=True)),
                (
                    "daily_limit",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="Max dispatch slots per calendar day (tenant timezone); null = no daily cap.",
                        null=True,
                    ),
                ),
                (
                    "per_minute_limit",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="Max dispatch slots per rolling minute for this domain; null = use tenant limit only.",
                        null=True,
                    ),
                ),
                ("warmup_stage", models.PositiveIntegerField(default=0)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant_domain",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sending_policy",
                        to="tenants.tenantdomain",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
