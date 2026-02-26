from django.core.management.base import BaseCommand
from django.utils import timezone

from dogadoption_admin.models import DogCatcherContact
from dogadoption_admin.sms import build_capture_message, send_sms
from user.models import DogCaptureRequest


class Command(BaseCommand):
    help = "Send dog capture SMS notifications that are due."

    def handle(self, *args, **options):
        now = timezone.now()
        contacts = list(
            DogCatcherContact.objects.filter(active=True).values_list("phone_number", flat=True)
        )

        if not contacts:
            self.stdout.write(self.style.WARNING("No active dog catcher contacts; nothing sent."))
            return

        due = DogCaptureRequest.objects.filter(
            status="accepted",
            scheduled_date__isnull=False,
            notification_sent_at__isnull=True,
            notification_scheduled_for__lte=now,
        ).order_by("notification_scheduled_for")

        if not due:
            self.stdout.write("No due notifications.")
            return

        sent_count = 0
        for req in due:
            message = build_capture_message(req)
            if send_sms(contacts, message):
                req.notification_sent_at = now
                req.save(update_fields=["notification_sent_at"])
                sent_count += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent_count} notification(s)."))
