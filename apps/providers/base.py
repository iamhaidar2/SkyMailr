from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EmailMessageDTO:
    to_email: str
    to_name: str = ""
    from_email: str = ""
    from_name: str = ""
    reply_to: str = ""
    subject: str = ""
    html_body: str = ""
    text_body: str = ""
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class SendResult:
    success: bool
    provider_message_id: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_detail: str = ""


class BaseEmailProvider(ABC):
    name: str = "base"

    @abstractmethod
    def send_message(self, message: EmailMessageDTO) -> SendResult:
        pass

    def send_bulk(self, messages: list[EmailMessageDTO]) -> list[SendResult]:
        return [self.send_message(m) for m in messages]

    def validate_config(self) -> tuple[bool, str]:
        return True, ""

    def health_check(self) -> tuple[bool, str]:
        return True, "ok"

    def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        return {"event": "unknown", "raw": raw_body.decode("utf-8", errors="replace")[:5000]}

    def get_message_status(self, provider_message_id: str) -> dict[str, Any]:
        return {"status": "unknown", "id": provider_message_id}

    def normalize_error(self, exc: Exception) -> tuple[str, str]:
        return type(exc).__name__, str(exc)[:2000]
