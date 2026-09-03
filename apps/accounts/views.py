"""Auth endpoints under /api/v1/auth/."""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.audit_logs.services import record

from .models import User
from .serializers import (
    CustomTokenObtainPairSerializer,
    FcmTokenSerializer,
    PasswordChangeSerializer,
    RegisterSerializer,
    RotatingRefreshSerializer,
    UserMeSerializer,
)


def _auth_user(request: Request) -> User:
    user = request.user
    assert isinstance(user, User)
    return user


@extend_schema(
    request=RegisterSerializer,
    responses={201: UserMeSerializer},
    tags=["auth"],
)
class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        record(
            "user.registered",
            actor=user,
            instance=user,
            source="API",
            request=request,
        )
        return Response(UserMeSerializer(user).data, status=status.HTTP_201_CREATED)


@extend_schema(
    request=CustomTokenObtainPairSerializer,
    responses={200: CustomTokenObtainPairSerializer},
    tags=["auth"],
)
class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer  # type: ignore[assignment]
    permission_classes = [AllowAny]  # type: ignore[assignment]
    throttle_scope = "auth"


@extend_schema(
    request=CustomTokenObtainPairSerializer,
    responses={200: CustomTokenObtainPairSerializer},
    tags=["auth"],
)
class RefreshView(TokenRefreshView):
    serializer_class = RotatingRefreshSerializer  # type: ignore[assignment]
    throttle_scope = "auth"


@extend_schema(
    request=None,
    responses={
        205: OpenApiResponse(description="Refresh token blacklisted"),
        400: OpenApiResponse(description="Invalid or expired refresh token"),
    },
    tags=["auth"],
)
class LogoutView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request: Request) -> Response:
        refresh = request.data.get("refresh")  # type: ignore[union-attr]
        if not refresh:
            return _invalid_token(request)
        try:
            token = RefreshToken(refresh)
        except Exception:
            return _invalid_token(request)
        token.blacklist()
        return Response(status=status.HTTP_205_RESET_CONTENT)


@extend_schema(
    request=None,
    responses={200: UserMeSerializer, 401: OpenApiResponse(description="Not authenticated")},
    tags=["auth"],
)
class MeView(APIView):
    def get(self, request: Request) -> Response:
        return Response(UserMeSerializer(_auth_user(request)).data)

    def patch(self, request: Request) -> Response:
        user = _auth_user(request)
        serializer = UserMeSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        record(
            "user.profile.updated",
            actor=user,
            instance=user,
            before={},
            after=serializer.data,
            source="API",
            request=request,
        )
        return Response(UserMeSerializer(user).data)


@extend_schema(
    request=PasswordChangeSerializer,
    responses={
        204: OpenApiResponse(description="Password changed, all tokens blacklisted"),
        400: OpenApiResponse(description="Validation error"),
    },
    tags=["auth"],
)
class PasswordChangeView(APIView):
    def post(self, request: Request) -> Response:
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = _auth_user(request)
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        _blacklist_user_tokens(user)
        record(
            "user.password.changed",
            actor=user,
            instance=user,
            source="API",
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    request=FcmTokenSerializer,
    responses={200: FcmTokenSerializer},
    tags=["auth"],
)
class FirebaseTokenView(APIView):
    def post(self, request: Request) -> Response:
        serializer = FcmTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _auth_user(request)
        changed = user.fcm_token != serializer.validated_data["fcm_token"]
        if changed:
            user.fcm_token = serializer.validated_data["fcm_token"]
            user.save(update_fields=["fcm_token"])
            record(
                "user.firebase_token.updated",
                actor=user,
                instance=user,
                source="API",
                request=request,
            )
        return Response({"fcm_token": user.fcm_token})


def _blacklist_user_tokens(user: User) -> None:
    """Blacklist every outstanding refresh token for ``user`` in two queries."""
    from django.utils import timezone
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    outstanding = OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True)
    if not outstanding.exists():
        return
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token, blacklisted_at=timezone.now()) for token in outstanding],
        ignore_conflicts=True,
    )


def _invalid_token(request: Request) -> Response:
    from core.logging import get_request_id

    return Response(
        {
            "error": {
                "code": "invalid_token",
                "message": "Invalid or expired refresh token.",
                "details": {},
                "request_id": get_request_id(),
            }
        },
        status=status.HTTP_400_BAD_REQUEST,
    )
