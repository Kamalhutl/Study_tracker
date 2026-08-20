"""Central DRF exception handler producing a stable error envelope."""

import logging
import uuid
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("study_tracker.errors")

HTTP_BAD_REQUEST = status.HTTP_400_BAD_REQUEST

CODE_MAP: dict[type[Exception], str] = {
    DjangoValidationError: "validation_error",
    exceptions.ValidationError: "validation_error",
    exceptions.NotAuthenticated: "not_authenticated",
    exceptions.AuthenticationFailed: "not_authenticated",
    exceptions.PermissionDenied: "permission_denied",
    exceptions.NotFound: "not_found",
    exceptions.MethodNotAllowed: "method_not_allowed",
    exceptions.Throttled: "rate_limited",
    IntegrityError: "conflict",
}


def _request_id_from(context: dict[str, Any]) -> str:
    request = context.get("request")
    rid = getattr(request, "request_id", None)
    return str(rid) if rid else str(uuid.uuid4())


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Map any exception to the canonical error envelope, logging internals safely."""
    request_id = _request_id_from(context)

    # Translate framework exceptions DRF understands before mapping.
    if isinstance(exc, Http404):
        exc = exceptions.NotFound(*(exc.args if exc.args else ("Not found.",)))
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    for exc_type, code in CODE_MAP.items():
        if isinstance(exc, exc_type):
            if isinstance(exc, DjangoValidationError):
                exc = exceptions.ValidationError(exc.messages if exc.messages else str(exc))
            # Custom codes set at raise-time (e.g. "account_inactive") win.
            if getattr(exc, "default_code", None) == "account_inactive":
                code = "account_inactive"
            response = exception_handler(exc, context)
            if response is None:
                response = Response(status=HTTP_BAD_REQUEST)
            return _envelope(response, code=code, exc=exc, request_id=request_id)

    logger.exception(
        "Unhandled internal error (request_id=%s) %s",
        request_id,
        type(exc).__name__,
        exc_info=exc,
    )
    return _envelope(
        Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR),
        code="internal_error",
        exc=exc,
        request_id=request_id,
        message="Internal server error",
    )


def _envelope(
    response: Response,
    *,
    code: str,
    exc: Exception,
    request_id: str,
    message: str | None = None,
) -> Response:
    """Rewrite the DRF default body into the envelope shape."""
    default_detail = getattr(exc, "detail", None) or getattr(exc, "default_detail", None)
    details: Any = response.data
    human = message
    if human is None and isinstance(default_detail, str) and default_detail:
        human = default_detail

    if code == "rate_limited" and isinstance(exc, exceptions.Throttled):
        wait = getattr(exc, "wait", None)
        human = f"Request was throttled. Try again in {wait} seconds."
        details = {"retry_after": wait if wait else None}

    response.data = {
        "error": {
            "code": code,
            "message": human if human is not None else "Request failed",
            "details": details if details is not None else {},
            "request_id": request_id,
        }
    }
    return response
