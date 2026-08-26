"""Base settings shared by every environment. No secrets live in this file."""

import sys
from datetime import timedelta
from pathlib import Path

from kombu import Queue

from . import env as env

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = env("SECRET_KEY", default="dev-only-not-a-real-secret-please-change-me") or ""
DEBUG = bool(env("DEBUG", default="1", cast_to=int))
ALLOWED_HOSTS = [
    host.strip()
    for host in (env("ALLOWED_HOSTS", default="localhost,127.0.0.1,0.0.0.0") or "").split(",")
    if host.strip()
]

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.postgres",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "django_filters",
    "corsheaders",
]

LOCAL_APPS = [
    "core",
    "apps.accounts",
    "apps.audit_logs",
    "apps.companies",
    "apps.jobs",
    "apps.scraping",
    "apps.career_detection",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Django 6.0 transitional default: assume https for scheme-less URLs in forms.
FORMS_URLFIELD_ASSUME_HTTPS = True

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.RequestIDMiddleware",
    "apps.audit_logs.middleware.AuditContextMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", default="study_tracker"),
        "USER": env("DB_USER", default="study_tracker"),
        "PASSWORD": env("DB_PASSWORD", default="study_tracker"),
        "HOST": env("DB_HOST", default="127.0.0.1"),
        "PORT": env("DB_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
        "ATOMIC_REQUESTS": False,
    }
}

# ---------------------------------------------------------------------------
# Cache (Redis, database 1)
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": f"{REDIS_URL}/1",
        "TIMEOUT": 300,
    }
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.accounts.validators.MinimumLengthValidator"},
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
TIME_ZONE = "Asia/Kolkata"
USE_TZ = True
LANGUAGE_CODE = "en-us"
USE_I18N = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "core.pagination.CursorAwarePageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "EXCEPTION_HANDLER": "core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "600/min",
        "auth": "10/min",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

# ---------------------------------------------------------------------------
# SimpleJWT
# ---------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_OBTAIN_SERIALIZER": "apps.accounts.serializers.CustomTokenObtainPairSerializer",
    "TOKEN_REFRESH_SERIALIZER": "apps.accounts.serializers.RotatingRefreshSerializer",
}

# ---------------------------------------------------------------------------
# drf-spectacular OpenAPI
# ---------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "Job + Exam Portal API",
    "DESCRIPTION": "Phase 1 MVP: accounts + JWT auth + audit log core.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in (env("CORS_ALLOWED_ORIGINS", default="http://localhost:3000") or "").split(",")
    if origin.strip()
]
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Celery (broker/result backend = Redis DB 0)
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = f"{REDIS_URL}/0"
CELERY_RESULT_BACKEND = f"{REDIS_URL}/0"
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 1800
CELERY_TASK_SOFT_TIME_LIMIT = 1500
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_QUEUES = (
    Queue("default", routing_key="default"),
    Queue("scraping", routing_key="scraping.#"),
    Queue("notifications", routing_key="notifications.#"),
)
CELERY_TASK_ROUTES = {
    "apps.scraping.*": {"queue": "scraping"},
    "apps.career_detection.*": {"queue": "scraping"},
    "apps.notifications.*": {"queue": "notifications"},
}
# STEP 12: 5-hour scrape cycle goes here
CELERY_BEAT_SCHEDULE: dict = {}

# ---------------------------------------------------------------------------
# Fetching (Scrapling wrapper)
# ---------------------------------------------------------------------------
FETCH_USER_AGENT = env(
    "FETCH_USER_AGENT", default="StudyTrackerBot/1.0 (+https://<your-domain>/bot)"
)
FETCH_TIMEOUT_SECONDS = 10
FETCH_MAX_REDIRECTS = 5
FETCH_MAX_RESPONSE_BYTES = 3 * 1024 * 1024
FETCH_ROBOTS_OBEY = True
FETCH_ROBOTS_CACHE_SECONDS = 3600
FETCH_PER_DOMAIN_RATE = 10  # requests per minute per domain
FETCH_PER_DOMAIN_JITTER_MS = (200, 900)
FETCH_ADAPTIVE_STORAGE_DIR = env(
    "FETCH_ADAPTIVE_STORAGE_DIR", default=str(BASE_DIR / "var" / "scrapling")
)
FETCH_ALLOW_DYNAMIC = True
FETCH_ALLOW_STEALTHY = False  # not used in detection; Prompt 4 flips this
FETCH_PROXY = env("FETCH_PROXY", default="")  # optional http://user:pass@host:port
FETCH_SMOKE_URLS: list[str] = []  # `manage.py run_smoke` targets; empty = offline skip

# ---------------------------------------------------------------------------
# Career detection
# ---------------------------------------------------------------------------
DETECTION_MAX_URL_CHECKS = 25
DETECTION_TOTAL_BUDGET_SECONDS = 120
DETECTION_MAX_CANDIDATES = 10
DETECTION_MIN_CANDIDATE_SCORE = 20
DETECTION_SAMPLE_TITLE_LIMIT = 5
DETECTION_ATS_SHORTCIRCUIT_SCORE = 60
DETECTION_COMMON_SUBDOMAINS = ["careers", "career", "jobs", "job", "work", "hiring"]
DETECTION_COMMON_PATHS = [
    "/careers",
    "/careers/",
    "/career",
    "/jobs",
    "/jobs/",
    "/job",
    "/about/careers",
    "/company/careers",
    "/en/careers",
    "/work-with-us",
    "/join-us",
    "/join-our-team",
    "/opportunities",
    "/hiring",
    "/openings",
    "/vacancies",
]

# ---------------------------------------------------------------------------
# Logging (JSON to stdout, request_id on every record)
# ---------------------------------------------------------------------------
LOGGING: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "core.logging.RequestIdFilter"},
    },
    "formatters": {
        "json": {"()": "core.logging.JsonFormatter"},
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "json",
            "filters": ["request_id"],
        },
    },
    "loggers": {
        "django": {"handlers": ["stdout"], "level": "INFO"},
        "django.request": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "study_tracker": {"handlers": ["stdout"], "level": "INFO"},
    },
}

if env("DJANGO_LOG_SQL", default="0", cast_to=int):
    LOGGING["loggers"]["django.db.backends"] = {
        "handlers": ["stdout"],
        "level": "DEBUG",
        "propagate": False,
    }

# ---------------------------------------------------------------------------
# Sentry (only active when SENTRY_DSN is set)
# ---------------------------------------------------------------------------
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=float(env("SENTRY_TRACES_SAMPLE_RATE", default="0.0")),
        send_default_pii=False,
    )
