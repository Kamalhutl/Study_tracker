import socket

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import User
from tests.factories import AdminUserFactory, UserFactory

_ORIGINAL_SOCKET = socket.socket


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """Raise on ANY outbound network call during tests (Prompt 2 ground rule 1)."""

    class BlockedSocket(_ORIGINAL_SOCKET):
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "Network access is blocked during tests — this suite must run fully offline."
            )

        def __enter__(self):
            raise AssertionError("Network access is blocked during tests.")

        def __exit__(self, *args):
            raise AssertionError("Network access is blocked during tests.")

    monkeypatch.setattr(socket, "socket", BlockedSocket)
    yield


@pytest.fixture(autouse=True)
def _enable_db(db):
    """Every test in this suite is a DB test (enable the pytest-django db)."""
    return db


@pytest.fixture(autouse=True)
def _flush_cache():
    """Throttle + lock state must never leak between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user() -> User:
    return UserFactory()  # type: ignore[return-value]


@pytest.fixture
def admin_user() -> User:
    return AdminUserFactory()  # type: ignore[return-value]


@pytest.fixture
def auth_client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def admin_auth_client(admin_user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client
