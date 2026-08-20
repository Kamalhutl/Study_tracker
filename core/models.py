"""Shared abstract models: timestamps, UUID PKs, soft deletes."""

import uuid

from django.db import models
from django.db.models.manager import BaseManager


class TimeStampedModel(models.Model):
    """Adds ``created_at`` / ``updated_at`` timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """UUID primary key, never exposed to clients as a plain int."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):  # type: ignore[type-arg]
    def hard_delete(self) -> tuple[int, dict[str, int]]:
        return super().delete()

    def delete(self) -> int:  # type: ignore[override]
        from django.utils import timezone

        return self.update(
            is_deleted=True,
            deleted_at=timezone.now(),
        )

    def alive(self) -> "SoftDeleteQuerySet":
        return self.filter(is_deleted=False)

    def deleted(self) -> "SoftDeleteQuerySet":
        return self.filter(is_deleted=True)


class SoftDeleteManager(BaseManager.from_queryset(SoftDeleteQuerySet)):  # type: ignore[misc]
    """Default manager hiding soft-deleted rows."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return super().get_queryset().alive().order_by("-created_at")  # type: ignore[no-any-return]


class AllObjectsManager(BaseManager.from_queryset(SoftDeleteQuerySet)):  # type: ignore[misc]
    """Manager returning every row, soft-deleted or not."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self.model, using=self._db)


class SoftDeleteModel(models.Model):
    """Soft-delete support: ``.delete()`` marks ``is_deleted`` instead of removing rows."""

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def delete(  # type: ignore[override]
        self, using: str | None = None, keep_parents: bool = False
    ) -> None:
        from django.utils import timezone

        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["is_deleted", "deleted_at", "updated_at"])

    def hard_delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        return super().delete(using=using, keep_parents=keep_parents)
