from django.core.cache import cache
from django.core.management.base import BaseCommand

from dogadoption_admin.admin_notification_utils import sync_expiry_notifications
from dogadoption_admin.context_processors import ADMIN_NOTIFICATIONS_CACHE_KEY


class Command(BaseCommand):
    help = "Sync admin expiry notifications without waiting for a page request."

    def handle(self, *args, **options):
        created_any = sync_expiry_notifications()
        if created_any:
            cache.delete(ADMIN_NOTIFICATIONS_CACHE_KEY)
            self.stdout.write(
                self.style.SUCCESS("Admin expiry notifications synced and cache refreshed.")
            )
            return

        self.stdout.write("No new admin expiry notifications were created.")
