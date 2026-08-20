"""Custom password validators."""

from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class MinimumLengthValidator:
    """Requires at least 10 characters (stricter than Django's default 8)."""

    def __init__(self, min_length: int = 10) -> None:
        self.min_length = min_length

    def validate(self, password: str, user: Any | None = None) -> None:
        if len(password) < self.min_length:
            raise ValidationError(
                _("This password must contain at least %(min_length)d characters."),
                code="password_too_short",
                params={"min_length": self.min_length},
            )

    def get_help_text(self) -> str:
        return _("Your password must contain at least {min_length} characters.").format(
            min_length=self.min_length
        )
