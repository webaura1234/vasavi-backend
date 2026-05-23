"""Production settings — require env vars; HTTPS-oriented security."""

from .base import *  # noqa: F403

DEBUG = False

LOGGING["handlers"]["file"] = {  # noqa: F405
    "class": "logging.FileHandler",
    "filename": BASE_DIR / "logs" / "vasavi.log",  # noqa: F405
    "formatter": "standard",
}
LOGGING["root"]["handlers"] = ["console", "file"]  # noqa: F405
for _logger in ("django.security", "axes", "vasavi.security"):
    LOGGING["loggers"][_logger]["handlers"] = ["console", "file"]  # noqa: F405

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

# ---------------------------------------------------------------------------
# Database — PostgreSQL required
# ---------------------------------------------------------------------------

if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":  # noqa: F405
    raise ValueError(
        "SQLite must not be used in production. Set DATABASE_URL to PostgreSQL."
    )
