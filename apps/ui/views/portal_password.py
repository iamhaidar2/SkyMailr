"""Customer portal password reset (Django auth views, themed templates)."""

from __future__ import annotations

from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.urls import reverse_lazy

_inp = "w-full rounded-md border border-surface-600 bg-surface-800 px-3 py-2 text-sm text-white"


class PortalPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update(
            {"class": _inp, "autocomplete": "email", "placeholder": "you@company.com"}
        )


class PortalPasswordResetView(PasswordResetView):
    form_class = PortalPasswordResetForm
    template_name = "ui/customer/password_reset_form.html"
    email_template_name = "ui/customer/password_reset_email.txt"
    subject_template_name = "ui/customer/password_reset_subject.txt"
    success_url = reverse_lazy("portal:password_reset_done")
    extra_email_context = {"product_name": "SkyMailr"}


class PortalPasswordResetDoneView(PasswordResetDoneView):
    template_name = "ui/customer/password_reset_done.html"


class PortalPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "ui/customer/password_reset_confirm.html"
    success_url = reverse_lazy("portal:password_reset_complete")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for _name, field in form.fields.items():
            field.widget.attrs.setdefault("class", _inp)
        return form


class PortalPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "ui/customer/password_reset_complete.html"
