import hashlib
import hmac
import json
import logging
from typing import Any

from django.db import transaction

from apps.messages.models import (
    BounceRecord,
    ComplaintRecord,
    MessageEvent,
    MessageEventType,
    OutboundMessage,
    OutboundStatus,
    ProviderWebhookEvent,
)
from apps.providers.normalizers import (
    BOUNCE_HARD,
    BOUNCE_SOFT,
    EVENT_BOUNCED,
    EVENT_CLICKED,
    EVENT_COMPLAINED,
    EVENT_DELIVERED,
    EVENT_FAILED,
    EVENT_OPENED,
    EVENT_UNKNOWN,
    normalize_provider_webhook,
)
from apps.subscriptions.models import DeliverySuppression, SuppressionReason
from apps.tenants.services.sending_risk import apply_automated_risk_pause

logger = logging.getLogger(__name__)

_PROCESSING_ERROR_MAX = 2000


def _truncate(s: str, n: int = _PROCESSING_ERROR_MAX) -> str:
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."


def _event_payload(normalized: dict[str, Any], ev: ProviderWebhookEvent) -> dict[str, Any]:
    pid = normalized.get("provider_event_id") or ""
    slim = {k: v for k, v in normalized.items() if k != "raw"}
    return {
        "provider_event_id": pid,
        "webhook_event_id": str(ev.id),
        "normalized": slim,
    }


def _message_event_exists(msg: OutboundMessage, event_type: str, provider_event_id: str) -> bool:
    if not provider_event_id:
        return False
    return MessageEvent.objects.filter(
        message=msg,
        event_type=event_type,
        payload__provider_event_id=provider_event_id,
    ).exists()


def _create_message_event_idempotent(
    msg: OutboundMessage,
    event_type: str,
    normalized: dict[str, Any],
    ev: ProviderWebhookEvent,
) -> bool:
    """Returns True if a new event was created."""
    pid = str(normalized.get("provider_event_id") or "")
    if pid and _message_event_exists(msg, event_type, pid):
        return False
    MessageEvent.objects.create(
        message=msg,
        event_type=event_type,
        payload=_event_payload(normalized, ev),
    )
    return True


def _merge_suppression_metadata(
    existing: dict[str, Any] | None,
    *,
    provider: str,
    provider_message_id: str,
    webhook_event_id: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = dict(existing or {})
    base.update(
        {
            "provider": provider,
            "provider_message_id": provider_message_id,
            "webhook_event_id": webhook_event_id,
        }
    )
    if extra:
        base.update(extra)
    return base


def _apply_suppression_unique(
    *,
    tenant,
    email: str,
    reason: str,
    applies_to_marketing: bool,
    applies_to_transactional: bool,
    metadata: dict[str, Any],
) -> None:
    """One suppression row per (tenant, email, reason); merge metadata on repeat."""
    email = email.strip()
    if not email:
        return
    email_canon = email.lower()
    existing = DeliverySuppression.objects.filter(
        tenant=tenant,
        email__iexact=email_canon,
        reason=reason,
    ).first()
    if existing:
        merged = {**(existing.metadata or {}), **metadata}
        DeliverySuppression.objects.filter(pk=existing.pk).update(
            applies_to_marketing=applies_to_marketing,
            applies_to_transactional=applies_to_transactional,
            metadata=merged,
        )
        return
    DeliverySuppression.objects.create(
        tenant=tenant,
        email=email_canon,
        reason=reason,
        applies_to_marketing=applies_to_marketing,
        applies_to_transactional=applies_to_transactional,
        metadata=metadata,
    )


class ProviderWebhookService:
    def ingest(
        self,
        *,
        provider: str,
        raw_body: bytes,
        headers: dict[str, str],
        tenant_secret: str = "",
    ) -> ProviderWebhookEvent:
        sig_ok = False
        if tenant_secret and "X-SkyMailr-Signature" in headers:
            expected = hmac.new(
                tenant_secret.encode(),
                raw_body,
                hashlib.sha256,
            ).hexdigest()
            sig_ok = hmac.compare_digest(expected, headers.get("X-SkyMailr-Signature", ""))

        text = raw_body.decode("utf-8", errors="replace")[:50000]
        parsed: dict[str, Any] | None = None
        parse_err: str | None = None
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                parsed = loaded
            else:
                parse_err = "json_root_not_object"
        except json.JSONDecodeError as e:
            parse_err = f"invalid_json:{e}"

        if parse_err:
            minimal = {
                "provider": provider,
                "provider_event_id": "",
                "provider_message_id": "",
                "event_type": EVENT_UNKNOWN,
                "recipient": "",
                "bounce_type": "",
                "reason": "",
                "timestamp": "",
                "is_terminal_failure": True,
                "raw": {},
            }
            return ProviderWebhookEvent.objects.create(
                provider=provider,
                raw_body=text,
                headers=headers,
                signature_valid=sig_ok,
                normalized=minimal,
                processing_error=_truncate(parse_err),
            )

        assert parsed is not None
        normalized = normalize_provider_webhook(provider, parsed)

        ev = ProviderWebhookEvent.objects.create(
            provider=provider,
            raw_body=text,
            headers=headers,
            signature_valid=sig_ok,
            normalized=normalized,
        )

        try:
            with transaction.atomic():
                self._apply_internal(ev, normalized)
        except Exception as e:
            logger.exception("Provider webhook apply failed provider=%s ev=%s", provider, ev.id)
            ev.processing_error = _truncate(str(e))
            ev.save(update_fields=["processing_error"])

        return ev

    def _apply_internal(self, ev: ProviderWebhookEvent, normalized: dict[str, Any]) -> None:
        mid = str(normalized.get("provider_message_id") or "").strip()
        event_type = str(normalized.get("event_type") or EVENT_UNKNOWN)
        pid = str(normalized.get("provider_event_id") or "")

        if not mid:
            return

        msg = OutboundMessage.objects.filter(provider_message_id=mid).first()
        if not msg:
            return

        if pid and MessageEvent.objects.filter(message=msg, payload__provider_event_id=pid).exists():
            return

        reason = str(normalized.get("reason") or "")

        if event_type == EVENT_DELIVERED:
            msg.status = OutboundStatus.DELIVERED
            msg.save(update_fields=["status", "updated_at"])
            _create_message_event_idempotent(msg, MessageEventType.DELIVERED, normalized, ev)
            return

        if event_type == EVENT_OPENED:
            _create_message_event_idempotent(msg, MessageEventType.OPENED, normalized, ev)
            return

        if event_type == EVENT_CLICKED:
            _create_message_event_idempotent(msg, MessageEventType.CLICKED, normalized, ev)
            return

        if event_type == EVENT_BOUNCED:
            bounce_type = str(normalized.get("bounce_type") or BOUNCE_SOFT)
            email = (normalized.get("recipient") or msg.to_email or "").strip() or msg.to_email

            BounceRecord.objects.create(
                tenant=msg.tenant,
                email=email,
                message=msg,
                bounce_type=bounce_type,
                reason=reason,
            )

            if bounce_type == BOUNCE_HARD:
                msg.status = OutboundStatus.BOUNCED
                msg.save(update_fields=["status", "updated_at"])
                _create_message_event_idempotent(msg, MessageEventType.BOUNCED, normalized, ev)
                _apply_suppression_unique(
                    tenant=msg.tenant,
                    email=email,
                    reason=SuppressionReason.HARD_BOUNCE,
                    applies_to_marketing=True,
                    applies_to_transactional=True,
                    metadata=_merge_suppression_metadata(
                        {},
                        provider=str(normalized.get("provider") or ""),
                        provider_message_id=mid,
                        webhook_event_id=str(ev.id),
                        extra={"reason": reason},
                    ),
                )
                apply_automated_risk_pause(msg.tenant)
            else:
                # Soft bounce: record only; do not auto-suppress.
                # TODO: after N soft bounces for the same tenant+email in a window, create
                # DeliverySuppression or escalate (SOFT_BOUNCE_SUPPRESS_THRESHOLD not yet wired).
                msg.status = OutboundStatus.DEFERRED
                msg.save(update_fields=["status", "updated_at"])
                _create_message_event_idempotent(msg, MessageEventType.DEFERRED, normalized, ev)
            return

        if event_type == EVENT_COMPLAINED:
            msg.status = OutboundStatus.COMPLAINED
            msg.save(update_fields=["status", "updated_at"])
            _create_message_event_idempotent(msg, MessageEventType.COMPLAINED, normalized, ev)
            feedback = reason or "spam"
            email = (normalized.get("recipient") or msg.to_email or "").strip() or msg.to_email
            ComplaintRecord.objects.create(
                tenant=msg.tenant,
                email=email,
                message=msg,
                feedback_type=feedback[:64],
            )
            _apply_suppression_unique(
                tenant=msg.tenant,
                email=email,
                reason=SuppressionReason.COMPLAINT,
                applies_to_marketing=True,
                applies_to_transactional=False,
                metadata=_merge_suppression_metadata(
                    {},
                    provider=str(normalized.get("provider") or ""),
                    provider_message_id=mid,
                    webhook_event_id=str(ev.id),
                    extra={"feedback_type": feedback[:256]},
                ),
            )
            apply_automated_risk_pause(msg.tenant)
            return

        if event_type == EVENT_FAILED:
            is_terminal = bool(normalized.get("is_terminal_failure", True))
            if is_terminal:
                msg.status = OutboundStatus.FAILED
                msg.last_error = reason or "provider_failed"
                msg.save(update_fields=["status", "last_error", "updated_at"])
                _create_message_event_idempotent(msg, MessageEventType.FAILED, normalized, ev)
            else:
                if msg.status in (OutboundStatus.SENDING, OutboundStatus.SENT):
                    msg.status = OutboundStatus.DEFERRED
                    msg.save(update_fields=["status", "updated_at"])
                _create_message_event_idempotent(msg, MessageEventType.DEFERRED, normalized, ev)
            return
