import logging
import os

from django.conf import settings

from apps.providers.base import BaseEmailProvider
from apps.providers.console import ConsoleEmailProvider
from apps.providers.dummy import DummyEmailProvider
from apps.providers.postal import PostalEmailProvider

logger = logging.getLogger(__name__)


def get_email_provider() -> BaseEmailProvider:
    name = (
        getattr(settings, "EMAIL_PROVIDER", None) or os.environ.get("EMAIL_PROVIDER", "dummy")
    ).lower()

    if name == "console":
        return ConsoleEmailProvider()
    if name == "postal":
        return PostalEmailProvider()
    return DummyEmailProvider()
