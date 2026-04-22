"""django.shortcuts.redirect must not raise (Django 5.2.13 preserve_request quirk)."""

from django.shortcuts import redirect


def test_redirect_to_named_url_does_not_raise():
    r = redirect("ui:dashboard")
    assert r.status_code in (301, 302, 303, 307, 308)
    assert "Location" in r


def test_redirect_preserve_request_false_does_not_raise():
    r = redirect("ui:home", preserve_request=False)
    assert r.status_code == 302
