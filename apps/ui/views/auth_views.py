from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy


class OperatorLoginView(LoginView):
    template_name = "ui/login.html"
    redirect_authenticated_user = True


class OperatorLogoutView(LogoutView):
    next_page = reverse_lazy("ui:login")
