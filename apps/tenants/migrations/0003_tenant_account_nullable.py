import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("tenants", "0002_remove_senderprofile_unique_default_sender_per_tenant_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tenants",
                to="accounts.account",
            ),
        ),
    ]
