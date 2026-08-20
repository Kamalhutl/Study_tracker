"""Liveness & readiness endpoints (AllowAny + throttle-exempt)."""

import logging

from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

logger = logging.getLogger("study_tracker.health")


@extend_schema(
    request=None,
    responses={200: OpenApiResponse(description="Liveness: process is up")},
    tags=["health"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])
def healthz(request: Request) -> Response:
    """Liveness: the process is up. No dependencies touched."""
    return Response({"status": "ok"})


@extend_schema(
    request=None,
    responses={200: OpenApiResponse(description="Readiness: DB + Redis healthy")},
    tags=["health"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])
def readyz(request: Request) -> Response:
    """Readiness: DB responds to SELECT 1 and Redis pings. 503 if either fails."""
    checks: dict[str, str] = {}
    healthy = True

    # DB
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:
        logger.exception("readyz database check failed")
        checks["database"] = "unavailable"
        healthy = False

    # Redis
    try:
        cache.set("__readyz_ping__", 1, timeout=5)
        cache.get("__readyz_ping__")
        checks["redis"] = "ok"
    except Exception:
        logger.exception("readyz redis check failed")
        checks["redis"] = "unavailable"
        healthy = False

    status_code = 200 if healthy else 503
    return Response(
        {"status": "ok" if healthy else "unavailable", "checks": checks}, status=status_code
    )
