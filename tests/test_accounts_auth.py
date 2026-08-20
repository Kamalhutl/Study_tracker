from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.audit_logs.models import AuditLog

User = get_user_model()

REGISTER_URL = "/api/v1/auth/register/"
LOGIN_URL = "/api/v1/auth/login/"
REFRESH_URL = "/api/v1/auth/refresh/"
LOGOUT_URL = "/api/v1/auth/logout/"
ME_URL = "/api/v1/auth/me/"
PASSWORD_CHANGE_URL = "/api/v1/auth/password/change/"
FIREBASE_URL = "/api/v1/auth/firebase-token/"


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------
def test_register_happy_path(api_client: APIClient):
    response = api_client.post(
        REGISTER_URL,
        {
            "email": "Fresh.User@Example.com",
            "password": "str0ng-Password!",
            "password2": "str0ng-Password!",
            "full_name": "Fresh User",
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    body = response.data
    assert body["email"] == "fresh.user@example.com"  # normalized lowercase
    assert body["role"] == "user"
    assert "password" not in body
    assert "refresh" not in body and "access" not in body
    assert User.objects.filter(email="fresh.user@example.com").exists()

    log = AuditLog.objects.filter(action="user.registered").first()
    assert log is not None
    actor = log.actor
    assert actor is not None
    assert actor.email == "fresh.user@example.com"
    assert log.source == "API"


def test_register_duplicate_email(api_client: APIClient, user):
    response = api_client.post(
        REGISTER_URL,
        {
            "email": user.email,
            "password": "str0ng-Password!",
            "password2": "str0ng-Password!",
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "validation_error"


def test_register_duplicate_email_different_case(api_client: APIClient, user):
    response = api_client.post(
        REGISTER_URL,
        {
            "email": user.email.upper(),
            "password": "str0ng-Password!",
            "password2": "str0ng-Password!",
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "validation_error"


def test_register_weak_password(api_client: APIClient):
    response = api_client.post(
        REGISTER_URL,
        {"email": "weak@example.com", "password": "123", "password2": "123"},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    body = response.data["error"]
    assert body["code"] == "validation_error"
    assert "password" in body["details"]
    assert User.objects.filter(email="weak@example.com").exists() is False


def test_register_password_mismatch(api_client: APIClient):
    response = api_client.post(
        REGISTER_URL,
        {
            "email": "mismatch@example.com",
            "password": "str0ng-Password!",
            "password2": "str0ng-Password?",
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------
def test_login_happy_path_returns_tokens_and_role_claim(api_client: APIClient, user):
    response = api_client.post(LOGIN_URL, {"email": user.email, "password": "str0ng-Password!"})
    assert response.status_code == status.HTTP_200_OK
    data = response.data
    assert "access" in data and "refresh" in data

    access = AccessToken(data["access"])
    assert access["role"] == user.role
    assert access["email"] == user.email

    user.refresh_from_db()
    assert user.last_login is not None
    assert user.last_login_ip == "127.0.0.1"


def test_login_wrong_password_401(api_client: APIClient, user):
    response = api_client.post(LOGIN_URL, {"email": user.email, "password": "wrong-pass-123"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.data["error"]["code"] == "not_authenticated"


def test_login_inactive_user_401_account_inactive(api_client: APIClient, user):
    user.is_active = False
    user.save(update_fields=["is_active"])
    response = api_client.post(LOGIN_URL, {"email": user.email, "password": "str0ng-Password!"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.data["error"]["code"] == "account_inactive"


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------
def test_refresh_rotates_and_blacklists_old(api_client: APIClient, user):
    login = api_client.post(LOGIN_URL, {"email": user.email, "password": "str0ng-Password!"})
    old_refresh = login.data["refresh"]

    response = api_client.post(REFRESH_URL, {"refresh": old_refresh})
    assert response.status_code == status.HTTP_200_OK
    new_refresh = response.data["refresh"]
    assert new_refresh != old_refresh

    # Old refresh is blacklisted -> unusable.
    second = api_client.post(REFRESH_URL, {"refresh": old_refresh})
    assert second.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# logout
# ---------------------------------------------------------------------------
def test_logout_blacklists_refresh(api_client: APIClient, user):
    login = api_client.post(LOGIN_URL, {"email": user.email, "password": "str0ng-Password!"})
    refresh = login.data["refresh"]

    response = api_client.post(LOGOUT_URL, {"refresh": refresh})
    assert response.status_code == status.HTTP_205_RESET_CONTENT

    reuse = api_client.post(REFRESH_URL, {"refresh": refresh})
    assert reuse.status_code == status.HTTP_401_UNAUTHORIZED


def test_logout_invalid_token(api_client: APIClient):
    response = api_client.post(LOGOUT_URL, {"refresh": "not-a-token"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "invalid_token"


# ---------------------------------------------------------------------------
# me (auth requirement on everything)
# ---------------------------------------------------------------------------
def test_me_unauthenticated_401(api_client: APIClient):
    response = api_client.get(ME_URL)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.data["error"]["code"] == "not_authenticated"


def test_me_returns_own_data(auth_client: APIClient, user):
    response = auth_client.get(ME_URL)
    assert response.status_code == status.HTTP_200_OK
    body = response.data
    assert body["email"] == user.email
    assert body["id"] == str(user.id)
    assert "password" not in body


def test_me_patch_rejects_role_escalation(auth_client: APIClient, user):
    response = auth_client.patch(ME_URL, {"role": "admin", "is_staff": True, "full_name": "Hax"})
    assert response.status_code == status.HTTP_200_OK
    body = response.data
    user.refresh_from_db()
    assert user.role == "user"
    assert user.is_staff is False
    assert body["role"] == "user"
    assert body["full_name"] == "Hax"


def test_me_patch_updates_profile(auth_client: APIClient, user):
    payload = {
        "full_name": "New Name",
        "phone": "+919812345678",
        "education": "B.Tech",
        "state": "MH",
        "years_of_experience": "2.5",
    }
    response = auth_client.patch(ME_URL, payload)
    assert response.status_code == status.HTTP_200_OK
    body = response.data
    assert body["full_name"] == "New Name"
    assert body["education"] == "B.Tech"
    assert body["years_of_experience"] == "2.5"
    user.refresh_from_db()
    assert user.years_of_experience == 2.5


# ---------------------------------------------------------------------------
# password change
# ---------------------------------------------------------------------------
def test_password_change_wrong_old_password_400(auth_client: APIClient, user):
    response = auth_client.post(
        PASSWORD_CHANGE_URL,
        {
            "old_password": "nope",
            "new_password": "new-strong-Pass1",
            "new_password2": "new-strong-Pass1",
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "validation_error"


def test_password_change_success_blacklists_refresh_tokens(api_client: APIClient, user):
    login = api_client.post(LOGIN_URL, {"email": user.email, "password": "str0ng-Password!"})
    assert login.status_code == status.HTTP_200_OK
    old_refresh = login.data["refresh"]
    access = login.data["access"]

    auth_client = APIClient()
    auth_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    response = auth_client.post(
        PASSWORD_CHANGE_URL,
        {
            "old_password": "str0ng-Password!",
            "new_password": "brand-new-Pass9",
            "new_password2": "brand-new-Pass9",
        },
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT

    user.refresh_from_db()
    assert user.check_password("brand-new-Pass9")

    reuse = api_client.post(REFRESH_URL, {"refresh": old_refresh})
    assert reuse.status_code == status.HTTP_401_UNAUTHORIZED


def test_password_change_blacklists_rotated_refresh(api_client: APIClient, user):
    login = api_client.post(LOGIN_URL, {"email": user.email, "password": "str0ng-Password!"})
    assert login.status_code == status.HTTP_200_OK
    rotated = api_client.post(REFRESH_URL, {"refresh": login.data["refresh"]})
    assert rotated.status_code == status.HTTP_200_OK

    auth_client = APIClient()
    auth_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    response = auth_client.post(
        PASSWORD_CHANGE_URL,
        {
            "old_password": "str0ng-Password!",
            "new_password": "brand-new-Pass9",
            "new_password2": "brand-new-Pass9",
        },
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT

    reuse = api_client.post(REFRESH_URL, {"refresh": rotated.data["refresh"]})
    assert reuse.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# firebase token
# ---------------------------------------------------------------------------
def test_firebase_token_upsert_idempotent(auth_client: APIClient, user):
    first = auth_client.post(FIREBASE_URL, {"fcm_token": "tok-ABC"})
    assert first.status_code == status.HTTP_200_OK
    assert first.data["fcm_token"] == "tok-ABC"
    user.refresh_from_db()
    assert user.fcm_token == "tok-ABC"

    second = auth_client.post(FIREBASE_URL, {"fcm_token": "tok-ABC"})
    assert second.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# throttling
# ---------------------------------------------------------------------------
def test_auth_throttle_429_after_10(api_client: APIClient, user):
    for _ in range(10):
        response = api_client.post(LOGIN_URL, {"email": user.email, "password": "str0ng-Password!"})
        assert response.status_code == status.HTTP_200_OK

    eleventh = api_client.post(LOGIN_URL, {"email": user.email, "password": "str0ng-Password!"})
    assert eleventh.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    body = eleventh.data["error"]
    assert body["code"] == "rate_limited"
    assert "retry_after" in body["details"]
