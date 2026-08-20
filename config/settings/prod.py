"""Production settings. Hardened, HTTPS-first, fail loudly on misconfiguration."""

from .base import *  # noqa: F403
from .base import env as env

DEBUG = False

SECRET_KEY = env("SECRET_KEY", required=True) or ""
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

ALLOWED_HOSTS = [
    host.strip() for host in (env("ALLOWED_HOSTS", required=True) or "").split(",") if host.strip()
]
if not ALLOWED_HOSTS:
    raise RuntimeError("ALLOWED_HOSTS must be set and non-empty in production.")
