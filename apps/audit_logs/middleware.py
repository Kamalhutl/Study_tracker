"""AuditContextMiddleware: plants actor/ip/request_id contextvars per request."""

from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin

from .services import _actor_var, _ip_var, _request_id_var


class AuditContextMiddleware(MiddlewareMixin):
    """Lets ``record()`` deep inside services auto-fill actor/ip/request_id.

    Contextvars make this async-safe; values are reset per-request so we
    never leak state between requests.
    """

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = getattr(request, "request_id", "") or ""
        actor = getattr(request, "user", None)
        ip = request.META.get("REMOTE_ADDR", "") or None

        token_actor = _actor_var.set(actor if getattr(actor, "is_authenticated", False) else None)
        token_ip = _ip_var.set(ip)
        token_rid = _request_id_var.set(request_id)
        try:
            return super().__call__(request)  # type: ignore[return-value]
        finally:
            _actor_var.reset(token_actor)
            _ip_var.reset(token_ip)
            _request_id_var.reset(token_rid)
