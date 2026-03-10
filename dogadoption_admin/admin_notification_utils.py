from django.urls import reverse
from django.utils import timezone

from .models import AdminNotification, DewormingTreatmentRecord, VaccinationRecord


def _notification_target(registration_id):
    if registration_id:
        return reverse("dogadoption_admin:med_records", args=[registration_id])
    return reverse("dogadoption_admin:admin_notifications")


def _registration_suffix(registration):
    if not registration:
        return ""
    reg_no = (registration.reg_no or "").strip()
    if not reg_no:
        return ""
    return f" ({reg_no})"


def _create_notification_once(*, event_key, title, message, url):
    if AdminNotification.objects.filter(event_key=event_key).exists():
        return False

    AdminNotification.objects.create(
        title=title,
        message=message,
        url=url,
        event_key=event_key,
    )
    return True


def sync_expiry_notifications(today=None):
    today = today or timezone.localdate()
    created_any = False
    created_any |= _sync_vaccination_card_expiry_notifications(today)
    created_any |= _sync_medicine_expiry_notifications(today)
    return created_any


def _sync_vaccination_card_expiry_notifications(today):
    created_any = False
    records = (
        VaccinationRecord.objects.select_related("registration")
        .filter(vaccination_expiry_date=today)
        .order_by("registration_id", "id")
    )
    for record in records:
        registration = record.registration
        pet_name = registration.name_of_pet if registration else "Unassigned pet"
        message = (
            f"{pet_name}{_registration_suffix(registration)} vaccination card expires today, "
            f"{today:%B %d, %Y}."
        )
        created_any |= _create_notification_once(
            event_key=f"vaccination-card-expiry:{record.pk}:{today.isoformat()}",
            title="Vaccination card expires today",
            message=message,
            url=_notification_target(getattr(registration, "id", None)),
        )
    return created_any


def _sync_medicine_expiry_notifications(today):
    created_any = False
    records = (
        DewormingTreatmentRecord.objects.select_related("registration")
        .filter(medicine_expiry_date=today)
        .order_by("registration_id", "id")
    )
    for record in records:
        registration = record.registration
        pet_name = registration.name_of_pet if registration else "Unassigned pet"
        medicine_name = (record.medicine_given or "Medicine").strip()
        message = (
            f"{pet_name}{_registration_suffix(registration)} medicine {medicine_name} expires today, "
            f"{today:%B %d, %Y}."
        )
        created_any |= _create_notification_once(
            event_key=f"medicine-expiry:{record.pk}:{today.isoformat()}",
            title="Medicine expires today",
            message=message,
            url=_notification_target(getattr(registration, "id", None)),
        )
    return created_any
