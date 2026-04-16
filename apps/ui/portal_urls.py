from django.urls import path

from apps.ui.views.customer_portal import (
    CustomerLoginView,
    CustomerLogoutView,
    api_keys_hub,
    dashboard,
    messages_list,
    placeholder,
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
    path("templates/", placeholder, {"slug": "templates"}, name="templates_placeholder"),
    path("workflows/", placeholder, {"slug": "workflows"}, name="workflows_placeholder"),
    path(
        "sender-profiles/",
        placeholder,
        {"slug": "sender-profiles"},
        name="sender_profiles_placeholder",
    ),
]
