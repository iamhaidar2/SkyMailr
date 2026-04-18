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
from apps.tenants.models import SenderProfile, Tenant, TenantDomain
from apps.tenants.services.domain_dns_instructions import normalize_fqdn
from apps.ui.forms import TenantForm
from apps.ui.tenant_validators import from_email_allowed_for_tenant
from apps.workflows.models import WorkflowStepType

User = get_user_model()

_inp = (
    "w-full rounded-md border border-surface-600 bg-surface-800 px-3 py-2 text-sm "
    "text-white placeholder:text-slate-500"
)
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
            "name": forms.TextInput(
                attrs={"class": _inp, "placeholder": "e.g. Main — transactional", "autocomplete": "off"}
            ),
            "category": forms.Select(attrs={"class": _inp}),
            "from_name": forms.TextInput(
                attrs={"class": _inp, "placeholder": "e.g. Acme Support", "autocomplete": "organization"}
            ),
            "from_email": forms.EmailInput(
                attrs={"class": _inp, "placeholder": "support@yourdomain.com", "autocomplete": "email"}
            ),
            "reply_to": forms.EmailInput(
                attrs={
                    "class": _inp,
                    "placeholder": "replies@yourdomain.com (optional)",
                    "autocomplete": "email",
                }
            ),
            "is_default": forms.CheckboxInput(attrs={"class": _chk}),
            "is_active": forms.CheckboxInput(attrs={"class": _chk}),
        }

    def __init__(self, *args, account: Account, single_tenant: Tenant | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._account = account
        self.fields["tenant"].queryset = Tenant.objects.filter(account=account).order_by("name")
        self.fields["tenant"].label = "Connected app"
        self.fields["reply_to"].required = False
        if single_tenant is not None and self.instance._state.adding:
            self.fields["tenant"].initial = single_tenant.pk
            self.fields["tenant"].queryset = Tenant.objects.filter(pk=single_tenant.pk)
            self.fields["tenant"].widget = forms.HiddenInput()
        # UUID pk is assigned on model __init__; only lock tenant after the row exists in the DB.
        if not self.instance._state.adding:
            self.fields["tenant"].disabled = True
            self.fields["tenant"].help_text = "Connected app cannot be changed after creation."

    def clean(self):
        # Validates tenant account + from_email vs tenant.sending_domain when set.
        data = super().clean()
        tenant = data.get("tenant")
        if tenant and tenant.account_id != self._account.id:
            self.add_error("tenant", "Invalid tenant for this account.")
        email = (data.get("from_email") or "").strip()
        tenant_for_email = tenant or getattr(self.instance, "tenant", None)
        if tenant_for_email and email:
            sd = (tenant_for_email.sending_domain or "").strip()
            if sd and not from_email_allowed_for_tenant(email, sd):
                self.add_error(
                    "from_email",
                    f"From address must be on the tenant sending domain ({sd}).",
                )
        return data


class PortalNewEmailTemplateForm(forms.Form):
    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.none(),
        label="Connected app",
        widget=forms.Select(attrs={"class": _inp}),
    )
    name = forms.CharField(
        label="Name",
        widget=forms.TextInput(
            attrs={"class": _inp, "placeholder": "e.g. Welcome email", "autocomplete": "off"}
        ),
    )
    key = forms.SlugField(
        label="Key",
        widget=forms.TextInput(
            attrs={
                "class": _inp,
                "placeholder": "e.g. welcome_new_user",
                "autocomplete": "off",
            }
        ),
    )
    category = forms.ChoiceField(
        choices=TemplateCategory.choices,
        widget=forms.Select(attrs={"class": _inp}),
    )
    description = forms.CharField(
        required=False,
        label="Description",
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": _inp,
                "placeholder": "Short internal note (optional). Used as AI context when you choose Create with AI.",
            }
        ),
    )

    def __init__(self, *args, account: Account, single_tenant: Tenant | None = None, **kwargs):
        self._account = account
        super().__init__(*args, **kwargs)
        self.fields["tenant"].queryset = Tenant.objects.filter(account=account).order_by("name")
        if single_tenant is not None:
            self.fields["tenant"].initial = single_tenant.pk
            self.fields["tenant"].queryset = Tenant.objects.filter(pk=single_tenant.pk)
            self.fields["tenant"].widget = forms.HiddenInput()

    def clean_tenant(self):
        t = self.cleaned_data.get("tenant")
        if t and t.account_id != self._account.id:
            raise forms.ValidationError("Invalid tenant.")
        return t


class PortalTemplateVersionForm(forms.Form):
    subject_template = forms.CharField(
        label="Subject line (template)",
        widget=forms.TextInput(
            attrs={"class": _inp, "placeholder": "e.g. Welcome back, {{ name }}", "autocomplete": "off"}
        ),
    )
    preview_text_template = forms.CharField(
        required=False,
        label="Preview text",
        widget=forms.TextInput(
            attrs={"class": _inp, "placeholder": "e.g. Your weekly summary inside", "autocomplete": "off"}
        ),
    )
    html_template = forms.CharField(
        label="HTML body",
        widget=forms.Textarea(
            attrs={
                "rows": 12,
                "class": _inp + " font-mono text-xs",
                "placeholder": "<p>Hi {{ name }},</p><p>...</p>",
                "autocomplete": "off",
            }
        ),
    )
    text_template = forms.CharField(
        required=False,
        label="Plain text",
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "class": _inp + " font-mono text-xs",
                "placeholder": "Hi {{ name }},\n\nPlain text version...",
                "autocomplete": "off",
            }
        ),
    )


class PortalWorkflowStepForm(forms.Form):
    order = forms.IntegerField(
        min_value=0,
        widget=forms.NumberInput(attrs={"class": _inp, "placeholder": "0"}),
    )
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
        widget=forms.TextInput(
            attrs={"class": _inp, "placeholder": "e.g. welcome_email", "autocomplete": "off"}
        ),
    )
    wait_seconds = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": _inp, "placeholder": "e.g. 86400"}),
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


# Inline styles so the field stays hidden even if Tailwind utilities are missing or overridden.
_SIGNUP_HONEYPOT_WIDGET = forms.TextInput(
    attrs={
        "class": "customer-signup-honeypot",
        "tabindex": "-1",
        "autocomplete": "off",
        "aria-hidden": "true",
        "style": (
            "position:absolute!important;left:-10000px!important;width:1px!important;"
            "height:1px!important;padding:0!important;margin:0!important;overflow:hidden!important;"
            "opacity:0!important;pointer-events:none!important;border:0!important;"
        ),
    }
)


class CustomerSignupForm(forms.Form):
    display_name = forms.CharField(
        max_length=150,
        label="Your name",
        widget=forms.TextInput(
            attrs={"class": _inp, "placeholder": "Jane Doe", "autocomplete": "name"}
        ),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"class": _inp, "placeholder": "you@company.com", "autocomplete": "email"}
        ),
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
        widget=forms.TextInput(
            attrs={"class": _inp, "placeholder": "e.g. Acme Labs", "autocomplete": "organization"}
        ),
    )
    account_slug = forms.SlugField(
        max_length=64,
        label="Account URL slug",
        help_text="Lowercase letters, numbers, and hyphens only.",
        widget=forms.TextInput(attrs={"class": _inp, "placeholder": "acme-corp"}),
    )
    # Anti-bot honeypot: must stay empty. Declared last so it renders after labeled fields.
    company_website = forms.CharField(
        required=False,
        label="",
        widget=_SIGNUP_HONEYPOT_WIDGET,
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
        if (self.data.get("company_website") or "").strip():
            raise forms.ValidationError("Unable to complete signup.")
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


class PortalTenantCreateForm(TenantForm):
    """Minimal create flow — name and slug only; other fields live under app settings."""

    class Meta(TenantForm.Meta):
        fields = ["name", "slug"]


class PortalTenantSettingsForm(TenantForm):
    """Full app settings on the portal (parity with operator tenant form)."""

    class Meta(TenantForm.Meta):
        pass


class PortalApiKeyForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        initial="default",
        widget=forms.TextInput(
            attrs={"class": _inp, "placeholder": "e.g. production CI", "autocomplete": "off"}
        ),
    )


class PortalInviteForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"class": _inp, "placeholder": "colleague@company.com", "autocomplete": "email"}
        )
    )
    role = forms.ChoiceField(choices=[], widget=forms.Select(attrs={"class": _inp}))

    def __init__(self, *args, inviter_role: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        choices = [
            (AccountRole.ADMIN, "Admin"),
            (AccountRole.EDITOR, "Editor"),
            (AccountRole.VIEWER, "Viewer"),
            (AccountRole.BILLING, "Billing"),
        ]
        if inviter_role == AccountRole.OWNER:
            choices = [(AccountRole.OWNER, "Owner")] + choices
        self.fields["role"].choices = choices

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()


class PortalMembershipEditForm(forms.ModelForm):
    class Meta:
        model = AccountMembership
        fields = ["role", "is_active"]
        widgets = {
            "role": forms.Select(attrs={"class": _inp}),
            "is_active": forms.CheckboxInput(attrs={"class": _chk}),
        }

    def __init__(self, *args, actor_role: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._actor_role = actor_role
        choices = list(AccountRole.choices)
        if actor_role == AccountRole.ADMIN:
            choices = [c for c in choices if c[0] != AccountRole.OWNER]
        self.fields["role"].choices = choices
        self.fields["is_active"].label = "Active"


class InviteSignupForm(forms.Form):
    display_name = forms.CharField(
        max_length=150,
        label="Your name",
        widget=forms.TextInput(
            attrs={"class": _inp, "placeholder": "Jane Doe", "autocomplete": "name"}
        ),
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": _inp, "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs={"class": _inp, "autocomplete": "new-password"}),
    )

    def __init__(self, *args, invite_email: str = "", **kwargs):
        self._invite_email = (invite_email or "").strip().lower()
        super().__init__(*args, **kwargs)

    def clean(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        if p1:
            validate_password(p1)
        return self.cleaned_data


class PortalTenantDomainForm(forms.Form):
    domain = forms.CharField(
        label="Domain or subdomain",
        help_text="Lowercase host only — e.g. mail.example.com (no https:// or paths).",
        widget=forms.TextInput(attrs={"class": _inp, "placeholder": "mail.example.com"}),
    )

    def __init__(self, *args, tenant: Tenant, **kwargs):
        self._tenant = tenant
        super().__init__(*args, **kwargs)

    def clean_domain(self):
        raw = self.cleaned_data.get("domain") or ""
        d = normalize_fqdn(raw)
        if not d or len(d) > 253:
            raise forms.ValidationError("Enter a valid domain.")
        if ".." in d or " " in d or "*" in d:
            raise forms.ValidationError("Invalid domain format.")
        if TenantDomain.objects.filter(tenant=self._tenant, domain=d).exists():
            raise forms.ValidationError("This domain is already added for this tenant.")
        return d
