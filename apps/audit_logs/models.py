from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel, UUIDModel


class Source(models.TextChoices):
    ADMIN = "ADMIN", _("Admin")
    API = "API", _("API")
    SYSTEM = "SYSTEM", _("System")
    CELERY = "CELERY", _("Celery")
    MANAGEMENT_COMMAND = "MANAGEMENT_COMMAND", _("Management command")


class AuditLog(UUIDModel, TimeStampedModel):
    """Immutable audit trail. Trust backbone — every later step writes here."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        help_text="Null = system/Celery actor.",
    )
    actor_label = models.CharField(
        max_length=160,
        blank=True,
        help_text='Denormalized "email (role)" so history survives user deletion.',
    )
    action = models.CharField(max_length=64, db_index=True)
    app_label = models.CharField(max_length=64, blank=True)
    model_name = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(
        max_length=255, blank=True, db_index=True, help_text="Stringified PK (UUID-friendly)."
    )
    object_repr = models.CharField(max_length=240, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    changed_fields = models.JSONField(default=list)
    source = models.CharField(max_length=24, choices=Source.choices, default=Source.SYSTEM)
    ip = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["app_label", "model_name", "object_id"]),
            models.Index(fields=["action", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.object_repr} [{self.source}]"
