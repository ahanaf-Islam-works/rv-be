"""Subscription business logic.

Views must not mutate subscriptions directly: any client-facing "upgrade" would
be a privilege-escalation bug. Plan changes come from ``change_plan()``, called
by payment-provider webhooks (Stripe etc.) after a verified payment.
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    LIVE_STATUSES,
    BillingCycle,
    Plan,
    Subscription,
    SubscriptionStatus,
    Tier,
    tier_rank,
)
from .plan_defaults import PLAN_DEFAULTS


def live_subscriptions_q(now=None) -> Q:
    """Q object matching live rows (status, period end and trial end aware)."""
    now = now or timezone.now()
    return (
        Q(status__in=LIVE_STATUSES)
        & (Q(current_period_end__isnull=True) | Q(current_period_end__gt=now))
        & ~(
            Q(status=SubscriptionStatus.TRIALING)
            & Q(trial_ends_at__isnull=False)
            & Q(trial_ends_at__lte=now)
        )
    )


def get_live_subscription(user) -> Subscription | None:
    """The user's current subscription, or ``None``."""
    if not user or not user.is_authenticated:
        return None
    return (
        Subscription.objects.select_related("plan")
        .filter(user=user)
        .filter(live_subscriptions_q())
        .order_by("-created_at")
        .first()
    )


def get_user_tier(user) -> str:
    sub = get_live_subscription(user)
    return sub.plan.tier if sub else Tier.BASIC


def get_basic_plan() -> Plan:
    """Return the Basic plan, recreating/restoring it if it was removed."""
    plan = Plan.all_objects.filter(tier=Tier.BASIC).first()
    if plan is None:
        defaults = dict(next(p for p in PLAN_DEFAULTS if p["tier"] == Tier.BASIC))
        defaults.pop("tier")
        return Plan.objects.create(tier=Tier.BASIC, **defaults)
    if plan.is_deleted or not plan.is_active:
        plan.deleted_at = None
        plan.deleted_by = None
        plan.is_active = True
        plan.save(update_fields=["deleted_at", "deleted_by", "is_active", "updated_at"])
    return plan


@transaction.atomic
def assign_default_plan(user) -> Subscription:
    """Give the user the free Basic plan (idempotent).

    Called at registration and whenever a paid subscription expires. If the user
    already has a live subscription this is a no-op.
    """
    existing = get_live_subscription(user)
    if existing:
        return existing

    plan = get_basic_plan()
    try:
        with transaction.atomic():
            return Subscription.objects.create(
                user=user,
                plan=plan,
                status=SubscriptionStatus.ACTIVE,
                current_period_end=None,
            )
    except IntegrityError:
        # Lost a race against another request creating the live row.
        existing = get_live_subscription(user)
        if existing:
            return existing
        raise


def _period_end(now, billing_cycle: str):
    if billing_cycle == BillingCycle.YEARLY:
        return now + timedelta(days=365)
    return now + timedelta(days=30)


@transaction.atomic
def change_plan(
    user,
    tier: str,
    billing_cycle: str = BillingCycle.MONTHLY,
    *,
    provider: str = "",
    provider_customer_id: str = "",
    provider_subscription_id: str = "",
) -> Subscription:
    """Close the current live subscription and open a new one on ``tier``.

    Call this from a payment webhook after a successful payment, never from a
    client-facing endpoint.
    """
    try:
        plan = Plan.all_objects.get(tier=tier)
    except Plan.DoesNotExist as exc:
        raise ValueError(f"Unknown plan tier: {tier!r}") from exc
    if plan.is_deleted or not plan.is_active:
        raise ValueError(f"Plan {tier!r} is not available")
    if billing_cycle not in BillingCycle.values:
        raise ValueError(f"Invalid billing cycle: {billing_cycle!r}")

    now = timezone.now()

    # Close every row that still counts as live for the unique constraint,
    # including a trial whose trial window has elapsed.
    live = list(
        Subscription.objects.select_for_update().filter(
            user=user, status__in=LIVE_STATUSES
        )
    )
    for sub in live:
        sub.status = SubscriptionStatus.CANCELED
        sub.ended_at = now
        sub.save(update_fields=["status", "ended_at", "updated_at"])

    period_end = None if tier == Tier.BASIC else _period_end(now, billing_cycle)

    return Subscription.objects.create(
        user=user,
        plan=plan,
        status=SubscriptionStatus.ACTIVE,
        billing_cycle=billing_cycle,
        started_at=now,
        current_period_start=now,
        current_period_end=period_end,
        provider=provider,
        provider_customer_id=provider_customer_id,
        provider_subscription_id=provider_subscription_id,
    )


@transaction.atomic
def expire_overdue_subscriptions() -> int:
    """Expire overdue paid subscriptions and move those users back to Basic.

    Run periodically (Celery beat / cron): ``python manage.py expire_subscriptions``.
    Returns the number of expired subscriptions.
    """
    now = timezone.now()
    overdue = (
        Subscription.objects.select_for_update()
        .select_related("user", "plan")
        .filter(status__in=LIVE_STATUSES)
        .filter(
            Q(current_period_end__lt=now)
            | Q(status=SubscriptionStatus.TRIALING, trial_ends_at__lt=now)
        )
    )
    count = 0
    for sub in overdue:
        sub.status = SubscriptionStatus.EXPIRED
        sub.ended_at = now
        sub.save(update_fields=["status", "ended_at", "updated_at"])
        assign_default_plan(sub.user)
        count += 1
    return count


def max_tier(*tiers: str) -> str:
    """Highest of the given tier values (helper for future features)."""
    return max(tiers, key=tier_rank, default=Tier.BASIC)
