"""Celery wiring, exception envelope, pagination, middleware, permissions,
soft-delete, env() helper."""

import uuid

import pytest
from django.core.paginator import Paginator
from django.db import connection
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from core.pagination import CursorAwarePageNumberPagination
from tests.factories import UserFactory


# ---------------------------------------------------------------------------
# celery wiring
# ---------------------------------------------------------------------------
def test_ping_task_eager_returns_pong():
    from core.tasks import ping

    assert ping.delay().get() == "pong"


def test_celery_declared_queues():
    from django.conf import settings

    names = {q.name for q in settings.CELERY_QUEUES}
    assert names == {"default", "scraping", "scraping_browser", "notifications"}
    assert settings.CELERY_TASK_ROUTES == {
        "apps.scraping.*": {"queue": "scraping"},
        "apps.career_detection.*": {"queue": "scraping"},
        "apps.notifications.*": {"queue": "notifications"},
    }


# ---------------------------------------------------------------------------
# exception envelope
# ---------------------------------------------------------------------------
def test_unhandled_exception_envelope_never_leaks():
    from core import exceptions as core_exceptions

    request = APIRequestFactory().get("/boom")
    request.request_id = str(uuid.uuid4())
    response = core_exceptions.api_exception_handler(
        RuntimeError("sensitive internals: DB_PASSWORD=sekret"), {"request": request}
    )
    assert response is not None
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    body = response.data["error"]
    assert body["code"] == "internal_error"
    assert "DB_PASSWORD" not in body["message"]
    assert body["request_id"] == request.request_id


@pytest.mark.parametrize(
    ("exc", "expected_code", "expected_status"),
    [
        (exceptions.ValidationError({"email": ["bad"]}), "validation_error", 400),
        (exceptions.NotAuthenticated(), "not_authenticated", 401),
        (exceptions.PermissionDenied(), "permission_denied", 403),
        (exceptions.NotFound(), "not_found", 404),
        (exceptions.MethodNotAllowed("POST"), "method_not_allowed", 405),
        (exceptions.Throttled(wait=7), "rate_limited", 429),
        (Http404(), "not_found", 404),
    ],
)
def test_exception_mapping(exc, expected_code, expected_status):
    from core import exceptions as core_exceptions

    request = APIRequestFactory().get("/x")
    request.request_id = str(uuid.uuid4())
    response = core_exceptions.api_exception_handler(exc, {"request": request})
    assert response is not None
    assert response.status_code == expected_status
    error = response.data["error"]
    assert error["code"] == expected_code
    assert error["request_id"] == request.request_id


def test_throttled_envelope_has_retry_after():
    from core import exceptions as core_exceptions

    request = APIRequestFactory().get("/x")
    request.request_id = "trid"
    response = core_exceptions.api_exception_handler(
        exceptions.Throttled(wait=12), {"request": request}
    )
    assert response is not None
    assert response.data["error"]["details"]["retry_after"] == 12


def test_integrity_error_maps_to_conflict():
    from django.db import IntegrityError

    from core import exceptions as core_exceptions

    request = APIRequestFactory().get("/x")
    request.request_id = "rid-1"
    response = core_exceptions.api_exception_handler(
        IntegrityError("duplicate key"), {"request": request}
    )
    assert response is not None
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "conflict"


def test_django_validation_error_maps():
    from django.core.exceptions import ValidationError

    from core import exceptions as core_exceptions

    request = APIRequestFactory().get("/x")
    request.request_id = "rid-2"
    response = core_exceptions.api_exception_handler(
        ValidationError(["some problem"]), {"request": request}
    )
    assert response is not None
    assert response.data["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------
def test_pagination_shape_with_page_size_query_param():
    users = UserFactory.create_batch(5)

    request = Request(APIRequestFactory().get("/users", {"page": 2, "page_size": 2}))
    paginator = CursorAwarePageNumberPagination()
    paginator.request = request
    paginator.page = Paginator(users, 2).page(2)
    body = paginator.get_paginated_response([{"email": u.email} for u in users[2:4]]).data
    assert set(body.keys()) == {"count", "next", "previous", "results"}
    assert body["count"] == 5
    assert body["next"] is not None and body["previous"] is not None
    assert len(body["results"]) == 2


def test_pagination_config_contract():
    paginator = CursorAwarePageNumberPagination()
    assert paginator.page_size == 20
    assert paginator.page_size_query_param == "page_size"
    assert paginator.max_page_size == 100


# ---------------------------------------------------------------------------
# middleware: request id
# ---------------------------------------------------------------------------
def test_request_id_middleware_echoes_client_header():
    from django.test import Client

    response = Client().get("/healthz", HTTP_X_REQUEST_ID="client-sent-id")
    assert response["X-Request-ID"] == "client-sent-id"


def test_request_id_generated_when_missing():
    from django.test import Client

    response = Client().get("/healthz")
    assert uuid.UUID(response["X-Request-ID"])  # parses -> real uuid4


# ---------------------------------------------------------------------------
# permissions
# ---------------------------------------------------------------------------
class _FakeView(APIView):
    permission_classes = []


def _request_with(user, method="GET"):
    factory = APIRequestFactory()
    request = factory.post("/x") if method == "POST" else factory.get("/x")
    request.user = user
    return request


def test_is_admin_role_denies_regular_user(user):
    from core.permissions import IsAdminRole

    assert IsAdminRole().has_permission(_request_with(user), _FakeView()) is False


def test_is_admin_role_allows_admin(admin_user):
    from core.permissions import IsAdminRole

    assert IsAdminRole().has_permission(_request_with(admin_user), _FakeView()) is True


def test_is_admin_role_denies_anonymous():
    from django.contrib.auth.models import AnonymousUser

    from core.permissions import IsAdminRole

    assert IsAdminRole().has_permission(_request_with(AnonymousUser()), _FakeView()) is False


class OwnerCarrier:
    def __init__(self, user):
        self.user = user


def test_is_owner_safe_methods_allowed(user, admin_user):
    from core.permissions import IsOwner

    assert (
        IsOwner().has_object_permission(_request_with(admin_user), _FakeView(), OwnerCarrier(user))
        is True
    )


def test_is_owner_write_denied_for_other_user(user, admin_user):
    from core.permissions import IsOwner

    assert (
        IsOwner().has_object_permission(
            _request_with(admin_user, "POST"), _FakeView(), OwnerCarrier(user)
        )
        is False
    )


def test_is_owner_write_allowed_for_owner(user):
    from core.permissions import IsOwner

    assert (
        IsOwner().has_object_permission(
            _request_with(user, "POST"), _FakeView(), OwnerCarrier(user)
        )
        is True
    )


# ---------------------------------------------------------------------------
# soft delete (DDL for a test-local model; registered once, table dropped after)
# ---------------------------------------------------------------------------
from django.db import models as _models  # noqa: E402

from core.models import SoftDeleteModel, TimeStampedModel, UUIDModel  # noqa: E402


class SoftThing(SoftDeleteModel, TimeStampedModel, UUIDModel):
    name = _models.CharField(max_length=100)

    class Meta:
        app_label = "core"


def _make_soft_model():
    tables = connection.introspection.table_names()
    with connection.schema_editor() as editor:
        if SoftThing._meta.db_table in tables:  # leftover from an aborted run
            editor.delete_model(SoftThing)
        editor.create_model(SoftThing)
    return SoftThing


def _drop_soft_model(model):
    if model._meta.db_table not in connection.introspection.table_names():
        return
    with connection.schema_editor() as editor:
        editor.delete_model(model)


@pytest.mark.django_db(transaction=True)
def test_soft_delete_flow():
    SoftThing = _make_soft_model()
    try:
        obj = SoftThing.objects.create(name="alpha")
        assert obj.is_deleted is False

        obj.delete()  # soft
        obj.refresh_from_db()
        assert obj.is_deleted is True
        assert obj.deleted_at is not None
        assert SoftThing.objects.count() == 0
        assert SoftThing.all_objects.count() == 1

        obj.hard_delete()
        assert SoftThing.all_objects.count() == 0
    finally:
        _drop_soft_model(SoftThing)


@pytest.mark.django_db(transaction=True)
def test_queryset_soft_delete_and_hard_delete():
    SoftThing = _make_soft_model()
    try:
        SoftThing.objects.create(name="x")
        SoftThing.objects.create(name="y")

        SoftThing.objects.filter(name="x").delete()
        assert SoftThing.objects.count() == 1
        assert SoftThing.all_objects.filter(is_deleted=True).count() == 1

        SoftThing.all_objects.hard_delete()
        assert SoftThing.all_objects.count() == 0
    finally:
        _drop_soft_model(SoftThing)


# ---------------------------------------------------------------------------
# settings env() helper
# ---------------------------------------------------------------------------
def test_env_helper_uses_default_and_casts(monkeypatch):
    from config.settings import env

    monkeypatch.delenv("ST_TEST_INT", raising=False)
    assert env("ST_TEST_INT", default="42", cast_to=int) == 42
    monkeypatch.setenv("ST_TEST_INT", "7")
    assert env("ST_TEST_INT", default="42", cast_to=int) == 7


def test_env_helper_string_passthrough(monkeypatch):
    from config.settings import env

    monkeypatch.setenv("ST_TEST_STR", "hello")
    assert env("ST_TEST_STR") == "hello"


def test_env_helper_required_missing_raises(monkeypatch):
    from config.settings import env

    monkeypatch.delenv("ST_TEST_REQ", raising=False)
    with pytest.raises(RuntimeError, match="ST_TEST_REQ"):
        env("ST_TEST_REQ", required=True)


def test_env_helper_bad_cast_raises(monkeypatch):
    from config.settings import env

    monkeypatch.setenv("ST_TEST_BAD", "not-an-int")
    with pytest.raises(RuntimeError, match="ST_TEST_BAD"):
        env("ST_TEST_BAD", cast_to=int)
