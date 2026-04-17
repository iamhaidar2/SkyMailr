"""
Prepopulated email templates for customer tenants (connected apps).

Seeded once per new tenant; customers can edit copy and styling in the portal.
Uses Jinja2 with |default() so optional variables do not break StrictUndefined rendering.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.email_templates.models import (
    ApprovalStatus,
    CreatedByType,
    EmailTemplate,
    EmailTemplateVersion,
    TemplateCategory,
    TemplateStatus,
    TemplateVariable,
    VersionSourceType,
)
from apps.tenants.models import Tenant

STARTER_TEMPLATE_KEYS: tuple[str, ...] = (
    "email_verification",
    "welcome_new_user",
    "account_deletion_confirmation",
    "password_reset",
    "password_change",
    "subscription_upgrade",
    "payment_reminder",
    "payment_received",
)


def _shell(inner: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title></title>
</head>
<body style="margin:0;padding:0;background:#f4f4f5;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f4f5;">
<tr><td align="center" style="padding:28px 16px;">
<table role="presentation" width="600" cellspacing="0" cellpadding="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:10px;border:1px solid #e4e4e7;overflow:hidden;">
{inner}
</table>
</td></tr>
</table>
</body>
</html>"""


def _cta_row(href: str, label: str) -> str:
    return f"""<tr><td style="padding:8px 32px 28px 32px;">
<a href="{href}" style="display:inline-block;background:#18181b;color:#fafafa;text-decoration:none;padding:12px 22px;border-radius:6px;font-size:15px;font-weight:600;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;">{label}</a>
</td></tr>"""


def _footer_row(product: str = "{{ product_name | default('Your app') }}") -> str:
    return f"""<tr><td style="padding:20px 32px 28px 32px;border-top:1px solid #f4f4f5;font-size:12px;line-height:1.5;color:#71717a;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;">
This message was sent by {product}. If you did not expect this email, you can ignore it or contact support.
</td></tr>"""


# --- Template definitions: subject, preview, html, text, variables ---


def _defs() -> list[dict[str, Any]]:
    p = "{{ product_name | default('Your app') }}"
    u = "{{ user_name | default('there') }}"
    return [
        {
            "key": "email_verification",
            "name": "Email verification",
            "category": TemplateCategory.TRANSACTIONAL,
            "description": "Sent when a user must confirm their email address.",
            "subject_template": f"Confirm your email for {p}",
            "preview_text_template": f"Verify your email to continue using {p}.",
            "html_template": _shell(
                f"""<tr><td style="padding:32px 32px 8px 32px;font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:1.3;color:#18181b;">
Verify your email
</td></tr>
<tr><td style="padding:8px 32px 16px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.6;color:#3f3f46;">
Hi {u},<br><br>
Thanks for signing up. Please confirm your email address so we know this is really you. This link expires in {{{{ expiry_time | default('24 hours') }}}}.
</td></tr>
{_cta_row('{{ action_url }}', 'Confirm email')}
<tr><td style="padding:0 32px 24px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.6;color:#71717a;">
If the button does not work, paste this URL into your browser:<br>
<span style="word-break:break-all;color:#3f3f46;">{{{{ action_url }}}}</span>
</td></tr>
{_footer_row()}"""
            ),
            "text_template": f"""Hi {u},

Thanks for signing up for {p}. Confirm your email by opening this link (expires in {{{{ expiry_time | default('24 hours') }}}}):

{{{{ action_url }}}}

If you did not create an account, you can ignore this message.

— {p}
""",
            "variables": [
                {
                    "name": "product_name",
                    "description": "Your product or app name (shown in subject and footer).",
                    "is_required": True,
                },
                {
                    "name": "action_url",
                    "description": "One-time verification URL.",
                    "is_required": True,
                },
                {
                    "name": "user_name",
                    "description": "Recipient display name.",
                    "is_required": False,
                },
                {
                    "name": "expiry_time",
                    "description": "Human-readable validity window, e.g. '24 hours'.",
                    "is_required": False,
                },
            ],
        },
        {
            "key": "welcome_new_user",
            "name": "Welcome new user",
            "category": TemplateCategory.LIFECYCLE,
            "description": "Onboarding welcome after signup or first login.",
            "subject_template": f"Welcome to {p}",
            "preview_text_template": f"You're in — here's how to get started with {p}.",
            "html_template": _shell(
                f"""<tr><td style="padding:32px 32px 8px 32px;font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:1.3;color:#18181b;">
Welcome aboard
</td></tr>
<tr><td style="padding:8px 32px 16px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.6;color:#3f3f46;">
Hi {u},<br><br>
We're glad you're here. Your account is ready. Use the button below to open your dashboard and explore what {p} can do for you.
</td></tr>
{_cta_row('{{ action_url | default("#") }}', 'Go to dashboard')}
<tr><td style="padding:0 32px 24px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.6;color:#71717a;">
Tip: complete your profile and notification settings so we only email you what matters.
</td></tr>
{_footer_row()}"""
            ),
            "text_template": f"""Hi {u},

Welcome to {p}. Your account is ready.

Open your dashboard:
{{{{ action_url | default("#") }}}}

We're here if you need help.

— {p}
""",
            "variables": [
                {
                    "name": "product_name",
                    "description": "Your product or app name.",
                    "is_required": True,
                },
                {
                    "name": "action_url",
                    "description": "Link to dashboard or getting-started page.",
                    "is_required": False,
                },
                {
                    "name": "user_name",
                    "description": "Recipient display name.",
                    "is_required": False,
                },
            ],
        },
        {
            "key": "account_deletion_confirmation",
            "name": "Account deletion confirmation",
            "category": TemplateCategory.TRANSACTIONAL,
            "description": "Confirms a scheduled account deletion or provides a cancel link.",
            "subject_template": f"Your {p} account deletion",
            "preview_text_template": "Confirm the details of your account deletion request.",
            "html_template": _shell(
                f"""<tr><td style="padding:32px 32px 8px 32px;font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:1.3;color:#18181b;">
Account deletion
</td></tr>
<tr><td style="padding:8px 32px 16px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.6;color:#3f3f46;">
Hi {u},<br><br>
We received a request to delete your <strong>{{{{ product_name | default('your app') }}}}</strong> account. Scheduled deletion: <strong>{{{{ deletion_scheduled_date | default('soon') }}}}</strong>.<br><br>
If you changed your mind, you can cancel this request using the button below while your account is still active.
</td></tr>
{_cta_row('{{ action_url }}', 'Cancel deletion')}
<tr><td style="padding:0 32px 24px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.6;color:#71717a;">
If you did not request deletion, secure your account immediately and contact support.
</td></tr>
{_footer_row()}"""
            ),
            "text_template": f"""Hi {u},

We received a request to delete your {p} account.

Scheduled deletion: {{{{ deletion_scheduled_date | default('soon') }}}}

Cancel deletion (while your account is active):
{{{{ action_url }}}}

If you did not request this, contact support right away.

— {p}
""",
            "variables": [
                {
                    "name": "product_name",
                    "description": "Your product or app name.",
                    "is_required": True,
                },
                {
                    "name": "action_url",
                    "description": "URL to cancel deletion or manage account.",
                    "is_required": True,
                },
                {
                    "name": "user_name",
                    "description": "Recipient display name.",
                    "is_required": False,
                },
                {
                    "name": "deletion_scheduled_date",
                    "description": "When the account will be removed, e.g. 'April 20, 2026'.",
                    "is_required": False,
                },
            ],
        },
        {
            "key": "password_reset",
            "name": "Password reset",
            "category": TemplateCategory.TRANSACTIONAL,
            "description": "Password reset link with expiry notice.",
            "subject_template": f"Reset your {p} password",
            "preview_text_template": "Use the secure link below to choose a new password.",
            "html_template": _shell(
                f"""<tr><td style="padding:32px 32px 8px 32px;font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:1.3;color:#18181b;">
Reset your password
</td></tr>
<tr><td style="padding:8px 32px 16px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.6;color:#3f3f46;">
Hi {u},<br><br>
We got a request to reset your password. The link below expires in {{{{ expiry_time | default('1 hour') }}}}. If you did not ask for this, you can ignore this email — your password will stay the same.
</td></tr>
{_cta_row('{{ action_url }}', 'Choose a new password')}
<tr><td style="padding:0 32px 24px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.6;color:#71717a;">
Or copy and paste:<br><span style="word-break:break-all;color:#3f3f46;">{{{{ action_url }}}}</span>
</td></tr>
{_footer_row()}"""
            ),
            "text_template": f"""Hi {u},

Reset your {p} password using this link (expires in {{{{ expiry_time | default('1 hour') }}}}):

{{{{ action_url }}}}

If you did not request a reset, ignore this message.

— {p}
""",
            "variables": [
                {
                    "name": "product_name",
                    "description": "Your product or app name.",
                    "is_required": True,
                },
                {
                    "name": "action_url",
                    "description": "Password reset URL.",
                    "is_required": True,
                },
                {
                    "name": "user_name",
                    "description": "Recipient display name.",
                    "is_required": False,
                },
                {
                    "name": "expiry_time",
                    "description": "Human-readable link lifetime, e.g. '1 hour'.",
                    "is_required": False,
                },
            ],
        },
        {
            "key": "password_change",
            "name": "Password changed",
            "category": TemplateCategory.TRANSACTIONAL,
            "description": "Security notice after the password was changed.",
            "subject_template": f"Your {p} password was changed",
            "preview_text_template": "This is a confirmation that your password was updated.",
            "html_template": _shell(
                f"""<tr><td style="padding:32px 32px 8px 32px;font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:1.3;color:#18181b;">
Password updated
</td></tr>
<tr><td style="padding:8px 32px 16px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.6;color:#3f3f46;">
Hi {u},<br><br>
Your password was changed on <strong>{{{{ changed_at | default('recently') }}}}</strong>. If you made this change, no further action is needed.
</td></tr>
{_cta_row('{{ action_url | default("#") }}', 'Review security settings')}
<tr><td style="padding:0 32px 24px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.6;color:#71717a;">
If you did not change your password, your account may be compromised. Reset your password immediately and contact support.
</td></tr>
{_footer_row()}"""
            ),
            "text_template": f"""Hi {u},

Your {p} password was changed on {{{{ changed_at | default('recently') }}}}.

Review security settings:
{{{{ action_url | default("#") }}}}

If this was not you, reset your password and contact support immediately.

— {p}
""",
            "variables": [
                {
                    "name": "product_name",
                    "description": "Your product or app name.",
                    "is_required": True,
                },
                {
                    "name": "user_name",
                    "description": "Recipient display name.",
                    "is_required": False,
                },
                {
                    "name": "changed_at",
                    "description": "When the password changed, e.g. 'Apr 14, 2026 at 3:04 PM UTC'.",
                    "is_required": False,
                },
                {
                    "name": "action_url",
                    "description": "Link to security settings or sessions page.",
                    "is_required": False,
                },
            ],
        },
        {
            "key": "subscription_upgrade",
            "name": "Subscription upgrade",
            "category": TemplateCategory.LIFECYCLE,
            "description": "Confirms a plan upgrade or new subscription tier.",
            "subject_template": f"You're on {{{{ plan_name | default('your new plan') }}}} — {p}",
            "preview_text_template": f"Your subscription for {p} has been updated.",
            "html_template": _shell(
                f"""<tr><td style="padding:32px 32px 8px 32px;font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:1.3;color:#18181b;">
Subscription updated
</td></tr>
<tr><td style="padding:8px 32px 16px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.6;color:#3f3f46;">
Hi {u},<br><br>
Thank you for upgrading. Your plan is now <strong>{{{{ plan_name | default('your new plan') }}}}</strong>. """
                + """{% if effective_date | default('') %}Effective {{ effective_date }}. {% endif %}"""
                + """You now have access to the features included in this tier.
</td></tr>
"""
                + _cta_row('{{ action_url | default("#") }}', 'Manage subscription')
                + """<tr><td style="padding:0 32px 24px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.6;color:#71717a;">
Questions about billing? Reply to this email or visit your billing portal.
</td></tr>
"""
                + _footer_row()
            ),
            "text_template": f"""Hi {u},

Your {p} subscription was updated.

Plan: {{{{ plan_name | default('your new plan') }}}}
"""
                + """{% if effective_date | default('') %}Effective: {{ effective_date }}
{% endif %}"""
                + f"""Manage subscription:
{{{{ action_url | default("#") }}}}

Thank you for your business.

— {p}
""",
            "variables": [
                {
                    "name": "product_name",
                    "description": "Your product or app name.",
                    "is_required": True,
                },
                {
                    "name": "plan_name",
                    "description": "New plan or tier name.",
                    "is_required": False,
                },
                {
                    "name": "user_name",
                    "description": "Recipient display name.",
                    "is_required": False,
                },
                {
                    "name": "effective_date",
                    "description": "Optional sentence fragment, e.g. ', effective April 14, 2026'.",
                    "is_required": False,
                },
                {
                    "name": "action_url",
                    "description": "Billing or subscription management URL.",
                    "is_required": False,
                },
            ],
        },
        {
            "key": "payment_reminder",
            "name": "Payment reminder",
            "category": TemplateCategory.TRANSACTIONAL,
            "description": "Reminder for an upcoming or overdue invoice.",
            "subject_template": f"Payment reminder: {{{{ payment_amount }}}} {{{{ currency }}}} due {{{{ due_date }}}}",
            "preview_text_template": f"Complete your payment to keep your {p} subscription active.",
            "html_template": _shell(
                f"""<tr><td style="padding:32px 32px 8px 32px;font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:1.3;color:#18181b;">
Payment due
</td></tr>
<tr><td style="padding:8px 32px 16px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.6;color:#3f3f46;">
Hi {u},<br><br>
This is a friendly reminder that a payment of <strong>{{{{ payment_amount }}}} {{{{ currency }}}}</strong> is due by <strong>{{{{ due_date }}}}</strong>"""
                + """{% if invoice_number | default('') %} (Invoice {{ invoice_number }}){% endif %}"""
                + """.
</td></tr>
"""
                + _cta_row('{{ action_url }}', 'Pay now')
                + """<tr><td style="padding:0 32px 24px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.6;color:#71717a;">
If you already paid, thank you — it may take a short time to reflect.
</td></tr>
"""
                + _footer_row()
            ),
            "text_template": f"""Hi {u},

Payment reminder for {p}:

Amount: {{{{ payment_amount }}}} {{{{ currency }}}}
Due: {{{{ due_date }}}}
"""
                + """{% if invoice_number | default('') %}(Invoice {{ invoice_number }})
{% endif %}"""
                + f"""Pay now:
{{{{ action_url }}}}

— {p}
""",
            "variables": [
                {
                    "name": "product_name",
                    "description": "Your product or app name.",
                    "is_required": True,
                },
                {
                    "name": "payment_amount",
                    "description": "Amount as a string, e.g. '29.00'.",
                    "is_required": True,
                },
                {
                    "name": "currency",
                    "description": "Currency code, e.g. USD.",
                    "is_required": True,
                },
                {
                    "name": "due_date",
                    "description": "Due date in plain language.",
                    "is_required": True,
                },
                {
                    "name": "action_url",
                    "description": "Payment or invoice URL.",
                    "is_required": True,
                },
                {
                    "name": "user_name",
                    "description": "Recipient display name.",
                    "is_required": False,
                },
                {
                    "name": "invoice_number",
                    "description": "Optional invoice or reference number.",
                    "is_required": False,
                },
            ],
        },
        {
            "key": "payment_received",
            "name": "Payment received",
            "category": TemplateCategory.TRANSACTIONAL,
            "description": "Receipt confirmation after a successful payment.",
            "subject_template": f"Receipt: {{{{ payment_amount }}}} {{{{ currency }}}} received — {p}",
            "preview_text_template": "Thanks — we've received your payment.",
            "html_template": _shell(
                f"""<tr><td style="padding:32px 32px 8px 32px;font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:1.3;color:#18181b;">
Payment received
</td></tr>
<tr><td style="padding:8px 32px 16px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.6;color:#3f3f46;">
Hi {u},<br><br>
We've received your payment of <strong>{{{{ payment_amount }}}} {{{{ currency }}}}</strong> on <strong>{{{{ payment_date }}}}</strong>"""
                + """{% if invoice_number | default('') %} (Invoice {{ invoice_number }}){% endif %}"""
                + """. Thank you.
</td></tr>
"""
                + _cta_row('{{ action_url | default("#") }}', 'View receipt')
                + """<tr><td style="padding:0 32px 24px 32px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.6;color:#71717a;">
Keep this email for your records. For billing questions, contact support.
</td></tr>
"""
                + _footer_row()
            ),
            "text_template": f"""Hi {u},

We received your payment for {p}.

Amount: {{{{ payment_amount }}}} {{{{ currency }}}}
Date: {{{{ payment_date }}}}
"""
                + """{% if invoice_number | default('') %}(Invoice {{ invoice_number }})
{% endif %}"""
                + f"""View details:
{{{{ action_url | default("#") }}}}

Thank you.

— {p}
""",
            "variables": [
                {
                    "name": "product_name",
                    "description": "Your product or app name.",
                    "is_required": True,
                },
                {
                    "name": "payment_amount",
                    "description": "Amount as a string.",
                    "is_required": True,
                },
                {
                    "name": "currency",
                    "description": "Currency code, e.g. USD.",
                    "is_required": True,
                },
                {
                    "name": "payment_date",
                    "description": "Payment date in plain language.",
                    "is_required": True,
                },
                {
                    "name": "user_name",
                    "description": "Recipient display name.",
                    "is_required": False,
                },
                {
                    "name": "invoice_number",
                    "description": "Optional invoice or reference number.",
                    "is_required": False,
                },
                {
                    "name": "action_url",
                    "description": "Link to receipt or billing history.",
                    "is_required": False,
                },
            ],
        },
    ]


@transaction.atomic
def seed_customer_starter_templates(tenant: Tenant) -> int:
    """
    Create the customer starter template set for ``tenant`` if not already present.

    Idempotent: skips templates that already have a current approved version.
    Returns the number of templates for which a new approved version was created.
    """
    seeded = 0
    for spec in _defs():
        tpl, _ = EmailTemplate.objects.get_or_create(
            tenant=tenant,
            key=spec["key"],
            defaults={
                "name": spec["name"],
                "category": spec["category"],
                "status": TemplateStatus.DRAFT,
                "description": spec["description"],
                "tags": ["starter"],
            },
        )
        if tpl.versions.filter(is_current_approved=True).exists():
            continue
        EmailTemplateVersion.objects.create(
            template=tpl,
            version_number=1,
            created_by_type=CreatedByType.SYSTEM,
            source_type=VersionSourceType.SEEDED,
            subject_template=spec["subject_template"],
            preview_text_template=spec["preview_text_template"],
            html_template=spec["html_template"],
            text_template=spec["text_template"],
            approval_status=ApprovalStatus.APPROVED,
            is_current_approved=True,
        )
        for v in spec["variables"]:
            TemplateVariable.objects.update_or_create(
                template=tpl,
                name=v["name"],
                defaults={
                    "description": v["description"],
                    "is_required": v["is_required"],
                },
            )
        tpl.status = TemplateStatus.ACTIVE
        tpl.save(update_fields=["status"])
        seeded += 1
    return seeded
