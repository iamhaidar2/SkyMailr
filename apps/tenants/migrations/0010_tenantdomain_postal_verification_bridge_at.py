from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0009_tenantdomain_postal_verification_txt"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantdomain",
            name="postal_verification_bridge_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Set when the provisioning bridge returned DNS at least once (stops repeat fetch when Postal omits verification TXT).",
                null=True,
            ),
        ),
    ]
