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
from apps.email_templates.models import TemplateCategory
from apps.tenants.models import SenderProfile, Tenant
from apps.ui.forms import TenantForm
from apps.ui.tenant_validators import from_email_allowed_for_tenant
from apps.workflows.models import WorkflowStepType

User = get_user_model()

_inp = "w-full rounded-md border border-surface-600 bg-surface-800 px-3 py-2 text-sm text-white"
_chk = "h-4 w-4 rounded border-surface-600 text-accent"


class PortalSenderProfileForm(forms.ModelForm):
    """Create/edit sender profile; tenant must belong to portal account."""

    class Meta:
        model = SenderProfile
        fields = [
            "tenant",
            "name",
            "category",
            "from_name",
            "from_email",
            "reply_to",
            "is_default",
            "is_active",
        ]
        widgets = {
            "tenant": forms.Select(attrs={"class": _inp}),
            "name": forms.TextInput(attrs={"class": _inp}),
            "category": forms.Select(attrs={"class": _inp}),
            "from_name": forms.TextInput(attrs={"class": _inp}),
            "from_email": forms.EmailInput(attrs={"class": _inp}),
            "reply_to": forms.EmailInput(attrs={"class": _inp}),
            "is_default": forms.CheckboxInput(attrs={"class": _chk}),
            "is_active": forms.CheckboxInput(attrs={"class": _chk}),
        }

    def __init__(self, *args, account: Account, **kwargs):
        super().__init__(*args, **kwargs)
        self._account = account
        self.fields["tenant"].queryset = Tenant.objects.filter(account=account).order_by("name")
        self.fields["tenant"].label = "App / tenant"
        self.fields["reply_to"].required = False
        if self.instance.pk:
            self.fields["tenant"].disabled = True
            self.fields["tenant"].help_text = "Tenant cannot be changed after creation."

    def clean_tenant(self):
        tenant = self.cleaned_data.get("tenant")
        if tenant and tenant.account_id != self._account.id:
            raise forms.ValidationError("Invalid tenant for this account.")
        return tenant

    def clean(self):
        data = super().clean()
        email = (data.get("from_email") or "").strip()
        tenant = data.get("tenant") or getattr(self.instance, "tenant", None)
        if tenant and email:
            sd = (tenant.sending_domain or "").strip()
            if sd and not from_email_allowed_for_tenant(email, sd):
                self.add_error(
                    "from_email",
                    f"From address must be on the tenant sending domain ({sd}).",
                )
        return data


class PortalNewEmailTemplateForm(forms.Form):
    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.none(),
        label="App / tenant",
        widget=forms.Select(attrs={"class": _inp}),
    )
    key = forms.SlugField(widget=forms.TextInput(attrs={"class": _inp}))
    name = forms.CharField(widget=forms.TextInput(attrs={"class": _inp}))
    category = forms.ChoiceField(
        choices=TemplateCategory.choices,
        widget=forms.Select(attrs={"class": _inp}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": _inp}),
    )

    def __init__(self, *args, account: Account, **kwargs):
        self._account = account
        super().__init__(*args, **kwargs)
        self.fields["tenant"].queryset = Tenant.objects.filter(account=account).order_by("name")

    def clean_tenant(self):
        t = self.cleaned_data.get("tenant")
        if t and t.account_id != self._account.id:
            raise forms.ValidationError("Invalid tenant.")
        return t


class PortalTemplateVersionForm(forms.Form):
    subject_template = forms.CharField(
        label="Subject line (template)",
        widget=forms.TextInput(attrs={"class": _inp}),
    )
    preview_text_template = forms.CharField(
        required=False,
        label="Preview text",
        widget=forms.TextInput(attrs={"class": _inp}),
    )
    html_template = forms.CharField(
        label="HTML body",
        widget=forms.Textarea(attrs={"rows": 12, "class": _inp + " font-mono text-xs"}),
    )
    text_template = forms.CharField(
        required=False,
        label="Plain text",
        widget=forms.Textarea(attrs={"rows": 6, "class": _inp + " font-mono text-xs"}),
    )


class PortalWorkflowStepForm(forms.Form):
    order = forms.IntegerField(min_value=0, widget=forms.NumberInput(attrs={"class": _inp}))
    step_type = forms.ChoiceField(
        choices=[
            (WorkflowStepType.SEND_TEMPLATE, "Send template email"),
            (WorkflowStepType.WAIT_DURATION, "Wait (duration)"),
            (WorkflowStepType.END, "End workflow"),
        ],
        widget=forms.Select(attrs={"class": _inp}),
    )
    template_key = forms.SlugField(
        required=False,
        help_text="Required for send-template steps.",
        widget=forms.TextInput(attrs={"class": _inp}),
    )
    wait_seconds = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": _inp}),
    )

    def clean(self):
        data = super().clean()
        st = data.get("step_type")
        tk = (data.get("template_key") or "").strip()
        ws = data.get("wait_seconds")
        if st == WorkflowStepType.SEND_TEMPLATE and not tk:
            raise forms.ValidationError("Template key is required for send-template steps.")
        if st == WorkflowStepType.WAIT_DURATION and ws is None:
            raise forms.ValidationError("Wait seconds required for wait steps.")
        return data


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
