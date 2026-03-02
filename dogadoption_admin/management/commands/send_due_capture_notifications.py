from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Dog capture SMS notifications are disabled."

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("SMS sending has been disabled for dog capture requests."))
