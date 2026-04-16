from django.http import JsonResponse
from django.urls import reverse


def service_meta(request):
    return JsonResponse(
        {
            "service": "SkyMailr",
            "health": "/api/v1/health/",
            "admin": "/admin/",
            "operator": reverse("ui:dashboard"),
            "marketing": reverse("ui:home"),
        }
    )
