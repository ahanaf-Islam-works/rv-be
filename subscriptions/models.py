from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from config.models import BaseModel


class Tier(models.TextChoices):
    BASIC = "basic", _("Basic")
    PLATINUM = "platinum", _("Platinum")
    DIAMOND = "diamond", _("Diamond")


# Single source of truth for ordering tiers (higher = more access).
TIER_RANK = {Tier.BASIC: 1, Tier.PLATINUM: 2, Tier.DIAMOND: 3}


def tier_rank(tier: str) -> int:
    """Rank of a tier value; unknown values rank below Basic instead of crashing."""
    try:
        return TIER_RANK[Tier(tier)]
    except (KeyError, ValueError):
        return 0


class SubscriptionStatus(models.TextChoices):
    TRIALING = "trialing", _("Trialing")
    ACTIVE = "active", _("Active")
    PAST_DUE = "past_due", _("Past due")  # payment failed, grace period
    CANCELED = "canceled", _("Canceled")
    EXPIRED = "expired", _("Expired")


# Statuses that grant access. Used both in the DB constraint and in queries.
LIVE_STATUSES = (
    SubscriptionStatus.TRIALING,
    SubscriptionStatus.ACTIVE,
    SubscriptionStatus.PAST_DUE,
)


class BillingCycle(models.TextChoices):
    MONTHLY = "monthly", _("Monthly")
    YEARLY = "yearly", _("Yearly")


class Plan(BaseModel):
    """
    Catalog entry. Three rows: basic, platinum, diamond.
    Prices/limits live in data, not code, so you can change them without a deploy.
    """

    tier = models.CharField(
        max_length=20, choices=Tier.choices, unique=True, verbose_name=_("Tier")
    )
    name = models.CharField(max_length=100, verbose_name=_("Name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="USD")

    # Feature limits, e.g. {"max_projects": 3, "api_calls_per_day": 1000, "export": false}
    limits = models.JSONField(default=dict, blank=True)

    # ID of this plan in your payment provider (Stripe price/product id)
    provider_price_id_monthly = models.CharField(max_length=255, blank=True)
    provider_price_id_yearly = models.CharField(max_length=255, blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("Plan")
        verbose_name_plural = _("Plans")

    def __str__(self):
        return self.name

    @property
    def rank(self) -> int:
        return tier_rank(self.tier)


class Subscription(BaseModel):
    """
    A user's subscription period. History is preserved: changing plan closes the
    old row and opens a new one. At most ONE live row per user (DB-enforced).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, related_name="subscriptions"
    )
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE,
        db_index=True,
    )
    billing_cycle = models.CharField(
        max_length=10, choices=BillingCycle.choices, default=BillingCycle.MONTHLY
    )

    started_at = models.DateTimeField(default=timezone.now)
    current_period_start = models.DateTimeField(default=timezone.now)
    # NULL = never expires (the free Basic plan)
    current_period_end = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    ended_at = models.DateTimeField(null=True, blank=True)

    # Payment provider linkage (Stripe subscription/customer ids)
    provider = models.CharField(max_length=30, blank=True)
    provider_customer_id = models.CharField(max_length=255, blank=True)
    provider_subscription_id = models.CharField(
        max_length=255, blank=True, db_index=True
    )

    class Meta:
        verbose_name = _("Subscription")
        verbose_name_plural = _("Subscriptions")
        ordering = ("-created_at",)
        constraints = (
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(status__in=[s.value for s in LIVE_STATUSES])
                & Q(deleted_at__isnull=True),
                name="one_live_subscription_per_user",
            ),
        )
        indexes = (
            models.Index(fields=["user", "status"], name="sub_user_status_idx"),
            models.Index(fields=["current_period_end"], name="sub_period_end_idx"),
        )

    def __str__(self):
        return f"{self.user.id} -> {self.plan.tier} ({self.status})"

    @property
    def is_live(self) -> bool:
        if self.status not in LIVE_STATUSES:
            return False
        now = timezone.now()
        if (
            self.status == SubscriptionStatus.TRIALING
            and self.trial_ends_at is not None
            and self.trial_ends_at <= now
        ):
            return False
        return self.current_period_end is None or self.current_period_end > now
