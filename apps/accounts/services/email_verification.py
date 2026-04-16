"""Email verification tokens (scaffold — wire sending in portal signup)."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import EmailVerificationToken, UserProfile

logger = logging.getLogger("apps.accounts.audit")

User = get_user_model()
VERIFY_EXPIRY_DAYS = 7


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@transaction.atomic
def create_verification_token(user: User) -> tuple[EmailVerificationToken, str]:
    raw = secrets.token_urlsafe(32)
    tok = EmailVerificationToken.objects.create(
        user=user,
        token_hash=_hash_token(raw),
        expires_at=timezone.now() + timedelta(days=VERIFY_EXPIRY_DAYS),
    )
    return tok, raw


def consume_verification_token(raw: str) -> User | None:
    if not raw:
        return None
    h = _hash_token(raw)
    tok = EmailVerificationToken.objects.filter(token_hash=h).select_related("user").first()
    if not tok or not tok.is_valid():
        return None
    with transaction.atomic():
        tok.consumed_at = timezone.now()
        tok.save(update_fields=["consumed_at"])
        profile, _ = UserProfile.objects.get_or_create(user=tok.user)
        profile.email_verified_at = timezone.now()
        profile.save(update_fields=["email_verified_at", "updated_at"])
    logger.info("email_verified user_id=%s", tok.user_id)
    return tok.user
