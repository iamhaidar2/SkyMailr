# Generated manually for dispatch throttling

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("skymailr_messages", "0001_initial"),
        ("tenants", "0011_tenantdomain_mx_targets"),
    ]

    operations = [
        migrations.CreateModel(
            name="DispatchRateSlot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "outbound_message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dispatch_rate_slots",
                        to="skymailr_messages.outboundmessage",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dispatch_rate_slots",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "tenant_domain",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dispatch_rate_slots",
                        to="tenants.tenantdomain",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="dispatchrateslot",
            index=models.Index(fields=["tenant", "created_at"], name="msg_drslot_tnt_ct_idx"),
        ),
        migrations.AddIndex(
            model_name="dispatchrateslot",
            index=models.Index(fields=["tenant_domain", "created_at"], name="msg_drslot_td_ct_idx"),
        ),
        migrations.AddIndex(
            model_name="outboundmessage",
            index=models.Index(
                fields=["status", "send_after", "priority", "created_at"],
                name="msg_ob_sweep_ord_idx",
            ),
        ),
    ]
