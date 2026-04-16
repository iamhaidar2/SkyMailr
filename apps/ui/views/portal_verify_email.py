"""Email verification link handler."""

from __future__ import annotations

from django.contrib import messages as django_messages
from django.shortcuts import redirect, render

from apps.accounts.services.email_verification import consume_verification_token


def verify_email_confirm(request, token: str):
    user = consume_verification_token(token)
    if not user:
        return render(
            request,
            "ui/customer/verify_email_invalid.html",
            {"reason": "This verification link is invalid or has expired."},
            status=400,
        )
    django_messages.success(request, "Your email address has been verified.")
    if request.user.is_authenticated:
        return redirect("portal:dashboard")
    return redirect("portal:login")
