from django.core.management.base import BaseCommand

from subscriptions.models import Plan
from subscriptions.plan_defaults import PLAN_DEFAULTS


class Command(BaseCommand):
    help = "Create or update the Basic / Platinum / Diamond plans"

    def handle(self, *args, **options):
        for entry in PLAN_DEFAULTS:
            data = dict(entry)  # never mutate the module-level defaults
            tier = data.pop("tier")
            plan, created = Plan.all_objects.update_or_create(tier=tier, defaults=data)
            # update_or_create also finds soft-deleted rows; bring them back.
            if plan.is_deleted:
                plan.restore()
            if not plan.is_active:
                plan.is_active = True
                plan.save(update_fields=["is_active", "updated_at"])
            if options.get("verbosity", 1):
                self.stdout.write(f"{'Created' if created else 'Updated'} {plan.name}")
