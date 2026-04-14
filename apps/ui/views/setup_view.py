from django.shortcuts import render

from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.ui.services.setup_checks import gather_setup_status


@operator_required
def setup(request):
    ctx = operator_shell_context(request)
    ctx.update({"page_title": "Setup & status", "nav_active": "setup", "setup": gather_setup_status()})
    return render(request, "ui/pages/setup.html", ctx)
