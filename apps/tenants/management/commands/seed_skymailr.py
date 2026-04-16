from django.core.management.base import BaseCommand
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
from apps.tenants.models import Tenant, TenantStatus


TENANTS = [
    {
        "name": "BrainList",
        "slug": "brainlist",
        "llm_defaults": {
            "default_model": "gpt-4o-mini",
            "temperature": 0.35,
            "brand_voice_notes": "Warm, intellectually curious, concise. Audio-learning product.",
        },
    },
    {
        "name": "TOMEO",
        "slug": "tomeo",
        "llm_defaults": {
            "default_model": "gpt-4o-mini",
            "temperature": 0.35,
            "brand_voice_notes": "Clear, confident, productivity-focused writing assistant.",
        },
    },
    {
        "name": "ProjMan",
        "slug": "projman",
        "llm_defaults": {
            "default_model": "gpt-4o-mini",
            "temperature": 0.3,
            "brand_voice_notes": "Direct, collaborative, project delivery oriented.",
        },
    },
]

COMMON_KEYS = [
    ("email_verification", "Email verification", TemplateCategory.TRANSACTIONAL),
    ("password_reset", "Password reset", TemplateCategory.TRANSACTIONAL),
    ("account_deletion_confirmation", "Account deletion", TemplateCategory.TRANSACTIONAL),
    ("collaborator_invite", "Collaborator invite", TemplateCategory.TRANSACTIONAL),
]

BRAINLIST_KEYS = [
    ("welcome_new_user", "Welcome", TemplateCategory.LIFECYCLE),
    ("day_2_listen_first_lecture", "Day 2 nudge", TemplateCategory.LIFECYCLE),
    ("day_5_quiz_nudge", "Day 5 quiz", TemplateCategory.LIFECYCLE),
    ("contest_invite", "Contest invite", TemplateCategory.MARKETING),
]

TOMEO_KEYS = [
    ("welcome_new_user", "Welcome", TemplateCategory.LIFECYCLE),
    ("generate_first_outline_nudge", "First outline nudge", TemplateCategory.LIFECYCLE),
    ("document_ready_notification", "Document ready", TemplateCategory.TRANSACTIONAL),
    ("subscription_upgrade_nudge", "Upgrade nudge", TemplateCategory.MARKETING),
]

PROJMAN_KEYS = [
    ("workspace_invite", "Workspace invite", TemplateCategory.TRANSACTIONAL),
    ("task_assignment_notification", "Task assigned", TemplateCategory.TRANSACTIONAL),
    ("project_created_notification", "Project created", TemplateCategory.TRANSACTIONAL),
    ("inactive_collaborator_nudge", "Inactive nudge", TemplateCategory.LIFECYCLE),
]


def _seed_templates_for_tenant(tenant: Tenant, extra_keys: list):
    keys = COMMON_KEYS + extra_keys
    for key, title, cat in keys:
        tpl, _ = EmailTemplate.objects.get_or_create(
            tenant=tenant,
            key=key,
            defaults={
                "name": title,
                "category": cat,
                "status": TemplateStatus.DRAFT,
                "description": f"Seeded template {key}",
                "tags": ["seed"],
            },
        )
        if tpl.versions.filter(is_current_approved=True).exists():
            continue
        ver = EmailTemplateVersion.objects.create(
            template=tpl,
            version_number=1,
            created_by_type=CreatedByType.SYSTEM,
            source_type=VersionSourceType.SEEDED,
            subject_template=f"[{tenant.slug}] {title}",
            preview_text_template="",
            html_template=f"<p>Hello {{{{ user_name }}}},</p><p>Seeded body for {key}.</p>",
            text_template=f"Hello {{{{ user_name }}}}, seeded body for {key}.",
            approval_status=ApprovalStatus.APPROVED,
            is_current_approved=True,
        )
        TemplateVariable.objects.get_or_create(
            template=tpl,
            name="user_name",
            defaults={"description": "Recipient name", "is_required": False},
        )
        tpl.status = TemplateStatus.ACTIVE
        tpl.save(update_fields=["status"])


class Command(BaseCommand):
    help = "Seed tenants (TOMEO, BrainList, ProjMan) and template definitions."

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.accounts.defaults import get_or_create_internal_account

        account = get_or_create_internal_account()
        for spec in TENANTS:
            tenant, created = Tenant.objects.get_or_create(
                slug=spec["slug"],
                defaults={
                    "account": account,
                    "name": spec["name"],
                    "status": TenantStatus.ACTIVE,
                    "default_sender_name": spec["name"],
                    "default_sender_email": f"noreply@{spec['slug']}.example.com",
                    "llm_defaults": spec["llm_defaults"],
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created tenant {tenant.slug}"))
            else:
                self.stdout.write(f"Tenant exists {tenant.slug}")

        mapping = {
            "brainlist": BRAINLIST_KEYS,
            "tomeo": TOMEO_KEYS,
            "projman": PROJMAN_KEYS,
        }
        for slug, keys in mapping.items():
            tenant = Tenant.objects.get(slug=slug)
            _seed_templates_for_tenant(tenant, keys)
            self.stdout.write(self.style.SUCCESS(f"Seeded templates for {slug}"))
