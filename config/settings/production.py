"""Production settings — require env vars; HTTPS-oriented security."""

from .base import *  # noqa: F403

DEBUG = False

# ---------------------------------------------------------------------------
# Secret key — fail loudly if the insecure default slips into production
# ---------------------------------------------------------------------------

_INSECURE_DEFAULT = "django-insecure-change-me-before-production"
if SECRET_KEY == _INSECURE_DEFAULT:  # noqa: F405
    raise ValueError(
        "SECRET_KEY is set to the insecure development default. "
        "Set a strong random SECRET_KEY environment variable before deploying."
    )

# ---------------------------------------------------------------------------
# Logging — rotating file + console, no silent failures
# ---------------------------------------------------------------------------

import logging.handlers  # noqa: E402 — after the base import

_LOG_DIR = BASE_DIR / "logs"  # noqa: F405
_LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING["handlers"]["file"] = {  # noqa: F405
    "class": "logging.handlers.RotatingFileHandler",
    "filename": _LOG_DIR / "vasavi.log",
    "maxBytes": 10 * 1024 * 1024,   # 10 MB per file
    "backupCount": 5,
    "formatter": "standard",
}
LOGGING["root"]["handlers"] = ["console", "file"]  # noqa: F405
for _logger in ("django.security", "axes", "vasavi.security"):
    LOGGING["loggers"][_logger]["handlers"] = ["console", "file"]  # noqa: F405

# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")  # noqa: F405

if not ALLOWED_HOSTS:
    raise ValueError("ALLOWED_HOSTS must be set in production.")

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31_536_000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# ---------------------------------------------------------------------------
# Database — PostgreSQL required
# ---------------------------------------------------------------------------

if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":  # noqa: F405
    raise ValueError(
        "SQLite must not be used in production. Set DATABASE_URL to PostgreSQL."
    )

# ---------------------------------------------------------------------------
# Celery — use database-backed Beat scheduler (safe for multi-process deploy)
# ---------------------------------------------------------------------------

CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_WORKER_CONCURRENCY = env.int("CELERY_WORKER_CONCURRENCY", default=4)  # noqa: F405

# ---------------------------------------------------------------------------
# Content Security Policy (django-csp is installed; activate here)
# ---------------------------------------------------------------------------

CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'",)
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")   # relax only if needed
CSP_IMG_SRC = ("'self'", "data:", "https:")
CSP_FONT_SRC = ("'self'", "https:")
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)
CSP_FORM_ACTION = ("'self'",)
CSP_UPGRADE_INSECURE_REQUESTS = True
CSP_BLOCK_ALL_MIXED_CONTENT = True

# ---------------------------------------------------------------------------
# Sentry — error tracking (set SENTRY_DSN env var to activate)
# ---------------------------------------------------------------------------

_SENTRY_DSN = env("SENTRY_DSN", default="")  # noqa: F405
if _SENTRY_DSN:
    import sentry_sdk  # noqa: PLC0415
    from sentry_sdk.integrations.celery import CeleryIntegration  # noqa: PLC0415
    from sentry_sdk.integrations.django import DjangoIntegration  # noqa: PLC0415
    from sentry_sdk.integrations.logging import LoggingIntegration  # noqa: PLC0415

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        integrations=[
            DjangoIntegration(transaction_style="url"),
            CeleryIntegration(monitor_beat_tasks=True),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),  # noqa: F405
        send_default_pii=False,
        environment=env("SENTRY_ENVIRONMENT", default="production"),  # noqa: F405
        release=env("APP_VERSION", default="unknown"),  # noqa: F405
    )
