import logging
import uuid

from apps.providers.base import BaseEmailProvider, EmailMessageDTO, SendResult

logger = logging.getLogger(__name__)


class ConsoleEmailProvider(BaseEmailProvider):
    name = "console"

    def send_message(self, message: EmailMessageDTO) -> SendResult:
        mid = str(uuid.uuid4())
        logger.info(
            "[ConsoleEmailProvider] id=%s to=%s subject=%s",
            mid,
            message.to_email,
            message.subject[:200],
        )
        return SendResult(success=True, provider_message_id=mid, raw_response={"mode": "console"})
