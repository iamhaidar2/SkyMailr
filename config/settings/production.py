from .base import *  # noqa: F401,F403

DEBUG = False

# Merge extra hosts (e.g. Railway preview URLs) without replacing explicit ALLOWED_HOSTS
_extra_hosts = os.environ.get("ALLOWED_HOSTS_EXTRA", "")
if _extra_hosts.strip():
    ALLOWED_HOSTS = list(
        dict.fromkeys(
            list(ALLOWED_HOSTS)
            + [h.strip() for h in _extra_hosts.split(",") if h.strip()]
        )
    )

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "true").lower() in ("1", "true", "yes")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
