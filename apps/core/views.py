from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import redirect


@staff_member_required
def internal_dashboard(request):
    """Legacy URL — forwards to the operator UI."""
    return redirect("ui:dashboard")


def noop_favicon(request):
    return HttpResponse(status=204)


def empty_sitemap(request):
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
    )
    return HttpResponse(body, content_type="application/xml")
