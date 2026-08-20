from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone

from apps.audit_logs.services import record

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):  # type: ignore[type-arg]
    ordering = ["-created_at"]
    list_display = ("email", "full_name", "role", "is_active", "email_verified_at", "created_at")
    list_filter = ("role", "is_active", "category", "state")
    search_fields = ("email", "phone", "full_name")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "last_login",
        "last_login_ip",
        "is_superuser",
    )
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Identity",
            {"fields": ("email", "phone", "full_name", "password")},
        ),
        (
            "Profile",
            {
                "fields": (
                    "dob",
                    "education",
                    "category",
                    "state",
                    "years_of_experience",
                    "fcm_token",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "role",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "email_verified_at",
                    "last_login",
                    "last_login_ip",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "phone", "full_name", "password1", "password2"),
            },
        ),
    )

    actions = ("deactivate_users", "mark_email_verified")

    @admin.action(description="Deactivate selected users")
    def deactivate_users(self, request: HttpRequest, queryset: QuerySet[User]) -> None:
        count = 0
        for user in queryset:
            if user.is_active:
                before = {"is_active": True}
                user.is_active = False
                user.save(update_fields=["is_active"])
                record(
                    "user.deactivated",
                    actor=request.user,
                    instance=user,
                    before=before,
                    after={"is_active": False},
                    source="ADMIN",
                    request=request,
                )
                count += 1
        self.message_user(request, f"{count} user(s) deactivated.")

    @admin.action(description="Mark email verified")
    def mark_email_verified(self, request: HttpRequest, queryset: QuerySet[User]) -> None:
        count = 0
        now = timezone.now()
        for user in queryset:
            if user.email_verified_at is None:
                before = {"email_verified_at": None}
                user.email_verified_at = now
                user.save(update_fields=["email_verified_at"])
                record(
                    "user.email_verified",
                    actor=request.user,
                    instance=user,
                    before=before,
                    after={"email_verified_at": now.isoformat()},
                    source="ADMIN",
                    request=request,
                )
                count += 1
        self.message_user(request, f"{count} user(s) marked email verified.")


admin.site.unregister(Group)
