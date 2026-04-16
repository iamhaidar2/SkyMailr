from django.urls import path

from apps.ui.views import portal_automation
from apps.ui.views.customer_portal import (
    CustomerLoginView,
    CustomerLogoutView,
    api_keys_hub,
    dashboard,
    messages_list,
    signup,
    switch_account,
    tenant_create_api_key,
    tenant_detail,
    tenant_list,
    tenant_new,
)

app_name = "portal"

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("signup/", signup, name="signup"),
    path("login/", CustomerLoginView.as_view(), name="login"),
    path("logout/", CustomerLogoutView.as_view(), name="logout"),
    path("switch-account/", switch_account, name="switch_account"),
    path("account/tenants/", tenant_list, name="tenant_list"),
    path("account/tenants/new/", tenant_new, name="tenant_new"),
    path("account/tenants/<uuid:tenant_id>/", tenant_detail, name="tenant_detail"),
    path(
        "account/tenants/<uuid:tenant_id>/api-keys/",
        tenant_create_api_key,
        name="tenant_create_api_key",
    ),
    path("account/api-keys/", api_keys_hub, name="api_keys"),
    path("account/messages/", messages_list, name="messages_list"),
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
        "account/workflows/<uuid:workflow_id>/steps/",
        portal_automation.workflow_add_step,
        name="workflow_add_step",
    ),
]
