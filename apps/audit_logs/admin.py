from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Fully read-only: the audit trail may never be edited from Django admin."""

    list_display = (
        "created_at",
        "action",
        "actor_label",
        "object_repr",
        "source",
        "request_id",
    )
    list_select_related = ("actor",)
    list_filter = ("action", "source", "created_at")
    search_fields = ("actor_label", "object_repr", "object_id")
    date_hierarchy = "created_at"
    readonly_fields = [field.name for field in AuditLog._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
