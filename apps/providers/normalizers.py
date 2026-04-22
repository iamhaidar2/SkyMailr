"""
Normalize provider webhook payloads into a stable internal shape for ingestion.

Postal payloads vary: status events use `status` + `message`, bounces use
`original_message` + `bounce`, opens/clicks nest under `message`, and some
installations wrap bodies in `payload` / `data`. This module is defensive and
must not raise on unexpected input.
"""

from __future__ import annotations

import copy
from typing import Any

# Canonical event_type values stored on ProviderWebhookEvent.normalized and used by webhook_service.
EVENT_DELIVERED = "delivered"
EVENT_BOUNCED = "bounced"
EVENT_COMPLAINED = "complained"
EVENT_FAILED = "failed"
EVENT_OPENED = "opened"
EVENT_CLICKED = "clicked"
EVENT_UNKNOWN = "unknown"

BOUNCE_HARD = "hard"
BOUNCE_SOFT = "soft"
BOUNCE_NONE = ""


def _s(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (int, float)):
        return str(v)
    return str(v).strip()


def _dig(d: dict[str, Any], *keys: str) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _unwrap_nested(raw: dict[str, Any]) -> dict[str, Any]:
    """If Postal or a proxy wraps the body, unwrap to the inner dict when obvious."""
    for key in ("payload", "data", "body", "webhook"):
        inner = raw.get(key)
        if isinstance(inner, dict) and (
            "message" in inner or "original_message" in inner or "status" in inner or "bounce" in inner
        ):
            merged = {**inner, **{k: v for k, v in raw.items() if k != key and k not in inner}}
            return merged
    return raw


def _message_blob(raw: dict[str, Any]) -> dict[str, Any]:
    for path in (
        ("message",),
        ("original_message",),
        ("payload", "message"),
        ("data", "message"),
    ):
        node = raw
        ok = True
        for p in path:
            if not isinstance(node, dict) or p not in node:
                ok = False
                break
            node = node[p]
        if ok and isinstance(node, dict):
            return node
    return {}


def _postal_message_id_candidates(raw: dict[str, Any]) -> list[str]:
    """Collect possible Postal message identifiers (SkyMailr stores provider_message_id from send API)."""
    out: list[str] = []
    seen: set[str] = set()

    def add(v: Any) -> None:
        s = _s(v)
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    for key in ("message_id", "id", "token"):
        add(raw.get(key))

    for blob in (_message_blob(raw),):
        for key in ("id", "token", "message_id"):
            add(blob.get(key))

    om = raw.get("original_message")
    if isinstance(om, dict):
        for key in ("id", "token", "message_id"):
            add(om.get(key))

    m = raw.get("message")
    if isinstance(m, dict):
        for key in ("id", "token", "message_id"):
            add(m.get(key))

    return out


def _pick_provider_message_id(raw: dict[str, Any]) -> str:
    for cand in _postal_message_id_candidates(raw):
        if cand:
            return cand
    return ""


def _recipient_from(raw: dict[str, Any]) -> str:
    for path in (
        ("to",),
        ("recipient",),
        ("email",),
        ("message", "to"),
        ("original_message", "to"),
        ("payload", "message", "to"),
    ):
        node: Any = raw
        for p in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(p)
        s = _s(node)
        if s:
            return s
    return ""


def _provider_event_id_postal(raw: dict[str, Any]) -> str:
    for key in ("uuid", "id", "event_id", "webhook_id"):
        v = raw.get(key)
        s = _s(v)
        if s and s not in ("message", "payload"):
            return s
    bounce = raw.get("bounce")
    if isinstance(bounce, dict):
        s = _s(bounce.get("id")) or _s(bounce.get("token"))
        if s:
            return f"bounce:{s}"
    om = raw.get("original_message")
    if isinstance(om, dict):
        s = _s(om.get("id")) or _s(om.get("token"))
        if s:
            return f"orig:{s}"
    st = _s(raw.get("status"))
    ev = _s(raw.get("event"))
    ts = raw.get("timestamp")
    mid = _pick_provider_message_id(raw)
    if mid or st or ev:
        return f"hash:{mid}:{st}:{ev}:{ts!s}"
    return ""


def _timestamp_from(raw: dict[str, Any]) -> str:
    for key in ("timestamp", "time", "created_at", "occurred_at"):
        v = raw.get(key)
        if v is not None and _s(v):
            return _s(v)
    m = _message_blob(raw)
    for key in ("timestamp",):
        v = m.get(key)
        if v is not None and _s(v):
            return _s(v)
    return ""


def _reason_from(raw: dict[str, Any]) -> str:
    for key in ("details", "output", "reason", "error", "description", "detail"):
        v = raw.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:4000]
    return ""


def _classify_postal_bounce_type(bounce: dict[str, Any] | None) -> str:
    """
    Infer hard vs soft from bounce / DSN hints.
    Ambiguous bounces default to soft to avoid over-suppressing recipients.
    """
    if not isinstance(bounce, dict):
        return BOUNCE_SOFT
    chunks: list[str] = []
    for key in ("subject", "plain_body", "html_body", "message_id", "from", "to"):
        v = bounce.get(key)
        if isinstance(v, str):
            chunks.append(v.lower())
    text = " ".join(chunks)
    hard_markers = (
        "550 5.1.1",
        "551 ",
        "552 ",
        "553 ",
        "554 ",
        "5.1.0",
        "5.1.1",
        "5.1.2",
        "5.1.3",
        "user unknown",
        "unknown user",
        "no such user",
        "invalid recipient",
        "mailbox unavailable",
        "does not exist",
        "address rejected",
        "recipient rejected",
        "permanent failure",
        "not found",
    )
    soft_markers = (
        "451 ",
        "452 ",
        "421 ",
        "450 ",
        "4.2.2",
        "4.3.1",
        "4.4.1",
        "mailbox full",
        "quota exceeded",
        "greylist",
        "try again",
        "temporar",
        "deferred",
    )
    if any(m in text for m in hard_markers):
        return BOUNCE_HARD
    if any(m in text for m in soft_markers):
        return BOUNCE_SOFT
    return BOUNCE_SOFT


def _postal_event_type_and_flags(raw: dict[str, Any]) -> tuple[str, str, bool]:
    """
    Returns (event_type, bounce_type, is_terminal_failure).
    bounce_type only for bounced; otherwise BOUNCE_NONE.
    is_terminal_failure is meaningful when event_type == failed.
    """
    raw_u = _unwrap_nested(raw)

    event_name = _s(raw_u.get("event")).lower()
    status = _s(raw_u.get("status")).lower()
    combined = f"{event_name} {status}".strip()

    # Bounce DSN pair (Postal docs).
    if isinstance(raw_u.get("original_message"), dict) and isinstance(raw_u.get("bounce"), dict):
        bt = _classify_postal_bounce_type(raw_u["bounce"])
        return EVENT_BOUNCED, bt, True

    msg = _message_blob(raw_u)
    spam_status = _s(msg.get("spam_status")).lower()
    # Spam / abuse complaint signals (not DSN bounces).
    if spam_status == "spam" or "complaint" in combined or "abuse" in combined:
        if "bounce" not in combined and not isinstance(raw_u.get("bounce"), dict):
            return EVENT_COMPLAINED, BOUNCE_NONE, True

    # Click / open tracking shapes.
    if isinstance(raw_u.get("message"), dict) and _s(raw_u.get("url")):
        return EVENT_CLICKED, BOUNCE_NONE, True
    if isinstance(raw_u.get("message"), dict) and (
        _s(raw_u.get("ip_address")) or _s(raw_u.get("user_agent"))
    ) and "status" not in raw_u:
        return EVENT_OPENED, BOUNCE_NONE, True

    # Status lifecycle (Postal message status webhooks).
    if "message" in raw_u or status:
        if status == "sent" or status == "delivered" or "sent" in status:
            return EVENT_DELIVERED, BOUNCE_NONE, True
        if "delay" in status or "delayed" in combined or "messagedelayed" in combined.replace(" ", ""):
            return EVENT_FAILED, BOUNCE_NONE, False
        if "held" in status or "hold" in combined:
            return EVENT_FAILED, BOUNCE_NONE, False
        if "fail" in status or "error" in status or "hardfail" in combined:
            return EVENT_FAILED, BOUNCE_NONE, True
        if "bounce" in status and "messagebounced" not in combined:
            return EVENT_BOUNCED, _classify_postal_bounce_type(raw_u.get("bounce") if isinstance(raw_u.get("bounce"), dict) else None), True

    # Flat legacy / tests: { "message_id", "event": "delivered" }
    if _s(raw_u.get("message_id")) or _pick_provider_message_id(raw_u):
        ev = event_name or status
        if "deliver" in ev or ev == "sent":
            return EVENT_DELIVERED, BOUNCE_NONE, True
        if "bounce" in ev:
            return EVENT_BOUNCED, BOUNCE_SOFT, True
        if "complaint" in ev or "spam" in ev:
            return EVENT_COMPLAINED, BOUNCE_NONE, True
        if "fail" in ev:
            return EVENT_FAILED, BOUNCE_NONE, True
        if "open" in ev or "load" in ev:
            return EVENT_OPENED, BOUNCE_NONE, True
        if "click" in ev:
            return EVENT_CLICKED, BOUNCE_NONE, True

    return EVENT_UNKNOWN, BOUNCE_NONE, True


def _normalize_postal(raw: dict[str, Any]) -> dict[str, Any]:
    raw_u = _unwrap_nested(raw)
    event_type, bounce_type, is_terminal = _postal_event_type_and_flags(raw_u)
    mid = _pick_provider_message_id(raw_u)
    recipient = _recipient_from(raw_u) or _recipient_from(_message_blob(raw_u))
    reason = _reason_from(raw_u)
    if event_type == EVENT_BOUNCED and isinstance(raw_u.get("bounce"), dict):
        breason = _reason_from(raw_u["bounce"])
        if breason and not reason:
            reason = breason

    return {
        "provider": "postal",
        "provider_event_id": _provider_event_id_postal(raw_u),
        "provider_message_id": mid,
        "event_type": event_type,
        "recipient": recipient,
        "bounce_type": bounce_type if event_type == EVENT_BOUNCED else BOUNCE_NONE,
        "reason": reason,
        "timestamp": _timestamp_from(raw_u),
        "is_terminal_failure": is_terminal,
        "raw": copy.deepcopy(raw) if isinstance(raw, dict) else {},
    }


def _normalize_generic(provider: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Best-effort mapping for non-Postal providers or future adapters."""
    mid = _s(
        raw.get("message_id")
        or raw.get("id")
        or _dig(raw, "message", "id")
        or _dig(raw, "payload", "message", "id")
    )
    ev = _s(raw.get("event") or raw.get("status")).lower()
    event_type = EVENT_UNKNOWN
    if "deliver" in ev or ev == "sent":
        event_type = EVENT_DELIVERED
    elif "bounce" in ev:
        event_type = EVENT_BOUNCED
    elif "complaint" in ev or "spam" in ev:
        event_type = EVENT_COMPLAINED
    elif "fail" in ev:
        event_type = EVENT_FAILED
    elif "open" in ev:
        event_type = EVENT_OPENED
    elif "click" in ev:
        event_type = EVENT_CLICKED
    bounce_type = BOUNCE_SOFT if event_type == EVENT_BOUNCED else BOUNCE_NONE
    return {
        "provider": provider,
        "provider_event_id": _s(raw.get("uuid") or raw.get("id") or ""),
        "provider_message_id": mid,
        "event_type": event_type,
        "recipient": _recipient_from(raw),
        "bounce_type": bounce_type,
        "reason": _reason_from(raw),
        "timestamp": _timestamp_from(raw),
        "is_terminal_failure": True,
        "raw": copy.deepcopy(raw),
    }


def normalize_provider_webhook(provider: str, raw: Any) -> dict[str, Any]:
    """
    Return a dict:
      provider, provider_event_id, provider_message_id, event_type,
      recipient, bounce_type ('hard'|'soft'|''), reason, timestamp,
      is_terminal_failure (bool), raw (dict copy).
    """
    if not isinstance(raw, dict):
        return {
            "provider": provider,
            "provider_event_id": "",
            "provider_message_id": "",
            "event_type": EVENT_UNKNOWN,
            "recipient": "",
            "bounce_type": BOUNCE_NONE,
            "reason": "",
            "timestamp": "",
            "is_terminal_failure": True,
            "raw": {},
        }

    p = (provider or "").strip().lower()
    if p == "postal":
        return _normalize_postal(raw)
    return _normalize_generic(p or "unknown", raw)
