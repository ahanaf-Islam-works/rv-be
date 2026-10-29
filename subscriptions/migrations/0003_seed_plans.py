from django.db import migrations

PLANS = (
    {
        "tier": "basic",
        "name": "Basic",
        "description": "Free plan. Get started with the essentials.",
        "price_monthly": 0,
        "price_yearly": 0,
        "limits": {"max_projects": 3, "api_calls_per_day": 1000, "export": False},
    },
    {
        "tier": "platinum",
        "name": "Platinum",
        "description": "For growing teams that need more room.",
        "price_monthly": 19,
        "price_yearly": 190,
        "limits": {"max_projects": 25, "api_calls_per_day": 25000, "export": True},
    },
    {
        "tier": "diamond",
        "name": "Diamond",
        "description": "Unlimited access and priority support.",
        "price_monthly": 49,
        "price_yearly": 490,
        "limits": {"max_projects": None, "api_calls_per_day": None, "export": True},
    },
)


def seed_plans(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for entry in PLANS:
        defaults = {k: v for k, v in entry.items() if k != "tier"}
        Plan.objects.update_or_create(tier=entry["tier"], defaults=defaults)


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0002_initial"),
    ]

    operations = [
        # Reversible no-op: removing catalog rows would break existing
        # subscriptions (Plan is PROTECTed). Use `seed_plans` to update prices.
        migrations.RunPython(seed_plans, migrations.RunPython.noop),
    ]
