"""
Shared Django settings for the Vasavi backend.

Environment-specific modules (``development``, ``production``) import from here.
"""

from datetime import timedelta
from pathlib import Path

import environ

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)

# Read .env from project root (backend/)
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY = env(
    "SECRET_KEY",
    default="django-insecure-change-me-before-production",
)

DEBUG = env.bool("DEBUG", default=False)

ALLOWED_HOSTS: list[str] = env.list("ALLOWED_HOSTS", default=[])

ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "axes",
    "django_celery_beat",  # DB-backed periodic task scheduler
]

LOCAL_APPS = [
    "core.apps.CoreConfig",
    "accounts.apps.AccountsConfig",
    "branches.apps.BranchesConfig",
    "properties.apps.PropertiesConfig",
    "donors.apps.DonorsConfig",
    "bookings.apps.BookingsConfig",
    "coupons.apps.CouponsConfig",
    "support.apps.SupportConfig",
    "notifications.apps.NotificationsConfig",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "axes.middleware.AxesMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.IdempotencyMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Database (override in local / production)
# ---------------------------------------------------------------------------

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    ),
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

ADMIN_URL = env("ADMIN_URL", default="admin/")

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "120/minute",
        "user": "1200/minute",
        "otp_send": "5/hour",
        "otp_verify": "3/10minute",
        "staff_otp_send": "5/hour",
        "staff_otp_verify": "3/10minute",
        "booking_create": "30/hour",
        "payment": "20/hour",
    },
    "DEFAULT_PAGINATION_CLASS": "utils.pagination.VasaviPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "EXCEPTION_HANDLER": "utils.exceptions.custom_exception_handler",
}

# Guest-facing cash checkout — always on (Razorpay deferred).
CASH_CHECKOUT_ENABLED = env.bool("CASH_CHECKOUT_ENABLED", default=True)

# Razorpay — disabled until credentials are provisioned.
RAZORPAY_ENABLED = env.bool("RAZORPAY_ENABLED", default=False)

# PENDING booking TTL in minutes. After this, Celery auto-cancels unpaid bookings.
BOOKING_PENDING_EXPIRY_MINUTES = env.int("BOOKING_PENDING_EXPIRY_MINUTES", default=15)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# django-axes 8.x — define every setting axes reads via ``settings.NAME`` (not only
# getattr). Missing keys cause AttributeError on admin login (see axes/conf.py).
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 10
AXES_LOCK_OUT_AT_FAILURE = True
AXES_LOCKOUT_PARAMETERS = ["ip_address", "username"]
AXES_ONLY_ADMIN_SITE = False
AXES_ENABLE_ADMIN = True
AXES_USERNAME_FORM_FIELD = "username"
AXES_PASSWORD_FORM_FIELD = "password"
AXES_USERNAME_CALLABLE = None
AXES_WHITELIST_CALLABLE = None
AXES_LOCKOUT_CALLABLE = None
AXES_CLIENT_IP_CALLABLE = None
AXES_CLIENT_STR_CALLABLE = None
AXES_RESET_ON_SUCCESS = True
AXES_DISABLE_ACCESS_LOG = False
AXES_ENABLE_ACCESS_FAILURE_LOG = False
AXES_ACCESS_FAILURE_LOG_PER_USER_LIMIT = 1000
AXES_HANDLER = "axes.handlers.database.AxesDatabaseHandler"
AXES_LOCKOUT_TEMPLATE = None
AXES_LOCKOUT_URL = None
AXES_COOLOFF_TIME = timedelta(hours=1)
AXES_USE_ATTEMPT_EXPIRATION = False
AXES_VERBOSE = True
AXES_NEVER_LOCKOUT_WHITELIST = False
AXES_NEVER_LOCKOUT_GET = False
AXES_ONLY_WHITELIST = False
AXES_IP_WHITELIST = None
AXES_IP_BLACKLIST = None
AXES_COOLOFF_MESSAGE = "Account locked: too many login attempts. Please try again later."
AXES_PERMALOCK_MESSAGE = (
    "Account locked: too many login attempts. Contact an admin to unlock your account."
)
AXES_ALLOWED_CORS_ORIGINS = "*"
AXES_SENSITIVE_PARAMETERS = ["username", "password", "ip_address"]
AXES_HTTP_RESPONSE_CODE = 429
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = True
AXES_IPWARE_PROXY_ORDER = "left-most"
AXES_IPWARE_PROXY_COUNT = None
AXES_IPWARE_PROXY_TRUSTED_IPS = None
AXES_IPWARE_META_PRECEDENCE_ORDER = ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[],
)
CORS_ALLOW_HEADERS = list(
    (
        "accept",
        "accept-encoding",
        "authorization",
        "content-type",
        "dnt",
        "origin",
        "user-agent",
        "x-csrftoken",
        "x-requested-with",
        "x-idempotency-key",
        "idempotency-key",
    )
)

REDIS_URL = env("REDIS_URL", default=env("CELERY_BROKER_URL", default="redis://localhost:6379/0"))

SMS_BACKEND = env("SMS_BACKEND", default="utils.sms.ConsoleSMSBackend")
SMS_API_KEY = env("SMS_API_KEY", default="")
SMS_SENDER_ID = env("SMS_SENDER_ID", default="VASAVI")
SMS_API_URL = env("SMS_API_URL", default="")

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

# Supabase Storage (property photos only — bucket must be public for guest URLs).
SUPABASE_URL = env("SUPABASE_URL", default="")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY", default="")
SUPABASE_PUBLISHABLE_KEY = env("SUPABASE_PUBLISHABLE_KEY", default="")
SUPABASE_STORAGE_BUCKET = env("SUPABASE_STORAGE_BUCKET", default="images")

# Storage API (upload/delete) must use the service role — publishable key hits RLS.
SUPABASE_STORAGE_KEY = SUPABASE_SERVICE_ROLE_KEY
_use_supabase_images = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)

STORAGES = {
    "default": {
        "BACKEND": (
            "core.storage.supabase.SupabaseStorage"
            if _use_supabase_images
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
# Object key prefixes inside the Supabase ``images`` bucket (or MEDIA_ROOT subdirs locally).
MEDIA_ROOMS_DIR = "rooms"
MEDIA_FUNCTION_HALLS_DIR = "function_halls"

# ---------------------------------------------------------------------------
# Security defaults (tightened in production)
# ---------------------------------------------------------------------------

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": env("DJANGO_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "axes": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "vasavi": {
            "handlers": ["console"],
            "level": env("VASAVI_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
        "vasavi.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env(
    "CELERY_RESULT_BACKEND",
    default=CELERY_BROKER_URL,
)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True

CELERY_TASK_ROUTES = {
    "accounts.tasks.cleanup_expired_otps": {"queue": "maintenance"},
    "bookings.tasks.expire_pending_bookings": {"queue": "maintenance"},
    "bookings.tasks.razorpay_create_order": {"queue": "payments"},
    "bookings.tasks.razorpay_verify_payment_webhook": {"queue": "payments"},
    "bookings.tasks.send_booking_confirmation": {"queue": "notifications"},
    "bookings.tasks.booking_status_notification": {"queue": "notifications"},
    "bookings.tasks.generate_booking_export": {"queue": "exports"},
    "bookings.tasks.cleanup_expired_booking_exports": {"queue": "maintenance"},
    "donors.tasks.export_donors_data": {"queue": "exports"},
}

CELERY_TASK_DEFAULT_QUEUE = "default"

OTP_LOG_RETENTION_DAYS = env.int("OTP_LOG_RETENTION_DAYS", default=30)

CELERY_BEAT_SCHEDULE = {
    "cleanup-expired-otps-hourly": {
        "task": "accounts.tasks.cleanup_expired_otps",
        "schedule": 3600.0,
    },
    "expire-pending-bookings-every-5min": {
        "task": "bookings.tasks.expire_pending_bookings",
        "schedule": 300.0,  # every 5 minutes
    },
    "cleanup-booking-exports-hourly": {
        "task": "bookings.tasks.cleanup_expired_booking_exports",
        "schedule": 3600.0,  # every hour
    },
}

# ---------------------------------------------------------------------------
# Razorpay
# ---------------------------------------------------------------------------

RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", default="")
RAZORPAY_CURRENCY = env("RAZORPAY_CURRENCY", default="INR")

# ---------------------------------------------------------------------------
# Notifications (booking confirmations / status updates)
# ---------------------------------------------------------------------------

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@vasavi.example")
BOOKING_NOTIFICATION_EMAIL = env(
    "BOOKING_NOTIFICATION_EMAIL",
    default=DEFAULT_FROM_EMAIL,
)
SMS_PROVIDER_ENABLED = env.bool("SMS_PROVIDER_ENABLED", default=False)

# ---------------------------------------------------------------------------
# Donor data exports (async CSV downloads)
# ---------------------------------------------------------------------------

DONOR_EXPORT_DIR = BASE_DIR / "media" / "exports" / "donors"
DONOR_EXPORT_RETENTION_DAYS = env.int("DONOR_EXPORT_RETENTION_DAYS", default=7)

# ---------------------------------------------------------------------------
# Booking data exports (async xlsx downloads)
# ---------------------------------------------------------------------------

BOOKING_EXPORT_DIR = BASE_DIR / "media" / "exports" / "bookings"
BOOKING_EXPORT_RETENTION_DAYS = env.int("BOOKING_EXPORT_RETENTION_DAYS", default=7)

# ---------------------------------------------------------------------------
# Idempotency (X-Idempotency-Key) — see docs/security.md
# ---------------------------------------------------------------------------

IDEMPOTENCY_KEY_REQUIRED = env.bool("IDEMPOTENCY_KEY_REQUIRED", default=True)
IDEMPOTENCY_TTL_HOURS = env.int("IDEMPOTENCY_TTL_HOURS", default=24)
IDEMPOTENCY_RETRY_AFTER_SECONDS = env.int("IDEMPOTENCY_RETRY_AFTER_SECONDS", default=2)

# Paths that MUST send X-Idempotency-Key on POST/PUT/PATCH
IDEMPOTENCY_PROTECTED_PREFIXES = [
    "/api/v1/accounts/",
    "/api/v1/bookings/",
    "/api/v1/staff/bookings/",
    "/api/v1/donors/",
    "/api/v1/coupons/",
    "/api/accounts/",
    "/api/bookings/",
    "/api/staff/bookings/",
    "/api/donors/",
    "/api/coupons/",
]

# Exempt server-to-server or idempotent-by-nature endpoints
IDEMPOTENCY_EXCLUDED_PREFIXES = [
    "/api/v1/bookings/webhooks/",
    "/api/bookings/webhooks/",
    "/admin/",
    "/api/v1/accounts/otp/",
    "/api/v1/accounts/token/refresh/",
    "/api/v1/staff/otp/",
    "/api/v1/staff/token/refresh/",
    "/api/accounts/otp/",
    "/api/accounts/token/refresh/",
    "/api/staff/token/refresh/",
]
