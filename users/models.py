import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _

from config.models import SoftDeleteMixin, TimeStampedMixin
from users.services import UserManager


class User(
    TimeStampedMixin,
    SoftDeleteMixin,
    AbstractBaseUser,
    PermissionsMixin,
):
    # UUID primary keys avoid leaking user counts and make ids unguessable.
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID"),
    )

    username = models.CharField(
        max_length=150,
        unique=True,
        verbose_name=_("Username"),
    )

    email = models.EmailField(
        unique=True,
        verbose_name=_("Email"),
    )

    email_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Email Verified At"),
    )

    first_name = models.CharField(
        max_length=150,
        blank=True,
        verbose_name=_("First Name"),
    )

    last_name = models.CharField(
        max_length=150,
        blank=True,
        verbose_name=_("Last Name"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
    )

    is_staff = models.BooleanField(
        default=False,
        verbose_name=_("Staff"),
    )

    objects = UserManager()

    USERNAME_FIELD = "username"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email"]

    def save(self, *args, **kwargs):
        # Keep emails/usernames normalised no matter which code path writes
        # them (registration, admin forms, scripts).
        if self.email:
            self.email = self.email.strip().lower()
        if self.username:
            self.username = self.normalize_username(self.username)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name or self.username

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def tier(self) -> str:
        """Live plan tier, read from the database (never from the JWT claim)."""
        from subscriptions.services import get_user_tier

        return get_user_tier(self)

    @property
    def subscription(self):
        """Current live subscription, or ``None``."""
        from subscriptions.services import get_live_subscription

        return get_live_subscription(self)

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        ordering = ("-created_at",)

        default_manager_name = "objects"

        indexes = (
            models.Index(fields=["created_at"], name="user_created_at_idx"),
            models.Index(fields=["deleted_at"], name="user_deleted_at_idx"),
        )
