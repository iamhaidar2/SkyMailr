import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0005_tenant_account_required"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenantdomain",
            name="domain",
            field=models.CharField(
                help_text="Root domain or subdomain used for outbound mail (lowercase).",
                max_length=255,
                unique=False,
            ),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="dmarc_status",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="last_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="spf_status",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="updated_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AlterField(
            model_name="tenantdomain",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="verification_notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="verification_status",
            field=models.CharField(
                choices=[
                    ("unverified", "Unverified"),
                    ("dns_pending", "DNS pending"),
                    ("partially_verified", "Partially verified"),
                    ("verified", "Verified"),
                    ("failed_check", "Check failed"),
                ],
                db_index=True,
                default="unverified",
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="tenantdomain",
            constraint=models.UniqueConstraint(
                fields=("tenant", "domain"),
                name="tenants_tenantdomain_tenant_domain_uniq",
            ),
        ),
    ]
