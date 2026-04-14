from django.db import models

from apps.subscriptions.models import DeliverySuppression, UnsubscribeRecord
from apps.tenants.models import Tenant


class SuppressionService:
    @staticmethod
    def is_globally_suppressed(email: str) -> bool:
        return DeliverySuppression.objects.filter(
            tenant__isnull=True,
            email__iexact=email,
            applies_to_marketing=True,
        ).exists()

    @staticmethod
    def is_tenant_suppressed(tenant: Tenant, email: str, *, marketing: bool) -> bool:
        qs = DeliverySuppression.objects.filter(email__iexact=email)
        if marketing:
            qs = qs.filter(
                models.Q(tenant=tenant) | models.Q(tenant__isnull=True),
                applies_to_marketing=True,
            )
        else:
            qs = qs.filter(
                models.Q(tenant=tenant) | models.Q(tenant__isnull=True),
                applies_to_transactional=True,
            )
        return qs.exists()

    @staticmethod
    def is_unsubscribed_marketing(tenant: Tenant, email: str) -> bool:
        return UnsubscribeRecord.objects.filter(
            tenant=tenant, email__iexact=email, channel="marketing"
        ).exists()
