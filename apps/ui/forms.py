"""Operator UI forms — validation aligned with API serializers where applicable."""

from __future__ import annotations

import json
from typing import Any

from django import forms

from apps.email_templates.models import TemplateCategory
from apps.messages.models import MessageType, OutboundStatus
from apps.tenants.models import SenderProfile, Tenant
from apps.ui.tenant_validators import from_email_allowed_for_tenant
from apps.workflows.models import WorkflowStepType


class JsonObjectField(forms.CharField):
    """JSON object as textarea; empty → {}."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "widget",
            forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "w-full rounded-md border border-surface-600 bg-surface-800 px-3 py-2 font-mono text-xs text-white",
                }
            ),
        )
        kwargs.setdefault("required", False)
        super().__init__(*args, **kwargs)

    def clean(self, value):
        raw = super().clean(value)
        raw = (raw or "").strip()
        if not raw:
            return {}
        try:
            val = json.loads(raw)
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f"Invalid JSON: {e}") from e
        if not isinstance(val, dict):
            raise forms.ValidationError("JSON must be an object.")
        return val


_select = "w-full rounded-md border border-surface-600 bg-surface-800 px-2 py-1.5 text-sm text-white"


class MessageFilterForm(forms.Form):
    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.all(),
        required=False,
        empty_label="Any tenant",
        widget=forms.Select(attrs={"class": _select}),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", "Any status")] + list(OutboundStatus.choices),
        widget=forms.Select(attrs={"class": _select}),
    )
    source_app = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": _select}))
    template_key = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": _select}))
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"class": _select}))
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date", "class": _select}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date", "class": _select}))


_inp = "w-full rounded-md border border-surface-600 bg-surface-800 px-3 py-2 text-sm text-white"
_chk = "h-4 w-4 rounded border-surface-600 text-accent"


def _sender_profile_label(obj: SenderProfile) -> str:
    return f"{obj.name} — {obj.from_email}"


class TenantForm(forms.ModelForm):
    """Create or edit a tenant (pass instance= for edit)."""

    class Meta:
        model = Tenant
        fields = [
            "name",
            "slug",
            "status",
            "default_sender_name",
            "default_sender_email",
            "reply_to",
            "sending_domain",
            "timezone",
            "rate_limit_per_minute",
            "webhook_secret",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": _inp}),
            "slug": forms.TextInput(attrs={"class": _inp}),
            "status": forms.Select(attrs={"class": _inp}),
            "default_sender_name": forms.TextInput(attrs={"class": _inp}),
            "default_sender_email": forms.EmailInput(attrs={"class": _inp}),
            "reply_to": forms.EmailInput(attrs={"class": _inp}),
            "sending_domain": forms.TextInput(attrs={"class": _inp}),
            "timezone": forms.TextInput(attrs={"class": _inp}),
            "rate_limit_per_minute": forms.NumberInput(attrs={"class": _inp, "min": 1}),
            "webhook_secret": forms.TextInput(attrs={"class": _inp}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "webhook_secret" in self.fields:
            self.fields["webhook_secret"].required = False
        if "default_sender_email" in self.fields:
            self.fields["default_sender_email"].required = False
        if "reply_to" in self.fields:
            self.fields["reply_to"].required = False
        if "sending_domain" in self.fields:
            self.fields["sending_domain"].required = False
        if "timezone" in self.fields:
            self.fields["timezone"].initial = self.fields["timezone"].initial or "UTC"

    def clean_slug(self):
        slug = (self.cleaned_data.get("slug") or "").strip()
        if not slug:
            raise forms.ValidationError("Slug is required.")
        qs = Tenant.objects.filter(slug__iexact=slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A tenant with this slug already exists.")
        return slug.lower()

    def clean_sending_domain(self):
        raw = self.cleaned_data.get("sending_domain") or ""
        return raw.strip().lower() if raw else ""

    def clean_timezone(self):
        tz = (self.cleaned_data.get("timezone") or "").strip()
        return tz or "UTC"


class SenderProfileForm(forms.ModelForm):
    class Meta:
        model = SenderProfile
        fields = ["name", "category", "from_name", "from_email", "reply_to", "is_default", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": _inp}),
            "category": forms.Select(attrs={"class": _inp}),
            "from_name": forms.TextInput(attrs={"class": _inp}),
            "from_email": forms.EmailInput(attrs={"class": _inp}),
            "reply_to": forms.EmailInput(attrs={"class": _inp}),
            "is_default": forms.CheckboxInput(attrs={"class": _chk}),
            "is_active": forms.CheckboxInput(attrs={"class": _chk}),
        }

    def __init__(self, *args, tenant: Tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self._tenant = tenant
        self.fields["reply_to"].required = False

    def clean_from_email(self):
        email = self.cleaned_data["from_email"].strip()
        sd = (self._tenant.sending_domain or "").strip()
        if sd and not from_email_allowed_for_tenant(email, sd):
            raise forms.ValidationError(
                f"From address must be on the tenant sending domain ({sd}).",
            )
        return email

    def save(self, commit: bool = True):
        self.instance.tenant = self._tenant
        return super().save(commit=commit)


class SendRawForm(forms.Form):
    source_app = forms.CharField(initial="operator_ui", widget=forms.TextInput(attrs={"class": _inp}))
    message_type = forms.ChoiceField(
        choices=MessageType.choices,
        initial=MessageType.TRANSACTIONAL,
        widget=forms.Select(attrs={"class": _inp}),
    )
    to_email = forms.EmailField(widget=forms.EmailInput(attrs={"class": _inp}))
    to_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": _inp}))
    subject = forms.CharField(widget=forms.TextInput(attrs={"class": _inp}))
    html_body = forms.CharField(widget=forms.Textarea(attrs={"rows": 12, "class": _inp + " font-mono text-xs"}))
    text_body = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 6, "class": _inp + " font-mono text-xs"})
    )
    metadata = JsonObjectField()
    idempotency_key = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": _inp}))
    sender_profile = forms.ModelChoiceField(
        queryset=SenderProfile.objects.none(),
        required=False,
        empty_label="Use tenant default sender",
        label="Sender profile",
        widget=forms.Select(attrs={"class": _inp}),
    )

    def __init__(self, *args, tenant: Tenant | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._tenant = tenant
        sp = self.fields["sender_profile"]
        sp.label_from_instance = _sender_profile_label
        if tenant is not None:
            sp.queryset = SenderProfile.objects.filter(tenant=tenant, is_active=True).order_by(
                "category", "name"
            )
        else:
            sp.queryset = SenderProfile.objects.none()

    def clean_sender_profile(self):
        sp = self.cleaned_data.get("sender_profile")
        if sp is not None and self._tenant is not None and sp.tenant_id != self._tenant.id:
            raise forms.ValidationError("That sender profile does not belong to the active tenant.")
        return sp


class SendTemplateForm(forms.Form):
    template_key = forms.SlugField(widget=forms.TextInput(attrs={"class": _inp}))
    source_app = forms.CharField(initial="operator_ui", widget=forms.TextInput(attrs={"class": _inp}))
    message_type = forms.ChoiceField(
        choices=MessageType.choices,
        initial=MessageType.TRANSACTIONAL,
        widget=forms.Select(attrs={"class": _inp}),
    )
    to_email = forms.EmailField(widget=forms.EmailInput(attrs={"class": _inp}))
    to_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": _inp}))
    context = JsonObjectField()
    metadata = JsonObjectField()
    tags = JsonObjectField()
    scheduled_for = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": _inp}),
    )
    idempotency_key = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": _inp}))
    sender_profile = forms.ModelChoiceField(
        queryset=SenderProfile.objects.none(),
        required=False,
        empty_label="Use tenant default sender",
        label="Sender profile",
        widget=forms.Select(attrs={"class": _inp}),
    )

    def __init__(self, *args, tenant: Tenant | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._tenant = tenant
        sp = self.fields["sender_profile"]
        sp.label_from_instance = _sender_profile_label
        if tenant is not None:
            sp.queryset = SenderProfile.objects.filter(tenant=tenant, is_active=True).order_by(
                "category", "name"
            )
        else:
            sp.queryset = SenderProfile.objects.none()

    def clean_sender_profile(self):
        sp = self.cleaned_data.get("sender_profile")
        if sp is not None and self._tenant is not None and sp.tenant_id != self._tenant.id:
            raise forms.ValidationError("That sender profile does not belong to the active tenant.")
        return sp


def send_forms_for_tenant(tenant: Tenant | None) -> tuple[SendRawForm, SendTemplateForm]:
    """Pair of send forms scoped to tenant (or empty sender profile queryset)."""
    return SendRawForm(tenant=tenant), SendTemplateForm(tenant=tenant)


class TemplatePreviewForm(forms.Form):
    context = JsonObjectField()


class TemplateApproveForm(forms.Form):
    note = forms.CharField(required=False, widget=forms.HiddenInput(), initial="")


class TemplateReviseForm(forms.Form):
    instructions = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4, "class": "w-full rounded-md border border-surface-600 bg-surface-800 px-3 py-2 text-sm text-white"})
    )


class TemplateStudioBriefForm(forms.Form):
    """Maps to TemplateGenerationBriefSchema (subset + extra for template metadata)."""

    template_key = forms.SlugField()
    name = forms.CharField()
    category = forms.ChoiceField(choices=TemplateCategory.choices)
    template_purpose = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    audience = forms.CharField(required=False)
    tone = forms.CharField(initial="professional", required=False)
    desired_cta = forms.CharField(required=False)
    mandatory_facts = forms.CharField(
        required=False,
        help_text="One per line",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    prohibited_claims = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    required_variables = forms.CharField(
        required=False,
        help_text="Comma-separated variable names",
    )
    legal_compliance_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    brand_voice_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    max_length_hint = forms.ChoiceField(
        choices=[("short", "short"), ("medium", "medium"), ("long", "long")],
        initial="medium",
    )
    include_images = forms.BooleanField(required=False, initial=False)
    is_marketing = forms.BooleanField(required=False, initial=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name in ("include_images", "is_marketing"):
                continue
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "h-4 w-4 rounded border-surface-600")
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", _inp + " min-h-[72px]")
            else:
                field.widget.attrs.setdefault("class", _inp)

    def brief_dict(self) -> dict[str, Any]:
        facts = [x.strip() for x in self.cleaned_data.get("mandatory_facts", "").splitlines() if x.strip()]
        prohibited_raw = self.cleaned_data.get("prohibited_claims") or ""
        prohibited = [
            x.strip()
            for x in prohibited_raw.replace("\n", ",").split(",")
            if x.strip()
        ]
        req_vars = [
            x.strip()
            for x in self.cleaned_data.get("required_variables", "").split(",")
            if x.strip()
        ]
        return {
            "template_purpose": self.cleaned_data["template_purpose"],
            "audience": self.cleaned_data.get("audience") or "",
            "email_category": self.cleaned_data["category"],
            "tone": self.cleaned_data.get("tone") or "professional",
            "desired_cta": self.cleaned_data.get("desired_cta") or "",
            "mandatory_facts": facts,
            "prohibited_claims": prohibited,
            "required_variables": req_vars,
            "legal_compliance_notes": self.cleaned_data.get("legal_compliance_notes") or "",
            "brand_voice_notes": self.cleaned_data.get("brand_voice_notes") or "",
            "max_length_hint": self.cleaned_data.get("max_length_hint") or "medium",
            "html_layout_style": "single_column",
            "include_images": self.cleaned_data.get("include_images", False),
            "is_marketing": self.cleaned_data.get("is_marketing", False),
        }


class WorkflowCreateForm(forms.Form):
    name = forms.CharField(widget=forms.TextInput(attrs={"class": _inp}))
    slug = forms.SlugField(widget=forms.TextInput(attrs={"class": _inp}))


class WorkflowAddStepForm(forms.Form):
    order = forms.IntegerField(min_value=0, widget=forms.NumberInput(attrs={"class": _inp}))
    step_type = forms.ChoiceField(
        choices=WorkflowStepType.choices,
        widget=forms.Select(attrs={"class": _inp}),
    )
    template_key = forms.SlugField(required=False, widget=forms.TextInput(attrs={"class": _inp}))
    wait_seconds = forms.IntegerField(required=False, min_value=0, widget=forms.NumberInput(attrs={"class": _inp}))


class WorkflowEnrollForm(forms.Form):
    recipient_email = forms.EmailField(widget=forms.EmailInput(attrs={"class": _inp}))
    recipient_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": _inp}))
    external_user_id = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": _inp}))
    metadata = JsonObjectField()


class ApiKeyCreateForm(forms.Form):
    name = forms.CharField(initial="operator", widget=forms.TextInput(attrs={"class": _inp}))


class NewEmailTemplateForm(forms.Form):
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