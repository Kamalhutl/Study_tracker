"""Extra profile/auth coverage: superuser creation, admin registration, age."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Category, Role
from tests.factories import UserFactory

User = get_user_model()


def test_create_superuser_forces_admin_role_and_permissions():
    admin = User.objects.create_superuser("boss@example.com", "str0ng-Password!")
    assert admin.is_superuser is True
    assert admin.is_staff is True
    assert admin.role == Role.ADMIN
    assert admin.is_admin_role


def test_create_user_requires_email():
    with pytest.raises(ValueError, match="email must be set"):
        User.objects.create_user(email="", password="x")
    with pytest.raises((ValueError, TypeError)):
        User.objects.create_user(email=None, password="x")


def test_age_computed_from_dob():
    from datetime import date

    from freezegun import freeze_time

    user = UserFactory(dob=date(1996, 6, 15))
    with freeze_time("2026-08-19"):
        assert user.age == 30


def test_age_none_when_no_dob(user):
    assert user.age is None


def test_admin_user_factory_is_staff(admin_user):
    assert admin_user.is_superuser is True
    assert admin_user.is_staff is True
    assert admin_user.role == "admin"


def test_category_choices():
    assert Category.GENERAL == "GEN"


def test_custom_min_length_validator_help_text():
    from django.core.exceptions import ValidationError

    from apps.accounts.validators import MinimumLengthValidator

    validator = MinimumLengthValidator()
    assert "10" in validator.get_help_text()
    with pytest.raises(ValidationError):
        validator.validate("short")


def test_negative_experience_rejected_at_model_level():
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        user = UserFactory(years_of_experience="-1.0")
        user.refresh_from_db()


def test_register_against_usernameless_login_flow(api_client: APIClient):
    """Register then immediately login to prove the full loop end-to-end."""
    reg = api_client.post(
        "/api/v1/auth/register/",
        {
            "email": "E2E.User@Example.com",
            "password": "str0ng-Password!",
            "password2": "str0ng-Password!",
        },
    )
    assert reg.status_code == status.HTTP_201_CREATED
    login = api_client.post(
        "/api/v1/auth/login/",
        {"email": "e2e.user@example.com", "password": "str0ng-Password!"},
    )
    assert login.status_code == status.HTTP_200_OK
