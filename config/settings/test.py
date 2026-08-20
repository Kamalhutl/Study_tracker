"""Test settings: fast, isolated, additive-only (do not disable migrations)."""

from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["testserver"]

# In-memory cache -> no Redis dependency in tests.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test",
    }
}

# Fast password hashing for tests.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Run Celery tasks synchronously.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Raise loudly on broken settings.
SILENCED_SYSTEM_CHECKS: list[str] = []

# Single-threaded thumb twiddler.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
