from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from subscriptions.models import (
    Subscription,
    SubscriptionStatus,
    Tier,
)
from subscriptions.services import change_plan, expire_overdue_subscriptions
from users.tokens import make_email_verification_token

User = get_user_model()

PASSWORD = "S0me-Str0ng-Pass"
PLATINUM_URL = "/api/v1/subscriptions/demo/platinum/"
DIAMOND_URL = "/api/v1/subscriptions/demo/diamond/"


class SubscriptionTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        call_command("seed_plans", verbosity=0)
        self.client = APIClient()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                "/api/v1/auth/register/",
                {
                    "username": "a",
                    "email": "a@example.com",
                    "password": PASSWORD,
                },
                format="json",
            )
        self.user = User.objects.get(username="a")
        self.client.post(
            "/api/v1/auth/verify-email/",
            {"token": make_email_verification_token(self.user)},
            format="json",
        )
        login = self.client.post(
            "/api/v1/auth/login/",
            {"username": "a", "password": PASSWORD},
            format="json",
        )
        self.access = login.json()["access"]
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {self.access}"

    def test_basic_is_blocked_from_platinum(self):
        response = self.client.get(PLATINUM_URL)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["code"], "tier_required")

    def test_upgrade_takes_effect_without_a_new_token(self):
        change_plan(self.user, Tier.PLATINUM)

        # Deliberately reuse the access token issued while the user was Basic.
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {self.access}"
        self.assertEqual(self.client.get(PLATINUM_URL).status_code, 200)
        self.assertEqual(self.client.get(DIAMOND_URL).status_code, 403)

    def test_diamond_can_access_everything(self):
        change_plan(self.user, Tier.DIAMOND)

        self.assertEqual(self.client.get(PLATINUM_URL).status_code, 200)
        self.assertEqual(self.client.get(DIAMOND_URL).status_code, 200)

    def test_downgrade_takes_effect_immediately(self):
        change_plan(self.user, Tier.PLATINUM)
        self.assertEqual(self.client.get(PLATINUM_URL).status_code, 200)

        change_plan(self.user, Tier.BASIC)

        self.assertEqual(self.client.get(PLATINUM_URL).status_code, 403)
        self.assertEqual(
            Subscription.objects.get(
                user=self.user, status=SubscriptionStatus.ACTIVE
            ).plan.tier,
            Tier.BASIC,
        )

    def test_plan_change_keeps_history_and_one_live_row(self):
        change_plan(self.user, Tier.PLATINUM)
        change_plan(self.user, Tier.DIAMOND)

        subs = Subscription.objects.filter(user=self.user)
        self.assertEqual(subs.count(), 3)  # Basic + Platinum + Diamond
        live = subs.filter(status=SubscriptionStatus.ACTIVE)
        self.assertEqual(live.count(), 1)
        self.assertEqual(live.get().plan.tier, Tier.DIAMOND)

    def test_expire_overdue_subscriptions_falls_back_to_basic(self):
        change_plan(self.user, Tier.PLATINUM)
        Subscription.objects.filter(user=self.user, plan__tier=Tier.PLATINUM).update(
            current_period_end=timezone.now() - timedelta(minutes=1)
        )

        expired = expire_overdue_subscriptions()

        self.assertEqual(expired, 1)
        self.assertEqual(self.client.get(PLATINUM_URL).status_code, 403)
        self.assertEqual(
            Subscription.objects.get(
                user=self.user, status=SubscriptionStatus.ACTIVE
            ).plan.tier,
            Tier.BASIC,
        )
        self.assertEqual(
            Subscription.objects.filter(
                user=self.user, status=SubscriptionStatus.ACTIVE
            )
            .get()
            .plan.tier,
            Tier.BASIC,
        )

    def test_expire_overdue_subscriptions_is_idempotent(self):
        change_plan(self.user, Tier.PLATINUM)
        Subscription.objects.filter(user=self.user, plan__tier=Tier.PLATINUM).update(
            current_period_end=timezone.now() - timedelta(minutes=1)
        )
        self.assertEqual(expire_overdue_subscriptions(), 1)
        self.assertEqual(expire_overdue_subscriptions(), 0)

    def test_expired_trial_is_not_live(self):
        sub = change_plan(self.user, Tier.PLATINUM)
        Subscription.objects.filter(pk=sub.pk).update(
            status=SubscriptionStatus.TRIALING,
            trial_ends_at=timezone.now() - timedelta(minutes=1),
            current_period_end=timezone.now() + timedelta(days=7),
        )

        self.assertEqual(self.client.get(PLATINUM_URL).status_code, 403)

    def test_my_subscription_shape(self):
        response = self.client.get("/api/v1/subscriptions/me/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["tier"], Tier.BASIC)
        self.assertEqual(data["status"], SubscriptionStatus.ACTIVE)
        self.assertIsNone(data["current_period_end"])
        self.assertIn("limits", data)

    def test_plans_are_public(self):
        self.client.defaults.pop("HTTP_AUTHORIZATION", None)
        response = self.client.get("/api/v1/subscriptions/plans/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [p["tier"] for p in response.json()],
            [Tier.BASIC, Tier.PLATINUM, Tier.DIAMOND],
        )

    def test_change_plan_rejects_unknown_tier(self):
        with self.assertRaises(ValueError):
            change_plan(self.user, "gold")
