from django.core.cache import cache
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    AdminNotification,
    DewormingTreatmentRecord,
    DogAnnouncement,
    DogRegistration,
    VaccinationRecord,
)


class AnnouncementBucketUpdateTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            password="secret123",
            is_staff=True,
        )
        self.post = DogAnnouncement.objects.create(
            title="Board post",
            content="Testing bucket updates",
            category=DogAnnouncement.CATEGORY_DOG_ANNOUNCEMENT,
            created_by=self.admin,
        )

    def test_admin_can_update_display_bucket(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dogadoption_admin:announcement_update_bucket", args=[self.post.id]),
            {"bucket": DogAnnouncement.BUCKET_PINNED},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.post.refresh_from_db()
        self.assertEqual(self.post.display_bucket, DogAnnouncement.BUCKET_PINNED)
        self.assertJSONEqual(
            response.content,
            {
                "ok": True,
                "bucket": DogAnnouncement.BUCKET_PINNED,
                "bucket_label": "Pinned",
            },
        )

    def test_invalid_bucket_is_rejected(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dogadoption_admin:announcement_update_bucket", args=[self.post.id]),
            {"bucket": "not-a-real-bucket"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.post.refresh_from_db()
        self.assertEqual(self.post.display_bucket, DogAnnouncement.BUCKET_ORDINARY)


class AdminExpiryNotificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username="admin_expiry",
            password="secret123",
            is_staff=True,
        )
        self.registration = DogRegistration.objects.create(
            reg_no="REG-100",
            name_of_pet="Buddy",
            breed="Aspen",
            color_markings="Brown",
            sex="M",
            status="Intact",
            owner_name="Jane Doe",
            address="Sample Street, Villareal, Bayawan City, Negros Oriental",
            contact_no="09123456789",
        )

    def test_admin_notifications_page_creates_today_expiry_alerts_without_duplicates(self):
        today = timezone.localdate()
        VaccinationRecord.objects.create(
            registration=self.registration,
            date=today,
            vaccine_name="Anti-rabies",
            manufacturer_lot_no="LOT-100",
            vaccine_expiry_date=today,
            vaccination_expiry_date=today,
            veterinarian="Dr. Cruz",
        )
        DewormingTreatmentRecord.objects.create(
            registration=self.registration,
            date=today,
            medicine_given="Caniverm",
            medicine_expiry_date=today,
            route="Oral",
            frequency="Single dose",
            veterinarian="Dr. Cruz",
        )

        self.client.force_login(self.admin)
        url = reverse("dogadoption_admin:admin_notifications")

        first_response = self.client.get(url)
        second_response = self.client.get(url)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertContains(first_response, "Vaccination card expires today")
        self.assertContains(first_response, "Medicine expires today")
        self.assertContains(first_response, "Buddy (REG-100) vaccination card expires today")
        self.assertContains(first_response, "Buddy (REG-100) medicine Caniverm expires today")
        self.assertEqual(AdminNotification.objects.filter(is_read=False).count(), 2)
        self.assertEqual(
            AdminNotification.objects.filter(event_key__startswith="vaccination-card-expiry:").count(),
            1,
        )
        self.assertEqual(
            AdminNotification.objects.filter(event_key__startswith="medicine-expiry:").count(),
            1,
        )
        self.assertEqual(first_response.context["admin_unread_notifications"], 2)

    def test_med_record_post_saves_medicine_expiry_date_and_surfaces_notification(self):
        today = timezone.localdate()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dogadoption_admin:med_records", args=[self.registration.id]),
            {
                "record_type": "deworming",
                "dew_date": today.isoformat(),
                "medicine_given": "Drontal",
                "medicine_expiry_date": today.isoformat(),
                "route": "Oral",
                "frequency": "Monthly",
                "dew_veterinarian": "Dr. Reyes",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        record = DewormingTreatmentRecord.objects.get(registration=self.registration)
        self.assertEqual(record.medicine_expiry_date, today)
        self.assertContains(response, "Medicine expires today")
        self.assertEqual(response.context["admin_unread_notifications"], 1)
