from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpResponseRedirect
from django.urls import reverse, reverse_lazy


class OperatorLoginView(LoginView):
    template_name = "ui/login.html"
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_staff:
            return HttpResponseRedirect(reverse("portal:dashboard"))
        return super().dispatch(request, *args, **kwargs)


class OperatorLogoutView(LogoutView):
    next_page = reverse_lazy("ui:login")
