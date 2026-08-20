from typing import Any

from django.contrib.auth.models import Permission  # noqa: F401
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def _log_migrations(sender: Any, **kwargs: Any) -> None:  # pragma: no cover - wiring placeholder
    """Hook point for future signals (e.g. welcome emails, login audit)."""
    return None
