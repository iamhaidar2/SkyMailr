from django.shortcuts import render

from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.ui.services.dashboard_data import build_dashboard_context
from apps.ui.services.setup_checks import gather_setup_status


@operator_required
def dashboard(request):
    ctx = operator_shell_context(request)
    ctx.update(build_dashboard_context())
    ctx.update({"setup": gather_setup_status()})
    ctx["page_title"] = "Dashboard"
    ctx["nav_active"] = "dashboard"
    return render(request, "ui/pages/dashboard.html", ctx)
