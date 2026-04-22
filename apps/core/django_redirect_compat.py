"""
Django 5.2.13 ships shortcuts.redirect(..., preserve_request=...) but HttpResponseRedirect
does not accept that keyword, causing TypeError on every redirect() call.

Upstream 5.2.x fixes HttpResponseRedirectBase to accept preserve_request. Until a fixed
release is on PyPI, patch django.shortcuts.redirect in-process.

See: django.shortcuts.redirect passing preserve_request to HttpResponseRedirect.__init__.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def apply_redirect_patch_if_needed() -> None:
    import django.shortcuts as shortcuts_mod
    from django.http import HttpResponsePermanentRedirect, HttpResponseRedirect

    try:
        HttpResponseRedirect("http://example.com/__skymailr_redirect_probe__", preserve_request=False)
        return
    except TypeError:
        pass

    if getattr(shortcuts_mod.redirect, "_skymailr_redirect_patched", False):
        return

    _resolve_url = shortcuts_mod.resolve_url

    def redirect(to, *args, permanent=False, preserve_request=False, **kwargs):
        redirect_class = HttpResponsePermanentRedirect if permanent else HttpResponseRedirect
        resolved = _resolve_url(to, *args, **kwargs)
        try:
            return redirect_class(resolved, preserve_request=preserve_request)
        except TypeError:
            resp = redirect_class(resolved)
            if preserve_request:
                resp.status_code = 308 if permanent else 307
            return resp

    redirect._skymailr_redirect_patched = True
    shortcuts_mod.redirect = redirect
    logger.warning(
        "SkyMailr: patched django.shortcuts.redirect for preserve_request / HttpResponseRedirect compatibility "
        "(Django 5.2.13 quirk; remove when using a Django release where HttpResponseRedirect accepts preserve_request)."
    )
