from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0008_tenantdomain_postal_provision"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantdomain",
            name="postal_verification_txt_expected",
            field=models.TextField(
                blank=True,
                help_text="Full Postal domain-control TXT (e.g. postal-verification <token>) at the domain apex, when required.",
                null=True,
            ),
        ),
    ]
