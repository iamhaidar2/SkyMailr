"""Send simple transactional emails for the customer portal (Django email layer)."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse


def send_account_invite_email(*, request, invite, raw_token: str) -> None:
    link = request.build_absolute_uri(
        reverse("portal:invite_accept", kwargs={"token": raw_token})
    )
    subject = f"Invitation to join {invite.account.name} on SkyMailr"
    body = render_to_string(
        "accounts/email/account_invite.txt",
        {
            "account_name": invite.account.name,
            "role": invite.get_role_display(),
            "invite_email": invite.email,
            "link": link,
            "expires_at": invite.expires_at,
        },
    )
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [invite.email],
        fail_silently=False,
    )


def send_email_verification_email(*, request, user, raw_token: str) -> None:
    link = request.build_absolute_uri(
        reverse("portal:verify_email_confirm", kwargs={"token": raw_token})
    )
    subject = "Verify your email — SkyMailr"
    body = render_to_string(
        "accounts/email/verify_email.txt",
        {"link": link, "user": user},
    )
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
