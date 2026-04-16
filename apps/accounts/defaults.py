"""Default account helpers (e.g. internal bootstrap tenant)."""

from apps.accounts.models import Account, AccountStatus
from apps.accounts.plans import PLAN_INTERNAL

INTERNAL_ACCOUNT_SLUG = "haidar-internal"
INTERNAL_ACCOUNT_NAME = "Haidar Internal"


def get_or_create_internal_account() -> Account:
    """The default account used for migrated tenants and internal operator-created tenants."""
    account, _created = Account.objects.get_or_create(
        slug=INTERNAL_ACCOUNT_SLUG,
        defaults={
            "name": INTERNAL_ACCOUNT_NAME,
            "status": AccountStatus.ACTIVE,
            "plan_code": PLAN_INTERNAL,
            "metadata": {},
        },
    )
    if account.plan_code != PLAN_INTERNAL:
        Account.objects.filter(pk=account.pk).update(plan_code=PLAN_INTERNAL)
        account.plan_code = PLAN_INTERNAL
    return account
