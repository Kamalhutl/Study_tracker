"""DRF permission classes used across the API."""

from typing import Any

from django.contrib.auth.models import AnonymousUser
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from apps.accounts.models import User


class IsAdminRole(BasePermission):
    """Only users with role=ADMIN (or superusers) get through."""

    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_admin_role)


class IsOwner(BasePermission):
    """Object-level: requester must be the object's owner (has user FK or id match)."""

    def has_object_permission(self, request: Request, view: Any, obj: Any) -> bool:
        if request.method in SAFE_METHODS:
            return True
        user: User | AnonymousUser = request.user
        return getattr(obj, "user", None) == user or (
            isinstance(user, User) and getattr(obj, "id", None) == user.id
        )
