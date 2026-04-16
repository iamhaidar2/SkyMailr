from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0006_tenant_domain_verification"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantdomain",
            name="spf_txt_expected",
            field=models.TextField(
                blank=True,
                help_text="Full SPF TXT value customers should publish at the domain name (e.g. v=spf1 include:… ~all).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="dkim_selector",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="dkim_txt_value",
            field=models.TextField(
                blank=True,
                help_text="Full DKIM TXT record value (v=DKIM1; …).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="return_path_cname_name",
            field=models.CharField(
                blank=True,
                help_text="Return-path hostname (FQDN). If empty, defaults to rp.<domain> when a target exists.",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="return_path_cname_target",
            field=models.CharField(
                blank=True,
                help_text="CNAME target for return-path/bounce handling.",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="dmarc_txt_expected",
            field=models.TextField(
                blank=True,
                help_text="Full DMARC TXT for _dmarc.<domain>.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="dns_source",
            field=models.CharField(
                choices=[
                    ("unknown", "Unknown"),
                    ("postal_api", "Postal API"),
                    ("settings", "Operator settings"),
                    ("admin", "Admin"),
                ],
                db_index=True,
                default="unknown",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="tenantdomain",
            name="dns_last_synced_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
