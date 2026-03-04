from django.apps import apps as django_apps
from django.conf import settings
from django.db.models.signals import post_delete, post_migrate, post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

from .cache_utils import invalidate_analytics_dashboard_cache

User = get_user_model()


def _invalidate_analytics_cache_on_model_change(**kwargs):
    invalidate_analytics_dashboard_cache()


def _connect_analytics_invalidation_signals():
    sender_labels = (
        "auth.User",
        "dogadoption_admin.Post",
        "dogadoption_admin.PostRequest",
        "user.DogCaptureRequest",
        "dogadoption_admin.DogRegistration",
        "dogadoption_admin.VaccinationRecord",
        "dogadoption_admin.Dog",
    )
    for sender_label in sender_labels:
        sender = django_apps.get_model(sender_label)
        if sender is None:
            continue
        post_save.connect(
            _invalidate_analytics_cache_on_model_change,
            sender=sender,
            weak=False,
            dispatch_uid=f"analytics_invalidate_save_{sender_label}",
        )
        post_delete.connect(
            _invalidate_analytics_cache_on_model_change,
            sender=sender,
            weak=False,
            dispatch_uid=f"analytics_invalidate_delete_{sender_label}",
        )


_connect_analytics_invalidation_signals()


@receiver(post_migrate)
def create_default_admin(sender, **kwargs):
    if sender.name != "dogadoption_admin":
        return

    if not getattr(settings, "CREATE_DEFAULT_ADMIN", False):
        return

    username = getattr(settings, "DEFAULT_ADMIN_USERNAME", "").strip()
    password = getattr(settings, "DEFAULT_ADMIN_PASSWORD", "")
    email = getattr(settings, "DEFAULT_ADMIN_EMAIL", "").strip()
    if not username or not password:
        return

    if User.objects.filter(username=username).exists():
        return

    User.objects.create_superuser(
        username=username,
        email=email,
        password=password,
    )
