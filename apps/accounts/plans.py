"""Code-driven plan definitions (billing integration can map Stripe products to plan_code)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from apps.accounts.models import Account

DEFAULT_PLAN_CODE = "free"

# Canonical plan codes stored on Account.plan_code
PLAN_FREE = "free"
PLAN_STARTER = "starter"
PLAN_GROWTH = "growth"
PLAN_INTERNAL = "internal"


@dataclass(frozen=True)
class PlanLimits:
    max_tenants: int
    max_active_api_keys: int
    max_monthly_sends: int
    max_templates: int
    max_workflows: int
    max_members: int
    max_sending_domains_per_tenant: int
    label: str


PLAN_DEFINITIONS: dict[str, PlanLimits] = {
    PLAN_FREE: PlanLimits(
        max_tenants=1,
        max_active_api_keys=3,
        max_monthly_sends=500,
        max_templates=10,
        max_workflows=5,
        max_members=5,
        max_sending_domains_per_tenant=2,
        label="Free",
    ),
    PLAN_STARTER: PlanLimits(
        max_tenants=5,
        max_active_api_keys=15,
        max_monthly_sends=10_000,
        max_templates=50,
        max_workflows=25,
        max_members=25,
        max_sending_domains_per_tenant=25,
        label="Starter",
    ),
    PLAN_GROWTH: PlanLimits(
        max_tenants=25,
        max_active_api_keys=100,
        max_monthly_sends=500_000,
        max_templates=500,
        max_workflows=200,
        max_members=100,
        max_sending_domains_per_tenant=100,
        label="Growth",
    ),
    PLAN_INTERNAL: PlanLimits(
        max_tenants=10_000,
        max_active_api_keys=50_000,
        max_monthly_sends=10_000_000,
        max_templates=50_000,
        max_workflows=50_000,
        max_members=10_000,
        max_sending_domains_per_tenant=10_000,
        label="Internal",
    ),
}


def _deep_merge_limits(base: PlanLimits, patch: dict[str, Any]) -> PlanLimits:
    """Apply partial override dict (int values) onto base limits."""
    data = {
        "max_tenants": patch.get("max_tenants", base.max_tenants),
        "max_active_api_keys": patch.get("max_active_api_keys", base.max_active_api_keys),
        "max_monthly_sends": patch.get("max_monthly_sends", base.max_monthly_sends),
        "max_templates": patch.get("max_templates", base.max_templates),
        "max_workflows": patch.get("max_workflows", base.max_workflows),
        "max_members": patch.get("max_members", base.max_members),
        "max_sending_domains_per_tenant": patch.get(
            "max_sending_domains_per_tenant", base.max_sending_domains_per_tenant
        ),
        "label": patch.get("label", base.label),
    }
    return replace(base, **data)


def resolve_plan_code(account: Account) -> str:
    raw = (account.plan_code or "").strip().lower()
    if not raw or raw not in PLAN_DEFINITIONS:
        return DEFAULT_PLAN_CODE
    return raw


def get_effective_limits(account: Account) -> PlanLimits:
    """Merge plan definition with optional account.metadata['plan_limits_override']."""
    code = resolve_plan_code(account)
    base = PLAN_DEFINITIONS.get(code) or PLAN_DEFINITIONS[DEFAULT_PLAN_CODE]
    meta = account.metadata or {}
    override = meta.get("plan_limits_override")
    if isinstance(override, dict) and override:
        return _deep_merge_limits(base, override)
    return base


def plan_display_name(account: Account) -> str:
    return get_effective_limits(account).label
