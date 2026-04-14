import hashlib
import hmac
import json
import logging

from apps.messages.models import (
    MessageEvent,
    MessageEventType,
    OutboundMessage,
    OutboundStatus,
    ProviderWebhookEvent,
)

logger = logging.getLogger(__name__)


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

        normalized = {}
        try:
            normalized = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            pass

        ev = ProviderWebhookEvent.objects.create(
            provider=provider,
            raw_body=raw_body.decode("utf-8", errors="replace")[:50000],
            headers=headers,
            signature_valid=sig_ok,
            normalized=normalized if isinstance(normalized, dict) else {},
        )

        self._apply_normalized(normalized)
        return ev

    def _apply_normalized(self, data: dict) -> None:
        mid = str(data.get("message_id") or data.get("id") or data.get("message", {}).get("id") or "")
        event = str(data.get("event") or data.get("status") or "").lower()
        if not mid:
            return
        msg = OutboundMessage.objects.filter(provider_message_id=mid).first()
        if not msg:
            return
        if "deliver" in event:
            msg.status = OutboundStatus.DELIVERED
            msg.save(update_fields=["status", "updated_at"])
            MessageEvent.objects.create(
                message=msg,
                event_type=MessageEventType.DELIVERED,
                payload=data,
            )
        elif "bounce" in event:
            msg.status = OutboundStatus.BOUNCED
            msg.save(update_fields=["status", "updated_at"])
            MessageEvent.objects.create(
                message=msg,
                event_type=MessageEventType.BOUNCED,
                payload=data,
            )
        elif "complaint" in event or "spam" in event:
            msg.status = OutboundStatus.COMPLAINED
            msg.save(update_fields=["status", "updated_at"])
            MessageEvent.objects.create(
                message=msg,
                event_type=MessageEventType.COMPLAINED,
                payload=data,
            )
