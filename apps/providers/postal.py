"""
Postal HTTP API adapter (skeleton + working send path via httpx).

Designed for self-hosted Postal on a VPS; safe to leave unconfigured in dev.
"""

import logging
from typing import Any
from urllib.parse import urljoin

import httpx
from django.conf import settings

from apps.providers.base import BaseEmailProvider, EmailMessageDTO, SendResult

logger = logging.getLogger(__name__)


class PostalEmailProvider(BaseEmailProvider):
    name = "postal"

    def __init__(self):
        self.base_url = (getattr(settings, "POSTAL_BASE_URL", "") or "").rstrip("/")
        self.api_key = getattr(settings, "POSTAL_SERVER_API_KEY", "") or ""
        self.timeout = float(getattr(settings, "POSTAL_TIMEOUT", 30))
        self.verify = getattr(settings, "POSTAL_USE_TLS_VERIFY", True)

    def validate_config(self) -> tuple[bool, str]:
        if not self.base_url or not self.api_key:
            return False, "POSTAL_BASE_URL and POSTAL_SERVER_API_KEY are required"
        return True, ""

    def health_check(self) -> tuple[bool, str]:
        """
        Postal's HTTP API is RPC-style (POST + JSON); there is no guaranteed GET /api/v1/status
        on every install (often 404). We check:
        1) TLS + host reachability via GET on the base URL (web UI / redirect).
        2) API + server key via POST api/v1/send/message with an empty body — Postal returns
           JSON with a `status` field (e.g. parameter-error) without sending mail.
        """
        ok, msg = self.validate_config()
        if not ok:
            return False, msg
        try:
            root = self.base_url.rstrip("/") + "/"
            r0 = httpx.get(
                root,
                timeout=self.timeout,
                verify=self.verify,
                follow_redirects=True,
            )
            if r0.status_code >= 500:
                return False, f"host HTTP {r0.status_code}"

            url = urljoin(self.base_url + "/", "api/v1/send/message")
            r = httpx.post(
                url,
                json={},
                headers={"X-Server-API-Key": self.api_key},
                timeout=self.timeout,
                verify=self.verify,
            )
            ct = r.headers.get("content-type", "")
            data: dict[str, Any] = {}
            if ct.startswith("application/json"):
                try:
                    parsed = r.json()
                    if isinstance(parsed, dict):
                        data = parsed
                except Exception:
                    pass
            if isinstance(data, dict) and "status" in data:
                st = data.get("status")
                return True, f"postal_api status={st!r} host_http={r0.status_code} api_http={r.status_code}"
            if r.status_code < 500:
                return True, f"host_http={r0.status_code} api_http={r.status_code} body={r.text[:300]}"
            return False, f"api_http={r.status_code} {r.text[:500]}"
        except Exception as e:
            return False, str(e)

    def send_message(self, message: EmailMessageDTO) -> SendResult:
        ok, err = self.validate_config()
        if not ok:
            return SendResult(success=False, error_code="config", error_detail=err)

        url = urljoin(self.base_url + "/", "api/v1/send/message")
        payload: dict[str, Any] = {
            "to": [message.to_email],
            "from": f"{message.from_name} <{message.from_email}>"
            if message.from_name
            else message.from_email,
            "subject": message.subject,
            "html_body": message.html_body,
            "plain_body": message.text_body,
        }
        if message.reply_to:
            payload["reply_to"] = message.reply_to
        if message.cc:
            payload["cc"] = message.cc
        if message.bcc:
            payload["bcc"] = message.bcc

        try:
            r = httpx.post(
                url,
                json=payload,
                headers={"X-Server-API-Key": self.api_key},
                timeout=self.timeout,
                verify=self.verify,
            )
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code >= 400:
                return SendResult(
                    success=False,
                    error_code=f"http_{r.status_code}",
                    error_detail=r.text[:2000],
                    raw_response=data if isinstance(data, dict) else {},
                )
            mid = ""
            if isinstance(data, dict):
                mid = str(data.get("message_id") or data.get("id") or "")
            return SendResult(success=True, provider_message_id=mid, raw_response=data if isinstance(data, dict) else {})
        except Exception as e:
            code, detail = self.normalize_error(e)
            logger.exception("Postal send failed")
            return SendResult(success=False, error_code=code, error_detail=detail)

    def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        import json

        try:
            return json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            return {"event": "parse_error", "raw": raw_body.decode("utf-8", errors="replace")[:2000]}
