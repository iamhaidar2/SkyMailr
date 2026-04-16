"""Customer portal signup and account-scoped forms."""

from __future__ import annotations

import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from django.db.models import Q
from django.utils.text import slugify

from apps.accounts.models import Account, AccountMembership, AccountRole, AccountStatus
from apps.tenants.models import Tenant
from apps.ui.forms import TenantForm

User = get_user_model()

_inp = "w-full rounded-md border border-surface-600 bg-surface-800 px-3 py-2 text-sm text-white"


class CustomerSignupForm(forms.Form):
    display_name = forms.CharField(
        max_length=150,
        label="Your name",
        widget=forms.TextInput(attrs={"class": _inp, "autocomplete": "name"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": _inp, "autocomplete": "email"}),
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": _inp, "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs={"class": _inp, "autocomplete": "new-password"}),
    )
    account_name = forms.CharField(
        max_length=200,
        label="Company or account name",
        widget=forms.TextInput(attrs={"class": _inp}),
    )
    account_slug = forms.SlugField(
        max_length=64,
        label="Account URL slug",
        help_text="Lowercase letters, numbers, and hyphens only.",
        widget=forms.TextInput(attrs={"class": _inp, "placeholder": "acme-corp"}),
    )

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        validate_email(email)
        if User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_account_slug(self):
        slug = (self.cleaned_data.get("account_slug") or "").strip().lower()
        if not slug:
            raise forms.ValidationError("Slug is required.")
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", slug):
            raise forms.ValidationError("Use lowercase letters, numbers, and hyphens only.")
        if Account.objects.filter(slug__iexact=slug).exists():
            raise forms.ValidationError("This account slug is already taken.")
        return slug

    def clean(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        if p1:
            validate_password(p1)
        return self.cleaned_data

    def suggest_slug_from_name(self, name: str) -> str:
        base = slugify(name) or "account"
        candidate = base[:64]
        if not Account.objects.filter(slug=candidate).exists():
            return candidate
        n = 2
        while True:
            suffix = f"-{n}"
            stem = base[: 64 - len(suffix)]
            cand = f"{stem}{suffix}"
            if not Account.objects.filter(slug=cand).exists():
                return cand
            n += 1


class PortalTenantForm(TenantForm):
    """Same as operator TenantForm; account is set in the view."""

    class Meta(TenantForm.Meta):
        pass


class PortalApiKeyForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        initial="default",
        widget=forms.TextInput(attrs={"class": _inp}),
    )
