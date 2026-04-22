import pytest
from rest_framework.test import APIClient

from apps.messages.models import MessageType
from apps.messages.services.send_pipeline import should_suppress
from apps.subscriptions.models import DeliverySuppression, SuppressionReason, UnsubscribeRecord
from apps.subscriptions.services.suppression_ops import create_manual_suppression, remove_suppression_with_audit


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


@pytest.mark.django_db
def test_tenant_marketing_only_suppression_does_not_block_transactional(tenant):
    DeliverySuppression.objects.create(
        tenant=tenant,
        email="m@example.com",
        reason=SuppressionReason.MANUAL,
        applies_to_marketing=True,
        applies_to_transactional=False,
    )
    assert should_suppress(tenant, "m@example.com", MessageType.MARKETING.value)[0] is True
    assert should_suppress(tenant, "m@example.com", MessageType.TRANSACTIONAL.value)[0] is False


@pytest.mark.django_db
def test_tenant_transactional_suppression_blocks_transactional(tenant):
    DeliverySuppression.objects.create(
        tenant=tenant,
        email="t@example.com",
        reason=SuppressionReason.MANUAL,
        applies_to_marketing=False,
        applies_to_transactional=True,
    )
    assert should_suppress(tenant, "t@example.com", MessageType.MARKETING.value)[0] is False
    assert should_suppress(tenant, "t@example.com", MessageType.TRANSACTIONAL.value)[0] is True


@pytest.mark.django_db
def test_manual_suppression_blocks_then_remove_unblocks(tenant):
    row = create_manual_suppression(
        email="manual@example.com",
        tenant=tenant,
        applies_to_marketing=True,
        applies_to_transactional=False,
        metadata={"note": "x", "created_by_username": "test", "source": "operator_manual"},
    )
    assert should_suppress(tenant, "manual@example.com", MessageType.MARKETING.value)[0] is True
    remove_suppression_with_audit(row, removed_by=None)
    assert should_suppress(tenant, "manual@example.com", MessageType.MARKETING.value)[0] is False


@pytest.mark.django_db
def test_api_suppressions_list_tenant_and_global_only(api_key, api_key_other, tenant, other_tenant):
    DeliverySuppression.objects.create(
        tenant=tenant,
        email="only-a@example.com",
        reason=SuppressionReason.MANUAL,
        applies_to_marketing=True,
    )
    DeliverySuppression.objects.create(
        tenant=other_tenant,
        email="only-b@example.com",
        reason=SuppressionReason.MANUAL,
        applies_to_marketing=True,
    )
    DeliverySuppression.objects.create(
        tenant=None,
        email="global@example.com",
        reason=SuppressionReason.HARD_BOUNCE,
        applies_to_marketing=True,
    )
    ca = APIClient()
    ca.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    ra = ca.get("/api/v1/suppressions/")
    assert ra.status_code == 200
    emails_a = {x["email"] for x in ra.json()}
    assert "only-a@example.com" in emails_a
    assert "global@example.com" in emails_a
    assert "only-b@example.com" not in emails_a

    cb = APIClient()
    cb.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key_other}")
    rb = cb.get("/api/v1/suppressions/")
    emails_b = {x["email"] for x in rb.json()}
    assert "only-b@example.com" in emails_b
    assert "global@example.com" in emails_b
    assert "only-a@example.com" not in emails_b


@pytest.mark.django_db
def test_api_suppression_detail_other_tenant_404(api_key, tenant, other_tenant):
    other_row = DeliverySuppression.objects.create(
        tenant=other_tenant,
        email="x@example.com",
        reason=SuppressionReason.MANUAL,
        applies_to_marketing=True,
    )
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r = c.get(f"/api/v1/suppressions/{other_row.id}/")
    assert r.status_code == 404


@pytest.mark.django_db
def test_api_delete_global_forbidden(api_key, tenant):
    g = DeliverySuppression.objects.create(
        tenant=None,
        email="g2@example.com",
        reason=SuppressionReason.MANUAL,
        applies_to_marketing=True,
    )
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r = c.delete(f"/api/v1/suppressions/{g.id}/")
    assert r.status_code == 403


@pytest.mark.django_db
def test_api_create_and_delete_suppression(api_key, tenant):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    r = c.post(
        "/api/v1/suppressions/",
        {
            "email": "api-manual@example.com",
            "applies_to_marketing": True,
            "applies_to_transactional": False,
            "note": "from test",
        },
        format="json",
    )
    assert r.status_code == 201
    sid = r.json()["id"]
    assert should_suppress(tenant, "api-manual@example.com", MessageType.MARKETING.value)[0] is True
    d = c.delete(f"/api/v1/suppressions/{sid}/")
    assert d.status_code == 204
    assert should_suppress(tenant, "api-manual@example.com", MessageType.MARKETING.value)[0] is False
