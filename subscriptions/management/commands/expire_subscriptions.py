from django.core.management.base import BaseCommand

from subscriptions.services import expire_overdue_subscriptions


class Command(BaseCommand):
    help = "Expire overdue subscriptions and move those users back to Basic"

    def handle(self, *args, **options):
        count = expire_overdue_subscriptions()
        if options.get("verbosity", 1):
            self.stdout.write(self.style.SUCCESS(f"Expired {count} subscription(s)."))
