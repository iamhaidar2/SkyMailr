from rest_framework.permissions import BasePermission


class HasTenant(BasePermission):
    def has_permission(self, request, view):
        return bool(getattr(request.user, "tenant", None))
