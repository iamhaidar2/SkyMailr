"""
Expected DNS record rows for tenant sending domains — provider entry point.

Postal is the current implementation; other providers can register builders later
without changing portal templates.
"""

from __future__ import annotations

from django.conf import settings

from apps.tenants.models import TenantDomain
from apps.tenants.services.domain_dns_instructions import DnsInstructionSet, build_dns_instructions_for_domain


class PostalDomainRecordsProvider:
    """DNS expectations when outbound is backed by Postal (current default)."""

    @staticmethod
    def expected_records(td: TenantDomain) -> DnsInstructionSet:
        return build_dns_instructions_for_domain(td)


def get_expected_dns_records(td: TenantDomain) -> DnsInstructionSet:
    """
    Return the instruction set for this tenant domain.

    Today all configured EMAIL_PROVIDER values use the same row builder (Postal-shaped
    metadata on TenantDomain). When Mailgun/Resend ship, select a provider-specific
    class here based on settings and/or tenant routing.
    """
    _ = (getattr(settings, "EMAIL_PROVIDER", None) or "dummy").lower()
    return PostalDomainRecordsProvider.expected_records(td)
