"""Account serializers — nothing sensitive ever leaves the API."""

from typing import Any

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken, Token

from core.utils import client_ip

from .models import Category, User

READ_ONLY_FIELDS = ("role", "is_staff", "is_superuser", "email_verified_at", "password")


class AccountInactive(AuthenticationFailed):
    """Login attempt on a deactivated account — distinguished error code."""

    default_detail = "Your account is inactive."
    default_code = "account_inactive"


class RegisterSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)
    full_name = serializers.CharField(max_length=120, allow_blank=True, required=False)

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError({"password2": "Passwords do not match."})
        try:
            password_validation.validate_password(attrs["password"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data: dict[str, Any]) -> User:
        validated_data.pop("password2")
        user = User.objects.create_user(**validated_data)
        assert user is not None
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Adds ``role`` + ``email`` claims and tracks login metadata."""

    @classmethod
    def get_token(cls, user: Any) -> Token:
        token = super().get_token(user)
        token["role"] = user.role
        token["email"] = user.email
        return token

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        email = (attrs.get(User.USERNAME_FIELD) or "").strip().lower()
        # Exact lookup hits the lower(email) unique index; iexact falls back
        # for rows created before normalization (e.g. via admin).
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.filter(email__iexact=email).first()
        if user is not None and not user.is_active:
            # default_code="account_inactive" flows through the envelope handler.
            raise AccountInactive()

        data = super().validate(attrs)
        user = self.user

        request = self.context.get("request")
        from django.utils import timezone

        assert self.user is not None
        self.user.last_login = timezone.now()
        if request is not None:
            self.user.last_login_ip = client_ip(request)
        self.user.save(update_fields=["last_login", "last_login_ip"])
        return data


class RotatingRefreshSerializer(TokenRefreshSerializer):
    """Like the stock refresh serializer but reissues the rotated token through
    ``RefreshToken.for_user`` so every rotation-issued refresh gets an
    ``OutstandingToken`` row. Stock simplejwt mutates the old token in place and
    never records the new jti, which silently breaks "blacklist all outstanding
    tokens on password change"."""

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        refresh = RefreshToken(attrs["refresh"])
        data = super().validate(attrs)
        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
        if user_id:
            user = User.objects.get(**{api_settings.USER_ID_FIELD: user_id})
            data["refresh"] = str(RefreshToken.for_user(user))
        return data


class UserMeSerializer(serializers.ModelSerializer[User]):
    role = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    email_verified_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    age = serializers.IntegerField(read_only=True)
    category = serializers.ChoiceField(choices=Category.choices, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "role",
            "dob",
            "age",
            "education",
            "category",
            "state",
            "years_of_experience",
            "email_verified_at",
            "created_at",
        ]
        read_only_fields = READ_ONLY_FIELDS
        extra_kwargs = {
            "phone": {"allow_blank": True},
            "education": {"allow_blank": True},
            "state": {"allow_blank": True},
            "dob": {"allow_null": True},
            "years_of_experience": {"allow_null": True},
        }


class PasswordChangeSerializer(serializers.Serializer[Any]):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    new_password2 = serializers.CharField(write_only=True)

    def validate_old_password(self, value: str) -> str:
        user: User = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["new_password"] != attrs["new_password2"]:
            raise serializers.ValidationError({"new_password2": "New passwords do not match."})
        try:
            password_validation.validate_password(
                attrs["new_password"], self.context["request"].user
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc
        return attrs


class FcmTokenSerializer(serializers.Serializer[Any]):
    fcm_token = serializers.CharField(max_length=255, trim_whitespace=True)

    def validate_fcm_token(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("fcm_token may not be blank.")
        return value
