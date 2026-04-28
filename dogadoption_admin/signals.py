from django.apps import apps as django_apps
from django.conf import settings
from django.db.models.signals import post_delete, post_migrate, post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

from .cache_utils import invalidate_analytics_dashboard_cache
from .models import DogRegistration, DogSurrenderRecord, VaccinationRecord
from .vaccination_list_print_service import invalidate_vaccination_certificate_export_cache
from user.models import DogCaptureRequest

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


def _invalidate_vaccination_export_cache(**kwargs):
    invalidate_vaccination_certificate_export_cache()


for _sender, _uid in (
    (DogRegistration, "dogreg_cert_pdf_cache"),
    (VaccinationRecord, "vacrec_cert_pdf_cache"),
):
    post_save.connect(
        _invalidate_vaccination_export_cache,
        sender=_sender,
        weak=False,
        dispatch_uid=f"cert_pdf_cache_invalidate_save_{_uid}",
    )
    post_delete.connect(
        _invalidate_vaccination_export_cache,
        sender=_sender,
        weak=False,
        dispatch_uid=f"cert_pdf_cache_invalidate_delete_{_uid}",
    )


@receiver(post_save, sender=DogCaptureRequest)
def ensure_dog_surrender_admin_record(sender, instance, **kwargs):
    """Ensure a standalone surrender record row exists when a surrender is marked completed."""
    if instance.status == "captured" and instance.request_type == "surrender":
        DogSurrenderRecord.objects.get_or_create(capture_request_id=instance.pk, defaults={})


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
