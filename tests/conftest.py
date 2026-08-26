import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import User
from tests.factories import AdminUserFactory, UserFactory


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
