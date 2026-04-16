from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0007_tenant_domain_dns_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantdomain",
            name="postal_provision_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("created", "Created in mail server"),
                    ("exists", "Already in mail server"),
                    ("failed", "Provisioning failed"),
                ],
                db_index=True,
                default="pending",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="postal_provision_error",
            field=models.TextField(
                blank=True,
                help_text="Last provisioning error detail (staff diagnostics; customer copy is templated).",
            ),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="postal_provision_last_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="postal_provider_domain_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
