"""Attach existing tenants to the default internal account; optional staff memberships."""

from django.db import migrations


HAIDAR_SLUG = "haidar-internal"
HAIDAR_NAME = "Haidar Internal"


def forwards(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    AccountMembership = apps.get_model("accounts", "AccountMembership")
    Tenant = apps.get_model("tenants", "Tenant")
    User = apps.get_model("auth", "User")

    account, _created = Account.objects.get_or_create(
        slug=HAIDAR_SLUG,
        defaults={
            "name": HAIDAR_NAME,
            "status": "active",
            "metadata": {},
        },
    )
    # Idempotent: do not overwrite name/status if account already existed with different data
    if not account.name:
        Account.objects.filter(pk=account.pk).update(name=HAIDAR_NAME)

    Tenant.objects.filter(account__isnull=True).update(account_id=account.id)

    for user in User.objects.filter(is_superuser=True):
        AccountMembership.objects.get_or_create(
            account_id=account.id,
            user_id=user.id,
            defaults={
                "role": "owner",
                "is_active": True,
            },
        )

    for user in User.objects.filter(is_staff=True, is_superuser=False):
        AccountMembership.objects.get_or_create(
            account_id=account.id,
            user_id=user.id,
            defaults={
                "role": "admin",
                "is_active": True,
            },
        )


def backwards(apps, schema_editor):
    """Detach tenants from the internal account so nullable FK can be reverted (dev only)."""
    Account = apps.get_model("accounts", "Account")
    Tenant = apps.get_model("tenants", "Tenant")

    try:
        acc = Account.objects.get(slug=HAIDAR_SLUG)
    except Account.DoesNotExist:
        return
    Tenant.objects.filter(account_id=acc.id).update(account_id=None)


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0003_tenant_account_nullable"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
