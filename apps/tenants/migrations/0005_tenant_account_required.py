import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0004_backfill_default_account"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenant",
            name="account",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tenants",
                to="accounts.account",
            ),
        ),
    ]
