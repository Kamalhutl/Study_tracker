from typing import ClassVar

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel, UUIDModel

from .managers import UserManager

E164_VALIDATOR = RegexValidator(
    regex=r"^\+[1-9]\d{1,14}$",
    message=_("Enter a valid E.164 phone number, e.g. +919876543210."),
)


class Role(models.TextChoices):
    ADMIN = "admin", _("Admin")
    USER = "user", _("User")


class Category(models.TextChoices):
    GENERAL = "GEN", _("General")
    OBC = "OBC", _("OBC")
    SC = "SC", _("SC")
    ST = "ST", _("ST")
    EWS = "EWS", _("EWS")


class User(UUIDModel, AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Application user — email is the login handle, no username."""

    email = models.EmailField(
        _("email address"),
        unique=True,
        error_messages={"unique": _("A user with that email already exists.")},
    )
    phone = models.CharField(
        max_length=15, unique=True, null=True, blank=True, validators=[E164_VALIDATOR]
    )
    full_name = models.CharField(_("full name"), max_length=120, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.USER, db_index=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    # Profile fields used by the eligibility checker (STEP 18).
    dob = models.DateField(null=True, blank=True)
    education = models.CharField(max_length=80, blank=True)
    category = models.CharField(max_length=8, choices=Category.choices, blank=True)
    state = models.CharField(max_length=80, blank=True)
    years_of_experience = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)

    # STEP 20: move to Device model if multi-device needed
    fcm_token = models.CharField(max_length=255, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["role"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(years_of_experience__isnull=True)
                | models.Q(years_of_experience__gte=0),
                name="years_of_experience_non_negative",
            ),
            models.UniqueConstraint(
                Lower("email"),
                name="user_email_ci_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.email

    @property
    def is_admin_role(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def age(self) -> int | None:
        """Age in whole years, None when dob missing or in the future."""
        if not self.dob:
            return None
        today = timezone.localdate()
        years = today.year - self.dob.year
        if (today.month, today.day) < (self.dob.month, self.dob.day):
            years -= 1
        return years if years >= 0 else None

    @property
    def actor_label(self) -> str:
        return f"{self.email} ({self.role})"
