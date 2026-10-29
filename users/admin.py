from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserCreationForm as DjangoUserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import User


class UserCreationForm(DjangoUserCreationForm):
    class Meta(DjangoUserCreationForm.Meta):
        model = User
        fields = ("username", "email")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_form = UserCreationForm
    ordering = ("-created_at",)
    list_display = (
        "username",
        "email",
        "tier",
        "is_email_verified",
        "is_active",
        "is_staff",
        "created_at",
    )
    list_filter = (
        "is_active",
        "is_staff",
        "is_superuser",
        "email_verified_at",
    )
    search_fields = ("username", "email", "first_name", "last_name")
    readonly_fields = ("last_login", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            _("Personal info"),
            {"fields": ("first_name", "last_name", "email", "email_verified_at")},
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "password1", "password2"),
            },
        ),
    )

    @admin.display(boolean=True, description=_("Email verified"))
    def is_email_verified(self, obj):
        return obj.is_email_verified
