from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "tier",
        "name",
        "price_monthly",
        "price_yearly",
        "currency",
        "is_active",
    )
    list_filter = ("is_active",)
    search_fields = ("tier", "name")
    ordering = ("price_monthly",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "plan",
        "status",
        "billing_cycle",
        "current_period_end",
        "cancel_at_period_end",
        "is_live",
    )
    list_filter = ("status", "billing_cycle", "plan", "provider")
    search_fields = (
        "user__username",
        "user__email",
        "provider_subscription_id",
        "provider_customer_id",
    )
    autocomplete_fields = ("user", "plan")
    list_select_related = ("user", "plan")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at", "started_at")
    date_hierarchy = "created_at"

    @admin.display(boolean=True, description=_("Live"))
    def is_live(self, obj):
        return obj.is_live
