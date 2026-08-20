from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    FirebaseTokenView,
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    RegisterView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("password/change/", PasswordChangeView.as_view(), name="auth-password-change"),
    path("firebase-token/", FirebaseTokenView.as_view(), name="auth-firebase-token"),
]
