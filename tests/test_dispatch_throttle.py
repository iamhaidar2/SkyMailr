"""Dispatch throttling, sweep ordering, and deferred retry behavior."""

import uuid
from datetime import timedelta

import pytest
from django.test.utils import override_settings
from django.utils import timezone

from apps.messages.models import (
    DispatchRateSlot,
    MessageEventType,
    MessagePriority,
    MessageType,
    OutboundMessage,
    OutboundStatus,
)
from apps.messages.tasks import dispatch_message_task, retry_due_deferred, sweep_dispatch_queue
from apps.tenants.models import TenantDomainSendingPolicy


def _queued_message(
    tenant,
    *,
    priority=MessagePriority.NORMAL_TX,
    send_after=None,
    sender_profile=None,
):
    return OutboundMessage.objects.create(
        tenant=tenant,
        source_app="throttle-test",
        message_type=MessageType.TRANSACTIONAL,
        to_email=f"to-{uuid.uuid4().hex[:8]}@example.com",
        subject_rendered="S",
        html_rendered="<p>x</p>",
        text_rendered="x",
        status=OutboundStatus.QUEUED,
        priority=priority,
        send_after=send_after or timezone.now(),
        sender_profile=sender_profile,
    )


@pytest.mark.django_db
@override_settings(EMAIL_PROVIDER="dummy")
def test_tenant_rate_limit_defers_excess_and_sets_next_retry(tenant):
    tenant.rate_limit_per_minute = 2
    tenant.save(update_fields=["rate_limit_per_minute"])
    m1 = _queued_message(tenant)
    m2 = _queued_message(tenant)
    m3 = _queued_message(tenant)

    dispatch_message_task.apply(args=[str(m1.id)])
    dispatch_message_task.apply(args=[str(m2.id)])
    dispatch_message_task.apply(args=[str(m3.id)])

    m1.refresh_from_db()
    m2.refresh_from_db()
    m3.refresh_from_db()
    assert m1.status == OutboundStatus.SENT
    assert m2.status == OutboundStatus.SENT
    assert m3.status == OutboundStatus.DEFERRED
    assert "rate_limited" in m3.last_error
    assert m3.next_retry_at is not None
    assert m3.events.filter(event_type=MessageEventType.DEFERRED).exists()
    assert DispatchRateSlot.objects.filter(tenant=tenant).count() == 2


@pytest.mark.django_db
def test_sweep_orders_by_priority_then_send_after_then_created(tenant):
    now = timezone.now()
    m_mkt = _queued_message(tenant, priority=MessagePriority.MARKETING, send_after=now)
    m_crit = _queued_message(tenant, priority=MessagePriority.CRITICAL_TX, send_after=now)
    qs = OutboundMessage.objects.filter(
        status=OutboundStatus.QUEUED,
        send_after__lte=now,
    ).order_by("priority", "send_after", "created_at")
    ids = list(qs.values_list("id", flat=True))
    assert ids[0] == m_crit.id
    assert ids[1] == m_mkt.id


@pytest.mark.django_db
@override_settings(EMAIL_PROVIDER="dummy")
def test_domain_daily_limit_defers_second_send(tenant):
    from apps.tenants.models import TenantDomain

    tenant.rate_limit_per_minute = 120
    tenant.default_sender_email = "noreply@warmup.example.com"
    tenant.save(update_fields=["rate_limit_per_minute", "default_sender_email"])

    td = TenantDomain.objects.create(
        tenant=tenant,
        domain="warmup.example.com",
        verified=True,
    )
    TenantDomainSendingPolicy.objects.create(
        tenant_domain=td,
        enabled=True,
        daily_limit=1,
        per_minute_limit=60,
    )

    m1 = _queued_message(tenant)
    m2 = _queued_message(tenant)
    dispatch_message_task.apply(args=[str(m1.id)])
    dispatch_message_task.apply(args=[str(m2.id)])

    m1.refresh_from_db()
    m2.refresh_from_db()
    assert m1.status == OutboundStatus.SENT
    assert m2.status == OutboundStatus.DEFERRED
    assert "domain daily" in m2.last_error.lower()


@pytest.mark.django_db
@override_settings(EMAIL_PROVIDER="dummy")
def test_throttle_deferred_not_failed_and_retry_requeues(tenant):
    tenant.rate_limit_per_minute = 1
    tenant.save(update_fields=["rate_limit_per_minute"])
    m1 = _queued_message(tenant)
    m2 = _queued_message(tenant)

    dispatch_message_task.apply(args=[str(m1.id)])
    dispatch_message_task.apply(args=[str(m2.id)])
    m2.refresh_from_db()
    assert m2.status == OutboundStatus.DEFERRED
    assert m2.status != OutboundStatus.FAILED

    DispatchRateSlot.objects.filter(tenant=tenant).delete()
    tenant.rate_limit_per_minute = 10
    tenant.save(update_fields=["rate_limit_per_minute"])

    m2.next_retry_at = timezone.now() - timedelta(seconds=1)
    m2.save(update_fields=["next_retry_at"])
    retry_due_deferred()
    m2.refresh_from_db()
    # Eager Celery runs dispatch_message_task inline after re-queue.
    assert m2.status == OutboundStatus.SENT


@pytest.mark.django_db
@override_settings(EMAIL_PROVIDER="dummy", CELERY_TASK_ALWAYS_EAGER=True)
def test_sweep_dispatch_enqueues_higher_priority_first(monkeypatch, tenant):
    now = timezone.now()
    m_low = _queued_message(tenant, priority=MessagePriority.MARKETING, send_after=now)
    m_high = _queued_message(tenant, priority=MessagePriority.CRITICAL_TX, send_after=now)
    order = []

    def capture(msg_id):
        order.append(msg_id)

    monkeypatch.setattr(
        "apps.messages.tasks.dispatch_message_task.delay",
        lambda msg_id: capture(msg_id),
    )
    sweep_dispatch_queue()
    assert order[0] == str(m_high.id)
    assert order[1] == str(m_low.id)
