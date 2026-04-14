import logging

from django.db import transaction

from apps.providers.base import BaseEmailProvider, EmailMessageDTO, SendResult
from apps.providers.models import DummyStoredEmail

logger = logging.getLogger(__name__)


class DummyEmailProvider(BaseEmailProvider):
    name = "dummy"

    def send_message(self, message: EmailMessageDTO) -> SendResult:
        payload = {
            "to_email": message.to_email,
            "subject": message.subject,
            "html_body": message.html_body[:50000],
            "text_body": message.text_body[:50000],
        }
        with transaction.atomic():
            row = DummyStoredEmail.objects.create(payload=payload)
        logger.info("DummyEmailProvider stored message %s", row.id)
        return SendResult(success=True, provider_message_id=str(row.id), raw_response=payload)
