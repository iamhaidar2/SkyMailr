"""Customer portal signup and account-scoped forms."""

from __future__ import annotations

import json
import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from django.db.models import Q
from django.utils.text import slugify

from apps.accounts.models import Account, AccountMembership, AccountRole, AccountStatus
from apps.email_templates.models import TemplateCategory
from apps.messages.models import MessageEventType
from apps.subscriptions.models import SuppressionReason
from apps.tenants.models import SenderProfile, Tenant, TenantDomain
from apps.tenants.services.domain_dns_instructions import normalize_fqdn
from apps.ui.forms import TenantForm, WorkflowEnrollForm
from apps.ui.tenant_validators import from_email_allowed_for_tenant
from apps.workflows.models import WorkflowStep, WorkflowStepType
from apps.workflows.services.enrollment_context import (
    build_default_enrollment_metadata,
    required_template_context_keys,
)

User = get_user_model()

_inp = (
    "w-full rounded-md border border-surface-600 bg-surface-800 px-3 py-2 text-sm "
    "text-white placeholder:text-slate-500"
)
_inp_compact = (
    "w-full min-w-0 rounded-md border border-surface-600 bg-surface-800 px-2 py-1.5 text-sm "
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
    template_key = forms.ChoiceField(
        required=False,
        choices=[],
        label="Template",
        help_text="Required for send-template steps.",
        widget=forms.Select(attrs={"class": _inp}),
    )
    wait_days = forms.IntegerField(
        required=False,
        min_value=0,
        initial=0,
        label="Days",
        widget=forms.NumberInput(attrs={"class": _inp_compact, "placeholder": "0", "min": "0"}),
    )
    wait_hours = forms.IntegerField(
        required=False,
        min_value=0,
        initial=0,
        label="Hours",
        widget=forms.NumberInput(attrs={"class": _inp_compact, "placeholder": "0", "min": "0"}),
    )
    wait_minutes = forms.IntegerField(
        required=False,
        min_value=0,
        initial=0,
        label="Minutes",
        widget=forms.NumberInput(attrs={"class": _inp_compact, "placeholder": "0", "min": "0"}),
    )
    wait_sec = forms.IntegerField(
        required=False,
        min_value=0,
        initial=0,
        label="Seconds",
        widget=forms.NumberInput(attrs={"class": _inp_compact, "placeholder": "0", "min": "0"}),
    )

    def __init__(
        self,
        *args,
        template_keys=None,
        extra_template_keys=None,
        include_blank_step_type: bool = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        keys = set(template_keys or [])
        for x in extra_template_keys or []:
            if (x or "").strip():
                keys.add(x.strip())
        self.fields["template_key"].choices = [("", "— Select template —")] + [
            (k, k) for k in sorted(keys)
        ]
        base_choices = [
            (WorkflowStepType.SEND_TEMPLATE, "Send template email"),
            (WorkflowStepType.WAIT_DURATION, "Wait (duration)"),
            (WorkflowStepType.END, "End workflow"),
        ]
        if include_blank_step_type:
            self.fields["step_type"].choices = [("", "— Select step type —")] + base_choices

    def clean(self):
        cleaned_data = super().clean()
        st = cleaned_data.get("step_type")
        if not st:
            self.add_error("step_type", "Select a step type.")
            return cleaned_data

        def nz(name: str) -> int:
            v = cleaned_data.get(name)
            if v is None:
                return 0
            return int(v)

        total_wait = (
            nz("wait_days") * 86400
            + nz("wait_hours") * 3600
            + nz("wait_minutes") * 60
            + nz("wait_sec")
        )
        cleaned_data["wait_seconds"] = total_wait

        tk = (cleaned_data.get("template_key") or "").strip()
        if st == WorkflowStepType.SEND_TEMPLATE and not tk:
            raise forms.ValidationError("Template key is required for send-template steps.")
        return cleaned_data


def wait_seconds_to_components(total: int | None) -> dict[str, int]:
    t = 0 if total is None else max(0, int(total))
    days, rem = divmod(t, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, sec = divmod(rem, 60)
    return {
        "wait_days": days,
        "wait_hours": hours,
        "wait_minutes": minutes,
        "wait_sec": sec,
    }


def portal_workflow_step_initial_from_instance(step: WorkflowStep) -> dict:
    tk = ""
    if step.step_type == WorkflowStepType.SEND_TEMPLATE:
        tk = step.template.key if step.template else (step.template_key or "")
    init = {
        "order": step.order,
        "step_type": step.step_type,
        "template_key": tk,
    }
    init.update(wait_seconds_to_components(step.wait_seconds))
    return init


class PortalWorkflowEnrollForm(WorkflowEnrollForm):
    """Workflow test enrollment with pre-filled template_context and validation of required keys."""

    def __init__(self, *args, workflow=None, **kwargs):
        self.workflow = workflow
        super().__init__(*args, **kwargs)
        self.fields["metadata"].label = "Metadata (JSON)"
        self.fields["metadata"].help_text = (
            "Must include a template_context object whose keys cover all variables used in "
            "this workflow’s send steps. Sample values are pre-filled — replace with real data for a realistic test."
        )
        if workflow is not None and not self.is_bound:
            default_md = build_default_enrollment_metadata(workflow)
            self.fields["metadata"].initial = json.dumps(default_md, indent=2)
            nvars = len((default_md.get("template_context") or {}))
            self.fields["metadata"].widget.attrs["rows"] = max(10, min(28, 8 + nvars * 2))

    def clean(self):
        cleaned_data = super().clean()
        wf = self.workflow
        if wf is None:
            return cleaned_data
        if self.errors.get("metadata"):
            return cleaned_data
        required = required_template_context_keys(wf)
        if not required:
            return cleaned_data
        meta = cleaned_data.get("metadata") or {}
        tc = meta.get("template_context") if isinstance(meta, dict) else None
        if tc is None:
            self.add_error(
                "metadata",
                'Include a "template_context" object with values for each variable required by this workflow.',
            )
            return cleaned_data
        if not isinstance(tc, dict):
            self.add_error("metadata", '"template_context" must be a JSON object.')
            return cleaned_data
        missing = [k for k in required if k not in tc]
        if missing:
            self.add_error(
                "metadata",
                "template_context is missing keys required by this workflow’s templates: "
                + ", ".join(missing),
            )
            return cleaned_data
        empty = [
            k
            for k in required
            if tc[k] is None or (isinstance(tc[k], str) and not str(tc[k]).strip())
        ]
        if empty:
            self.add_error(
                "metadata",
                "template_context values must not be empty for: " + ", ".join(empty),
            )
        return cleaned_data


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


class PortalSuppressionFilterForm(forms.Form):
    """Filter suppressions visible in the customer portal (own tenants + global)."""

    email = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": _inp, "placeholder": "Email contains…", "autocomplete": "off"}
        ),
    )
    reason = forms.ChoiceField(
        required=False,
        choices=[("", "Any reason")] + list(SuppressionReason.choices),
        widget=forms.Select(attrs={"class": _inp}),
    )
    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.none(),
        required=False,
        empty_label="Any connected app",
        label="Connected app",
        widget=forms.Select(attrs={"class": _inp}),
    )
    scope = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Your rows + global"),
            ("mine", "Your rows only"),
            ("global", "Global only"),
        ],
        widget=forms.Select(attrs={"class": _inp}),
    )
    affects = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Any channel"),
            ("marketing", "Affects marketing"),
            ("transactional", "Affects transactional"),
        ],
        widget=forms.Select(attrs={"class": _inp}),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": _inp}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": _inp}),
    )

    def __init__(self, *args, account: Account, **kwargs):
        super().__init__(*args, **kwargs)
        self._account = account
        self.fields["tenant"].queryset = Tenant.objects.filter(
            account=account
        ).order_by("name")


class PortalManualSuppressionForm(forms.Form):
    """Add a manual suppression in the customer portal, scoped to one of the account's tenants."""

    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"class": _inp, "placeholder": "recipient@example.com"}
        ),
    )
    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.none(),
        empty_label=None,
        label="Connected app",
        widget=forms.Select(attrs={"class": _inp}),
    )
    applies_to_marketing = forms.BooleanField(
        required=False,
        initial=True,
        label="Block marketing / lifecycle email",
        widget=forms.CheckboxInput(attrs={"class": _chk}),
    )
    applies_to_transactional = forms.BooleanField(
        required=False,
        initial=False,
        label="Block transactional / system email",
        widget=forms.CheckboxInput(attrs={"class": _chk}),
    )
    note = forms.CharField(
        required=False,
        label="Note (saved in metadata)",
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "class": _inp,
                "placeholder": "Why are you blocking this address? (optional)",
            }
        ),
    )

    def __init__(self, *args, account: Account, single_tenant: Tenant | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._account = account
        qs = Tenant.objects.filter(account=account).order_by("name")
        self.fields["tenant"].queryset = qs
        if single_tenant is not None:
            self.fields["tenant"].initial = single_tenant.pk
            self.fields["tenant"].queryset = qs.filter(pk=single_tenant.pk)

    def clean_tenant(self):
        t = self.cleaned_data.get("tenant")
        if t is None or t.account_id != self._account.id:
            raise forms.ValidationError("Choose one of your connected apps.")
        return t

    def clean(self):
        data = super().clean()
        m = bool(data.get("applies_to_marketing"))
        t = bool(data.get("applies_to_transactional"))
        if not m and not t:
            raise forms.ValidationError(
                "Select at least one of marketing or transactional."
            )
        return data


class PortalWebhookEventFilterForm(forms.Form):
    """Filter the portal webhook / delivery event feed."""

    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.none(),
        required=False,
        empty_label="Any connected app",
        label="Connected app",
        widget=forms.Select(attrs={"class": _inp}),
    )
    event_type = forms.ChoiceField(
        required=False,
        choices=[("", "Any event")] + list(MessageEventType.choices),
        widget=forms.Select(attrs={"class": _inp}),
    )
    to_email = forms.CharField(
        required=False,
        label="Recipient contains",
        widget=forms.TextInput(
            attrs={"class": _inp, "placeholder": "user@example.com", "autocomplete": "off"}
        ),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": _inp}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": _inp}),
    )

    def __init__(self, *args, account: Account, **kwargs):
        super().__init__(*args, **kwargs)
        self._account = account
        self.fields["tenant"].queryset = Tenant.objects.filter(
            account=account
        ).order_by("name")


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
