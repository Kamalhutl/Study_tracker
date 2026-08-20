"""Development settings. Verbose, forgiving, HTTP, auto-reload."""

from .base import *  # noqa: F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]

INTERNAL_IPS = ["127.0.0.1"]

# Swagger / OpenAPI docs are dev-only.
# SPECTACULAR_SETTINGS already serves Swagger UI + ReDoc from the CDN.

if env("DJANGO_LOG_SQL", default="0", cast_to=int):
    LOGGING["loggers"]["django.db.backends"] = {  # noqa: F405
        "handlers": ["stdout"],
        "level": "DEBUG",
        "propagate": False,
    }
