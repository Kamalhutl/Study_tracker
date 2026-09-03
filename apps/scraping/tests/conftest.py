import pytest

from apps.accounts.models import User
from tests.factories import UserFactory


@pytest.fixture
def user(db) -> User:
    return UserFactory()
