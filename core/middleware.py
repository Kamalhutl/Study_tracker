"""RequestIDMiddleware: X-Request-ID in, response header out, contextvar for logs."""

from logging import getLogger
from typing import Any

from django.http import HttpRequest, HttpResponse

from .logging import set_request_id

logger = getLogger("study_tracker.request_id")

HEADER = "X-Request-ID"


class RequestIDMiddleware:
    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(HEADER, "")
        request_id = set_request_id(incoming or None)
        request.request_id = request_id  # type: ignore[attr-defined]

        try:
            response: HttpResponse = self.get_response(request)
        except Exception:
            raise

        response[HEADER] = request_id
        return response
