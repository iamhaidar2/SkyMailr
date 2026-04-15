"""Helpers for tenant/sender identity validation in the operator UI."""

from __future__ import annotations


def normalize_domain(value: str) -> str:
    return (value or "").strip().lower()


def email_domain(email: str) -> str:
    if not email or "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].strip().lower()


def from_email_allowed_for_tenant(from_email: str, sending_domain: str) -> bool:
    """If sending_domain is set, from_email must be on that domain."""
    sd = normalize_domain(sending_domain)
    if not sd:
        return True
    return email_domain(from_email) == sd


def default_sender_domain_mismatch(tenant) -> bool:
    """True if default_sender_email domain does not match sending_domain (both set)."""
    sd = normalize_domain(getattr(tenant, "sending_domain", "") or "")
    de = (getattr(tenant, "default_sender_email", "") or "").strip()
    if not sd or not de:
        return False
    return email_domain(de) != sd
