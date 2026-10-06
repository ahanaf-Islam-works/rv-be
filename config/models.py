from typing import TYPE_CHECKING, Any

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TimeStampedMixin(models.Model):
    """
    Adds created_at and updated_at timestamp fields.
    """

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At"),
        help_text=_("Timestamp when this record was created"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At"),
        help_text=_("Timestamp when this record was last updated"),
    )

    class Meta:
        abstract = True
        indexes = (models.Index(fields=["created_at"]),)


class AuditMixin(models.Model):
    """
    Adds created_by and updated_by audit fields.
    """

    created_by = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Created By"),
        help_text=_("User UUID or identifier who created this record"),
    )
    updated_by = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Updated By"),
        help_text=_("User UUID or identifier who last updated this record"),
    )

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    """
    QuerySet with helpers for soft-deleted records.
    """

    def active(self):
        return self.filter(deleted_at__isnull=True)

    def deleted(self):
        return self.filter(deleted_at__isnull=False)


class SoftDeleteManager(models.Manager):
    """
    Default manager that returns only non-deleted records.
    """

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).active()


class SoftDeleteMixin(models.Model):
    """
    Adds soft-delete behavior to a model.
    """

    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Deleted At"),
        help_text=_("Timestamp when this record was soft-deleted"),
    )
    deleted_by = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Deleted By"),
        help_text=_("User UUID or identifier who soft-deleted this record"),
    )

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
        indexes = (models.Index(fields=["deleted_at"], name="%(class)s_deleted_idx"),)

    def soft_delete(self, deleted_by=None):
        """
        Soft delete the record.
        """
        self.deleted_at = timezone.now()
        self.deleted_by = deleted_by
        self.save(update_fields=["deleted_at", "deleted_by"])

    def restore(self):
        """
        Restore a soft-deleted record.
        """
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["deleted_at", "deleted_by"])

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class BaseModel(
    TimeStampedMixin,
    AuditMixin,
    SoftDeleteMixin,
):
    """
    Combined base model with timestamps, auditing, and soft delete.
    """

    if TYPE_CHECKING:
        id: Any

    class Meta(
        TimeStampedMixin.Meta,
        AuditMixin.Meta,
        SoftDeleteMixin.Meta,
    ):
        abstract = True
