from django.utils import timezone
from rest_framework import authentication, exceptions

from apps.tenants.crypto import verify_api_key
from apps.tenants.models import TenantAPIKey


class ApiTenantUser:
    is_authenticated = True

    def __init__(self, tenant):
        self.tenant = tenant
        self.pk = tenant.pk


class TenantAPIKeyAuthentication(authentication.BaseAuthentication):
    keyword = b"Bearer"

    def authenticate(self, request):
        header = request.headers.get("Authorization")
        if not header or not header.startswith("Bearer "):
            return None
        raw = header.split(" ", 1)[1].strip()
        if not raw:
            return None
        qs = TenantAPIKey.objects.filter(revoked_at__isnull=True).select_related("tenant")
        for key in qs:
            if verify_api_key(raw, key.key_hash):
                TenantAPIKey.objects.filter(pk=key.pk).update(
                    last_used_at=timezone.now()
                )
                return (ApiTenantUser(key.tenant), key)
        raise exceptions.AuthenticationFailed("Invalid or revoked API key")
