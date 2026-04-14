from django.contrib import admin

admin.site.site_header = "SkyMailr administration"
from django.urls import include, path

from apps.api.v1.views import (
    CreateApiKeyView,
    HealthView,
    MessageCancelView,
    MessageDetailView,
    MessageEventsView,
    MessageRetryView,
    ProviderHealthView,
    ProviderWebhookView,
    SendRawView,
    SendTemplateView,
    SuppressionListView,
    TemplateApproveView,
    TemplateGenerateView,
    TemplateListView,
    TemplatePreviewView,
    TemplateReviseView,
    UnsubscribeView,
    WorkflowCreateView,
    WorkflowEnrollView,
)
from apps.core.views import (
    empty_sitemap,
    internal_dashboard,
    noop_favicon,
)

urlpatterns = [
    path("", include("apps.ui.urls")),
    path("favicon.ico", noop_favicon),
    path("sitemap.xml", empty_sitemap),
    path("admin/", admin.site.urls),
    path("internal/dashboard/", internal_dashboard, name="internal_dashboard"),
    path("api/v1/health/", HealthView.as_view()),
    path("api/v1/providers/health/", ProviderHealthView.as_view()),
    path("api/v1/messages/send/", SendRawView.as_view()),
    path("api/v1/messages/send-template/", SendTemplateView.as_view()),
    path("api/v1/messages/<uuid:uuid>/", MessageDetailView.as_view()),
    path("api/v1/messages/<uuid:uuid>/events/", MessageEventsView.as_view()),
    path("api/v1/messages/<uuid:uuid>/retry/", MessageRetryView.as_view()),
    path("api/v1/messages/<uuid:uuid>/cancel/", MessageCancelView.as_view()),
    path("api/v1/templates/", TemplateListView.as_view()),
    path("api/v1/templates/generate/", TemplateGenerateView.as_view()),
    path("api/v1/templates/<uuid:template_id>/revise/", TemplateReviseView.as_view()),
    path("api/v1/templates/<uuid:template_id>/approve/", TemplateApproveView.as_view()),
    path("api/v1/templates/<uuid:template_id>/preview/", TemplatePreviewView.as_view()),
    path("api/v1/workflows/", WorkflowCreateView.as_view()),
    path("api/v1/workflows/<uuid:workflow_id>/enroll/", WorkflowEnrollView.as_view()),
    path("api/v1/subscriptions/unsubscribe/", UnsubscribeView.as_view()),
    path(
        "api/v1/webhooks/provider/<str:provider>/",
        ProviderWebhookView.as_view(),
    ),
    path("api/v1/tenants/api-keys/", CreateApiKeyView.as_view()),
    path("api/v1/suppressions/", SuppressionListView.as_view()),
]
