from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def operator_required(view_func):
    """Session-authenticated staff users only."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("ui:login")
        if not request.user.is_staff:
            from django.http import HttpResponseForbidden

            return HttpResponseForbidden("Staff access required.")
        return view_func(request, *args, **kwargs)

    return login_required(_wrapped)
