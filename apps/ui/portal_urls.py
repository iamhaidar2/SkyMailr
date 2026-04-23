from django.urls import path

from apps.ui.views import portal_automation, portal_suppressions, portal_tenant_domains, portal_webhooks
from apps.ui.views.customer_portal import (
    CustomerLoginView,
    CustomerLogoutView,
    account_billing,
    account_usage,
    api_keys_hub,
    api_keys_hub_create,
    dashboard,
    messages_list,
    quick_start,
    sending_domains_hub,
    signup,
    switch_account,
    tenant_create_api_key,
    tenant_detail,
    tenant_list,
    tenant_new,
)
from apps.ui.views.portal_invite_public import invite_accept, signup_via_invite
from apps.ui.views.portal_members import (
    invite_cancel,
    invite_resend,
    member_deactivate,
    member_edit,
    members_invite,
    members_list,
)
from apps.ui.views.portal_password import (
    PortalPasswordResetCompleteView,
    PortalPasswordResetConfirmView,
    PortalPasswordResetDoneView,
    PortalPasswordResetView,
)
from apps.ui.views.portal_verify_email import verify_email_confirm

app_name = "portal"

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("signup/", signup, name="signup"),
    path("signup/invite/<str:token>/", signup_via_invite, name="signup_invite"),
    path("login/", CustomerLoginView.as_view(), name="login"),
    path("logout/", CustomerLogoutView.as_view(), name="logout"),
    path("switch-account/", switch_account, name="switch_account"),
    path("account/usage/", account_usage, name="account_usage"),
    path("account/sending-domains/", sending_domains_hub, name="sending_domains"),
    path("account/quick-start/", quick_start, name="quick_start"),
    path("account/billing/", account_billing, name="account_billing"),
    # Password reset
    path("password-reset/", PortalPasswordResetView.as_view(), name="password_reset"),
    path(
        "password-reset/done/",
        PortalPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        PortalPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        PortalPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("verify-email/<str:token>/", verify_email_confirm, name="verify_email_confirm"),
    path("invites/<str:token>/accept/", invite_accept, name="invite_accept"),
    path("account/members/", members_list, name="members_list"),
    path("account/members/invite/", members_invite, name="members_invite"),
    path(
        "account/members/<uuid:membership_id>/edit/",
        member_edit,
        name="member_edit",
    ),
    path(
        "account/members/<uuid:membership_id>/deactivate/",
        member_deactivate,
        name="member_deactivate",
    ),
    path(
        "account/invites/<uuid:invite_id>/cancel/",
        invite_cancel,
        name="invite_cancel",
    ),
    path(
        "account/invites/<uuid:invite_id>/resend/",
        invite_resend,
        name="invite_resend",
    ),
    path("account/tenants/", tenant_list, name="tenant_list"),
    path("account/tenants/new/", tenant_new, name="tenant_new"),
    path("account/tenants/<uuid:tenant_id>/", tenant_detail, name="tenant_detail"),
    path(
        "account/tenants/<uuid:tenant_id>/api-keys/",
        tenant_create_api_key,
        name="tenant_create_api_key",
    ),
    path(
        "account/tenants/<uuid:tenant_id>/domains/",
        portal_tenant_domains.tenant_domain_list,
        name="tenant_domain_list",
    ),
    path(
        "account/tenants/<uuid:tenant_id>/domains/new/",
        portal_tenant_domains.tenant_domain_new,
        name="tenant_domain_new",
    ),
    path(
        "account/tenants/<uuid:tenant_id>/domains/<uuid:domain_id>/",
        portal_tenant_domains.tenant_domain_detail,
        name="tenant_domain_detail",
    ),
    path(
        "account/tenants/<uuid:tenant_id>/domains/<uuid:domain_id>/verify/",
        portal_tenant_domains.tenant_domain_verify,
        name="tenant_domain_verify",
    ),
    path(
        "account/tenants/<uuid:tenant_id>/domains/<uuid:domain_id>/retry-postal/",
        portal_tenant_domains.tenant_domain_retry_postal,
        name="tenant_domain_retry_postal",
    ),
    path(
        "account/tenants/<uuid:tenant_id>/domains/<uuid:domain_id>/make-primary/",
        portal_tenant_domains.tenant_domain_make_primary,
        name="tenant_domain_make_primary",
    ),
    path(
        "account/tenants/<uuid:tenant_id>/domains/<uuid:domain_id>/delete/",
        portal_tenant_domains.tenant_domain_delete,
        name="tenant_domain_delete",
    ),
    path("account/api-keys/", api_keys_hub, name="api_keys"),
    path("account/api-keys/create/", api_keys_hub_create, name="api_keys_hub_create"),
    path("account/messages/", messages_list, name="messages_list"),
    path(
        "account/suppressions/",
        portal_suppressions.portal_suppression_list,
        name="suppressions_list",
    ),
    path(
        "account/suppressions/add/",
        portal_suppressions.portal_suppression_add,
        name="suppression_add",
    ),
    path(
        "account/suppressions/<uuid:suppression_id>/delete/",
        portal_suppressions.portal_suppression_delete,
        name="suppression_delete",
    ),
    path(
        "account/webhooks/",
        portal_webhooks.portal_webhooks_overview,
        name="webhooks_overview",
    ),
    # Sender profiles
    path("account/sender-profiles/", portal_automation.sender_profile_list, name="sender_profile_list"),
    path(
        "account/sender-profiles/new/",
        portal_automation.sender_profile_new,
        name="sender_profile_new",
    ),
    path(
        "account/sender-profiles/<uuid:profile_id>/",
        portal_automation.sender_profile_detail,
        name="sender_profile_detail",
    ),
    path(
        "account/sender-profiles/<uuid:profile_id>/edit/",
        portal_automation.sender_profile_edit,
        name="sender_profile_edit",
    ),
    path(
        "account/sender-profiles/<uuid:profile_id>/delete/",
        portal_automation.sender_profile_delete,
        name="sender_profile_delete",
    ),
    # Templates
    path("account/templates/", portal_automation.template_list, name="template_list"),
    path("account/templates/new/", portal_automation.template_new, name="template_new"),
    path(
        "account/templates/<uuid:template_id>/setup/",
        portal_automation.template_setup,
        name="template_setup",
    ),
    path(
        "account/templates/<uuid:template_id>/preview-draft/",
        portal_automation.template_preview_draft,
        name="template_preview_draft",
    ),
    path(
        "account/templates/<uuid:template_id>/delete/",
        portal_automation.template_delete,
        name="template_delete",
    ),
    path(
        "account/templates/<uuid:template_id>/",
        portal_automation.template_detail,
        name="template_detail",
    ),
    path(
        "account/templates/<uuid:template_id>/versions/",
        portal_automation.template_version_create,
        name="template_version_create",
    ),
    path(
        "account/templates/<uuid:template_id>/preview/",
        portal_automation.template_preview,
        name="template_preview",
    ),
    path(
        "account/templates/<uuid:template_id>/approve/",
        portal_automation.template_approve,
        name="template_approve",
    ),
    path(
        "account/templates/<uuid:template_id>/revise/",
        portal_automation.template_revise,
        name="template_revise",
    ),
    # Workflows
    path("account/workflows/", portal_automation.workflow_list, name="workflow_list"),
    path("account/workflows/new/", portal_automation.workflow_new, name="workflow_new"),
    path(
        "account/workflows/<uuid:workflow_id>/",
        portal_automation.workflow_detail,
        name="workflow_detail",
    ),
    path(
        "account/workflows/<uuid:workflow_id>/enroll/",
        portal_automation.workflow_enroll,
        name="workflow_enroll",
    ),
    path(
        "account/workflows/<uuid:workflow_id>/steps/<uuid:step_id>/update/",
        portal_automation.workflow_step_update,
        name="workflow_step_update",
    ),
    path(
        "account/workflows/<uuid:workflow_id>/steps/<uuid:step_id>/delete/",
        portal_automation.workflow_step_delete,
        name="workflow_step_delete",
    ),
    path(
        "account/workflows/<uuid:workflow_id>/steps/",
        portal_automation.workflow_add_step,
        name="workflow_add_step",
    ),
]
