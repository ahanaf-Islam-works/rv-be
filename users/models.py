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
    username = models.CharField(
        max_length=150,
        unique=True,
        verbose_name=_("Username"),
    )

    email = models.EmailField(
        unique=True,
        verbose_name=_("Email"),
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

    def __str__(self):
        return self.username

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name or self.username

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        ordering = ("-created_at",)

        default_manager_name = "objects"

        indexes = (
            models.Index(fields=["created_at"], name="user_created_at_idx"),
            models.Index(fields=["deleted_at"], name="user_deleted_at_idx"),
        )
