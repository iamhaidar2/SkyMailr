import uuid

from django.db import models


class DummyStoredEmail(models.Model):
    """Persists messages when using DummyEmailProvider (dev / tests)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
