import pytest
from rest_framework import status
from rest_framework.test import APIClient


def test_healthz_always_ok(api_client: APIClient):
    response = api_client.get("/healthz")
    assert response.status_code == status.HTTP_200_OK
    assert response.data == {"status": "ok"}


def test_readyz_ok_when_db_and_redis_up(api_client: APIClient):
    response = api_client.get("/readyz")
    assert response.status_code == status.HTTP_200_OK
    body = response.data
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "ok"


@pytest.mark.parametrize("which", ["db", "redis"])
def test_readyz_503_when_dependency_down(api_client: APIClient, monkeypatch, which):
    from django.core.cache import cache

    from core import health

    monkeypatch.setattr(
        health, "connection", _BrokenConnection() if which == "db" else real_connection()
    )
    if which == "redis":
        monkeypatch.setattr(cache, "set", _boom)
        monkeypatch.setattr(cache, "get", _boom)

    response = api_client.get("/readyz")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    body = response.data
    assert body["status"] == "unavailable"


class _BrokenConnection:
    def __enter__(self):
        raise RuntimeError("db down")

    def __exit__(self, *a):
        return False

    def cursor(self):
        raise RuntimeError("db down")


def real_connection():
    from django.db import connection

    return connection


def _boom(*args: object, **kwargs: object) -> None:
    raise RuntimeError("redis down")
