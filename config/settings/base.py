"""
Base Django settings for SkyMailr.
"""
import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-in-production")

DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() in ("1", "true", "yes")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "corsheaders",
    "django_celery_beat",
    "rest_framework",
    "apps.core",
    "apps.accounts",
    "apps.tenants",
    "apps.email_templates",
    "apps.messages",
    "apps.workflows",
    "apps.subscriptions",
    "apps.llm",
    "apps.providers",
    "apps.api",
    "apps.ui",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestCorrelationMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

_default_db = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL", _default_db),
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/operator/"
LOGOUT_REDIRECT_URL = "/login/"

# --- Redis / Celery ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 30
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Minimum tenant dispatch rate when rate_limit_per_minute is 0 or unset (messages/min rolling window).
SKYMAILR_DISPATCH_RATE_LIMIT_FLOOR_PER_MINUTE = int(
    os.environ.get("SKYMAILR_DISPATCH_RATE_LIMIT_FLOOR_PER_MINUTE", "30")
)

CELERY_BEAT_SCHEDULE = {
    "skymailr-sweep-dispatch": {
        "task": "apps.messages.tasks.sweep_dispatch_queue",
        "schedule": 15.0,
    },
    "skymailr-workflow-steps": {
        "task": "apps.workflows.tasks.process_workflow_due_steps",
        "schedule": 15.0,
    },
    "skymailr-retry-deferred": {
        "task": "apps.messages.tasks.retry_due_deferred",
        "schedule": 45.0,
    },
}

# --- Email provider (outbound) ---
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "dummy").lower()
POSTAL_BASE_URL = os.environ.get("POSTAL_BASE_URL", "")
POSTAL_SERVER_API_KEY = os.environ.get("POSTAL_SERVER_API_KEY", "")
POSTAL_TIMEOUT = float(os.environ.get("POSTAL_TIMEOUT", "30"))
POSTAL_USE_TLS_VERIFY = os.environ.get("POSTAL_USE_TLS_VERIFY", "true").lower() in ("1", "true", "yes")

# Optional HTTPS endpoint that creates/gets a Postal domain and returns DNS metadata JSON.
# Stock Postal does not expose domain CRUD on the public server API; operators often deploy
# a small bridge next to Postal. See apps.providers.postal_provisioning.
POSTAL_PROVISIONING_URL = os.environ.get("POSTAL_PROVISIONING_URL", "").strip()
POSTAL_PROVISIONING_SECRET = os.environ.get("POSTAL_PROVISIONING_SECRET", "").strip()

# Customer domain onboarding — DNS instruction templates & automated checks (optional)
SKYMAILR_SPF_INCLUDE_HINT = os.environ.get("SKYMAILR_SPF_INCLUDE_HINT", "").strip()
SKYMAILR_DKIM_SELECTOR = os.environ.get("SKYMAILR_DKIM_SELECTOR", "postal").strip()
SKYMAILR_RETURN_PATH_HOST = os.environ.get("SKYMAILR_RETURN_PATH_HOST", "").strip()
# Host label for return-path CNAME on the customer's domain (Postal default is often psrp).
SKYMAILR_RETURN_PATH_PREFIX = os.environ.get("SKYMAILR_RETURN_PATH_PREFIX", "psrp").strip() or "psrp"
# Comma-separated MX hostnames when the bridge did not store mx_targets on TenantDomain.
SKYMAILR_MX_TARGETS = os.environ.get("SKYMAILR_MX_TARGETS", "").strip()
# When true, Postal dispatch does not require a verified TenantDomain for the From domain (local/staging only).
SKYMAILR_ALLOW_UNVERIFIED_DOMAIN_SEND = (
    os.environ.get("SKYMAILR_ALLOW_UNVERIFIED_DOMAIN_SEND", "").lower() in ("1", "true", "yes")
)

# --- LLM (BrainList-compatible env names) ---
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "dummy").lower()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip() or ""
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
SKYMAILR_DEFAULT_LLM_MODEL = os.environ.get("SKYMAILR_DEFAULT_LLM_MODEL", "gpt-4o-mini")

# --- Security / API ---
API_KEY_PEPPER = os.environ.get("API_KEY_PEPPER", "")
WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS = int(os.environ.get("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", "300"))

# --- Observability ---
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

if SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
            send_default_pii=False,
        )
    except ImportError:
        pass

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": "%(asctime)s %(levelname)s %(name)s [%(correlation_id)s] %(message)s",
        },
    },
    "filters": {
        "correlation": {"()": "apps.core.logging.CorrelationIdFilter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
            "filters": ["correlation"],
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "apps": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "celery": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.api.authentication.TenantAPIKeyAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "EXCEPTION_HANDLER": "apps.api.exceptions.custom_exception_handler",
}

CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

# --- Django email (portal invites, password reset, verification) ---
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "SkyMailr <noreply@localhost>")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "skymailr-portal",
    },
}
