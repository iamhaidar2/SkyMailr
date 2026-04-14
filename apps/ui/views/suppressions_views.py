from django.shortcuts import render

from apps.subscriptions.models import DeliverySuppression, UnsubscribeRecord
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required


@operator_required
def suppressions_list(request):
    qs = DeliverySuppression.objects.select_related("tenant").order_by("-created_at")[:500]
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Suppressions",
            "nav_active": "suppressions",
            "rows": qs,
        }
    )
    return render(request, "ui/pages/suppressions_list.html", ctx)


@operator_required
def unsubscribes_list(request):
    qs = UnsubscribeRecord.objects.select_related("tenant").order_by("-created_at")[:500]
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Unsubscribes",
            "nav_active": "unsubscribes",
            "rows": qs,
        }
    )
    return render(request, "ui/pages/unsubscribes_list.html", ctx)
