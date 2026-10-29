"""Seed data for the plan catalog.

Shared by the ``seed_plans`` management command, the initial data migration and
the ``assign_default_plan`` fallback so the three tiers always exist.
"""

from .models import Tier

PLAN_DEFAULTS = (
    {
        "tier": Tier.BASIC,
        "name": "Basic",
        "description": "Free plan. Get started with the essentials.",
        "price_monthly": 0,
        "price_yearly": 0,
        "limits": {
            "max_projects": 3,
            "api_calls_per_day": 1_000,
            "export": False,
        },
    },
    {
        "tier": Tier.PLATINUM,
        "name": "Platinum",
        "description": "For growing teams that need more room.",
        "price_monthly": 19,
        "price_yearly": 190,
        "limits": {
            "max_projects": 25,
            "api_calls_per_day": 25_000,
            "export": True,
        },
    },
    {
        "tier": Tier.DIAMOND,
        "name": "Diamond",
        "description": "Unlimited access and priority support.",
        "price_monthly": 49,
        "price_yearly": 490,
        "limits": {
            "max_projects": None,
            "api_calls_per_day": None,
            "export": True,
        },
    },
)
