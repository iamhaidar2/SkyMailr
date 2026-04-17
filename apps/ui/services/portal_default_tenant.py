"""Ensure every account has a primary connected app (tenant) without extra user steps."""

from __future__ import annotations

from apps.accounts.models import Account
from apps.tenants.models import Tenant, TenantStatus


def _unique_tenant_slug_from_account(account: Account) -> str:
    """Globally unique tenant slug derived from the account slug."""
    base = (account.slug or "app").strip().lower()[:64]
    if not base:
        base = "app"
    candidate = base
    n = 0
    while Tenant.objects.filter(slug__iexact=candidate).exists():
        n += 1
        suffix = f"-{n}"
        stem = base[: max(1, 64 - len(suffix))]
        candidate = f"{stem}{suffix}"
    return candidate


def ensure_default_tenant_for_account(account: Account) -> Tenant | None:
    """If the account has no tenants yet, create one. Returns existing or new tenant."""
    existing = Tenant.objects.filter(account=account).order_by("created_at").first()
    if existing is not None:
        return existing
    slug = _unique_tenant_slug_from_account(account)
    return Tenant.objects.create(
        account=account,
        name=account.name[:200] or slug,
        slug=slug,
        status=TenantStatus.ACTIVE,
    )
