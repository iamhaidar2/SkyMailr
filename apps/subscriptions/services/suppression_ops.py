"""Create and remove delivery suppressions (operator UI, API, webhooks)."""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from apps.subscriptions.models import DeliverySuppression, SuppressionReason, SuppressionRemovalLog

logger = logging.getLogger(__name__)


def merge_manual_suppression_metadata(
    *,
    note: str,
    actor_username: str,
    source_message_id: str | None = None,
    extra: dict[str, Any] | None = None,
    source: str = "operator_manual",
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "note": (note or "").strip(),
        "created_by_username": actor_username,
        "source": source,
    }
    if source_message_id:
        meta["outbound_message_id"] = str(source_message_id)
    if extra:
        meta.update(extra)
    return meta


@transaction.atomic
def create_manual_suppression(
    *,
    email: str,
    tenant,
    applies_to_marketing: bool,
    applies_to_transactional: bool,
    metadata: dict[str, Any],
) -> DeliverySuppression:
    """Create or merge a manual DeliverySuppression (same uniqueness as webhooks: tenant+email+reason)."""
    email_canon = (email or "").strip().lower()
    if not email_canon:
        raise ValueError("email is required")

    q = DeliverySuppression.objects.filter(
        email__iexact=email_canon,
        reason=SuppressionReason.MANUAL,
    )
    if tenant is None:
        q = q.filter(tenant__isnull=True)
    else:
        q = q.filter(tenant=tenant)
    existing = q.first()
    if existing:
        merged = {**(existing.metadata or {}), **metadata}
        DeliverySuppression.objects.filter(pk=existing.pk).update(
            applies_to_marketing=applies_to_marketing,
            applies_to_transactional=applies_to_transactional,
            metadata=merged,
        )
        existing.refresh_from_db()
        logger.info(
            "suppression_manual_merged suppression_id=%s email=%s tenant_id=%s",
            existing.pk,
            email_canon,
            getattr(tenant, "id", None),
        )
        return existing

    row = DeliverySuppression.objects.create(
        tenant=tenant,  # None = global
        email=email_canon,
        reason=SuppressionReason.MANUAL,
        applies_to_marketing=applies_to_marketing,
        applies_to_transactional=applies_to_transactional,
        metadata=metadata,
    )
    logger.info(
        "suppression_manual_created suppression_id=%s email=%s tenant_id=%s",
        row.pk,
        email_canon,
        getattr(tenant, "id", None),
    )
    return row


@transaction.atomic
def remove_suppression_with_audit(
    suppression: DeliverySuppression,
    *,
    removed_by,
) -> None:
    """Delete suppression and persist a removal audit row."""
    sid = suppression.id
    email = suppression.email
    tenant = suppression.tenant
    reason = suppression.reason
    meta = dict(suppression.metadata or {})
    SuppressionRemovalLog.objects.create(
        original_suppression_id=sid,
        email=email,
        tenant=tenant,
        reason=reason,
        metadata_snapshot=meta,
        removed_by=removed_by if getattr(removed_by, "pk", None) else None,
    )
    suppression.delete()
    logger.info(
        "suppression_removed original_id=%s email=%s removed_by_id=%s",
        sid,
        email,
        getattr(removed_by, "pk", None),
    )
