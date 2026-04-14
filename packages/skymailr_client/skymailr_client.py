"""
Minimal HTTP client for source apps (TOMEO, BrainList, ProjMan).

Usage:
    from skymailr_client import SkyMailrClient
    c = SkyMailrClient("https://skymailr.example.com", api_key=os.environ["SKYMAILR_API_KEY"])
    c.send_verification_email("user@example.com", {"user_name": "Ada", "verify_url": "..."})
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class SkyMailrClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(
                f"{self.base_url}{path}",
                json=body,
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    def send_template_email(
        self,
        *,
        template_key: str,
        to_email: str,
        context: dict[str, Any],
        message_type: str = "transactional",
        source_app: str = "app",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "template_key": template_key,
            "to_email": to_email,
            "context": context,
            "message_type": message_type,
            "source_app": source_app,
        }
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._post("/api/v1/messages/send-template/", body)

    def send_verification_email(
        self, to_email: str, context: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        return self.send_template_email(
            template_key="email_verification",
            to_email=to_email,
            context=context,
            message_type="transactional",
            **kwargs,
        )

    def send_password_reset_email(
        self, to_email: str, context: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        return self.send_template_email(
            template_key="password_reset",
            to_email=to_email,
            context=context,
            message_type="transactional",
            **kwargs,
        )

    def send_collaborator_invite(
        self, to_email: str, context: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        return self.send_template_email(
            template_key="collaborator_invite",
            to_email=to_email,
            context=context,
            message_type="transactional",
            **kwargs,
        )

    def send_account_deletion_confirmation(
        self, to_email: str, context: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        return self.send_template_email(
            template_key="account_deletion_confirmation",
            to_email=to_email,
            context=context,
            message_type="transactional",
            **kwargs,
        )

    def enroll_user_in_workflow(
        self,
        workflow_id: str,
        *,
        recipient_email: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = {
            "recipient_email": recipient_email,
            "metadata": metadata or {},
        }
        return self._post(f"/api/v1/workflows/{workflow_id}/enroll/", body)


def client_from_env() -> SkyMailrClient:
    return SkyMailrClient(
        os.environ["SKYMAILR_BASE_URL"],
        os.environ["SKYMAILR_API_KEY"],
    )
