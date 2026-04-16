"""Default account helpers (e.g. internal bootstrap tenant)."""

from apps.accounts.models import Account, AccountStatus

INTERNAL_ACCOUNT_SLUG = "haidar-internal"
INTERNAL_ACCOUNT_NAME = "Haidar Internal"


def get_or_create_internal_account() -> Account:
    """The default account used for migrated tenants and internal operator-created tenants."""
    account, _created = Account.objects.get_or_create(
        slug=INTERNAL_ACCOUNT_SLUG,
        defaults={
            "name": INTERNAL_ACCOUNT_NAME,
            "status": AccountStatus.ACTIVE,
            "metadata": {},
        },
    )
    return account
