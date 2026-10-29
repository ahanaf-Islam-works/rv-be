from rest_framework import serializers

from .models import Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    rank = serializers.IntegerField(read_only=True)

    class Meta:
        model = Plan
        fields = (
            "tier",
            "name",
            "description",
            "price_monthly",
            "price_yearly",
            "currency",
            "limits",
            "rank",
        )


class SubscriptionSerializer(serializers.ModelSerializer):
    tier = serializers.CharField(source="plan.tier", read_only=True)
    plan = PlanSerializer(read_only=True)
    limits = serializers.JSONField(source="plan.limits", read_only=True)

    class Meta:
        model = Subscription
        fields = (
            "tier",
            "plan",
            "limits",
            "status",
            "billing_cycle",
            "started_at",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
        )
        read_only_fields = fields
