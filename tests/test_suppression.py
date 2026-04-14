import pytest

from apps.messages.services.send_pipeline import should_suppress
from apps.subscriptions.models import DeliverySuppression, SuppressionReason, UnsubscribeRecord


@pytest.mark.django_db
def test_unsubscribe_blocks_marketing(tenant):
    UnsubscribeRecord.objects.create(
        tenant=tenant, email="a@example.com", channel="marketing"
    )
    sup, _ = should_suppress(tenant, "a@example.com", "marketing")
    assert sup is True


@pytest.mark.django_db
def test_transactional_not_blocked_by_marketing_unsub(tenant):
    UnsubscribeRecord.objects.create(
        tenant=tenant, email="a@example.com", channel="marketing"
    )
    sup, _ = should_suppress(tenant, "a@example.com", "transactional")
    assert sup is False


@pytest.mark.django_db
def test_global_suppression(tenant):
    DeliverySuppression.objects.create(
        tenant=None,
        email="g@example.com",
        reason=SuppressionReason.HARD_BOUNCE,
        applies_to_marketing=True,
    )
    sup, _ = should_suppress(tenant, "g@example.com", "transactional")
    assert sup is True
