"""Public marketing site (homepage and lightweight legal/contact stubs)."""

from __future__ import annotations

from django.shortcuts import render
from django.views.generic import TemplateView

from apps.accounts.plans import PLAN_DEFINITIONS, PLAN_FREE, PLAN_GROWTH, PLAN_STARTER


def marketing_home(request):
    """Premium marketing homepage; pricing figures mirror PLAN_DEFINITIONS."""
    free = PLAN_DEFINITIONS[PLAN_FREE]
    starter = PLAN_DEFINITIONS[PLAN_STARTER]
    growth = PLAN_DEFINITIONS[PLAN_GROWTH]
    return render(
        request,
        "ui/marketing/home.html",
        {
            "page_title": "SkyMailr — Application email automation",
            "plans": {
                "free": free,
                "starter": starter,
                "growth": growth,
            },
        },
    )


class LegalPrivacyView(TemplateView):
    template_name = "ui/marketing/legal/privacy.html"


class LegalTermsView(TemplateView):
    template_name = "ui/marketing/legal/terms.html"


class ContactView(TemplateView):
    template_name = "ui/marketing/contact.html"
