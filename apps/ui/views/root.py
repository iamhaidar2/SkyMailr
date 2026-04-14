from django.http import JsonResponse


def service_meta(request):
    return JsonResponse(
        {
            "service": "SkyMailr",
            "health": "/api/v1/health/",
            "admin": "/admin/",
            "operator": "/",
        }
    )
