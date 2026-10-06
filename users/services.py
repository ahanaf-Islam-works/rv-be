from typing import Any

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import BaseUserManager
from django.utils.translation import gettext_lazy as _

from config.models import SoftDeleteManager


class UserManager(SoftDeleteManager, BaseUserManager):
    """
    Manager for the custom User model.

    - Inherits SoftDeleteManager, so `User.objects` hides soft-deleted users
      (which also means soft-deleted users cannot authenticate, because
      `get_by_natural_key` goes through `get_queryset`).
    - Inherits BaseUserManager for `normalize_email`, `make_random_password`, etc.
    - Use `User.all_objects` to reach deleted records too.
    """

    use_in_migrations = True

    def _create_user(
        self,
        username: str,
        email: str,
        password: str | None,
        **extra_fields: Any,
    ):
        if not username:
            raise ValueError(_("The username must be set"))
        if not email:
            raise ValueError(_("The email must be set"))

        email = self.normalize_email(email)
        username = self.model.normalize_username(username)

        user = self.model(username=username, email=email, **extra_fields)
        # make_password(None) produces an unusable password
        user.password = make_password(password)
        user.save(using=self._db)
        return user

    def create_user(
        self,
        username: str,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(username, email, password, **extra_fields)

    def create_superuser(
        self,
        username: str,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))

        return self._create_user(username, email, password, **extra_fields)
