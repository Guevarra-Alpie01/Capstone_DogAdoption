from datetime import date

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from dogadoption_admin.models import Barangay
from user.models import DogCaptureRequest


class UserDogSurrenderRequestTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="request_member",
            password="Request123!",
        )
        self.request_url = reverse("user:dog_capture_request")
        Barangay.objects.update_or_create(
            name="Bugay",
            defaults={"is_active": True},
        )

    def test_request_page_only_shows_surrender_online_flow(self):
        self.client.force_login(self.user)

        response = self.client.get(self.request_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dog Surrender Form")
        self.assertContains(response, 'name="request_type" value="surrender"', html=False)
        self.assertContains(response, 'name="submission_type" value="online"', html=False)
        self.assertNotContains(response, "Request Dog Capture")
        self.assertNotContains(response, "Walk-in Request (Office)")

    def test_guest_can_view_request_page_but_submit_uses_login_modal_flow(self):
        response = self.client.get(self.request_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dog Surrender Form")
        self.assertContains(response, 'data-auth-modal-trigger="login"', html=False)

    def test_guest_request_submission_redirects_to_home_login_modal(self):
        response = self.client.post(
            self.request_url,
            {
                "phone_number": "09171234567",
                "location_mode": "manual",
                "barangay": "Bugay",
                "city": "Bayawan City",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("auth_modal=login", response["Location"])
        self.assertIn("next=%2Fuser%2Frequest%2F", response["Location"])

    def test_submission_forces_online_surrender_and_ignores_legacy_values(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.request_url,
            {
                "request_type": "capture",
                "submission_type": "walk_in",
                "appointment_date": "2026-04-15",
                "phone_number": "09171234567",
                "location_mode": "manual",
                "barangay": "Bugay",
                "city": "Bayawan City",
                "manual_full_address": "Purok 1",
                "reason": "aggressive",
                "description": "Needs safe turnover.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        request_record = DogCaptureRequest.objects.get(requested_by=self.user)
        self.assertEqual(request_record.request_type, "surrender")
        self.assertEqual(request_record.submission_type, "online")
        self.assertIsNone(request_record.preferred_appointment_date)
        self.assertEqual(request_record.barangay, "Bugay")
        self.assertEqual(request_record.manual_full_address, "Purok 1")
        self.assertEqual(request_record.description, "Needs safe turnover.")

    def test_exact_submission_requires_good_gps_accuracy(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.request_url,
            {
                "phone_number": "09171234567",
                "location_mode": "exact",
                "latitude": "9.123456",
                "longitude": "122.654321",
                "gps_accuracy": "130",
                "reason": "stray",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(DogCaptureRequest.objects.filter(requested_by=self.user).exists())
        self.assertContains(response, "100 meters or better")

    def test_exact_submission_accepts_usable_gps_accuracy(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.request_url,
            {
                "phone_number": "09171234567",
                "location_mode": "exact",
                "latitude": "9.123456",
                "longitude": "122.654321",
                "gps_accuracy": "80",
                "reason": "stray",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        request_record = DogCaptureRequest.objects.get(requested_by=self.user)
        self.assertEqual(str(request_record.latitude), "9.123456")
        self.assertEqual(str(request_record.longitude), "122.654321")
        self.assertEqual(request_record.submission_type, "online")

    def test_exact_submission_saves_coordinates_when_accuracy_is_good(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.request_url,
            {
                "phone_number": "09171234567",
                "location_mode": "exact",
                "latitude": "9.123456",
                "longitude": "122.654321",
                "gps_accuracy": "12",
                "reason": "stray",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        request_record = DogCaptureRequest.objects.get(requested_by=self.user)
        self.assertEqual(str(request_record.latitude), "9.123456")
        self.assertEqual(str(request_record.longitude), "122.654321")
        self.assertEqual(request_record.submission_type, "online")

    def test_edit_forces_online_surrender_and_clears_old_appointment_data(self):
        request_record = DogCaptureRequest.objects.create(
            requested_by=self.user,
            request_type="capture",
            submission_type="walk_in",
            preferred_appointment_date=date(2026, 4, 15),
            reason="stray",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("user:edit_dog_capture_request", args=[request_record.id]),
            {
                "request_type": "capture",
                "submission_type": "walk_in",
                "appointment_date": "2026-04-18",
                "location_mode": "manual",
                "barangay": "Bugay",
                "city": "Bayawan City",
                "manual_full_address": "Near barangay hall",
                "description": "Updated surrender details.",
                "reason": "stray",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        request_record.refresh_from_db()
        self.assertEqual(request_record.request_type, "surrender")
        self.assertEqual(request_record.submission_type, "online")
        self.assertIsNone(request_record.preferred_appointment_date)
        self.assertEqual(request_record.barangay, "Bugay")
        self.assertEqual(request_record.manual_full_address, "Near barangay hall")
        self.assertEqual(request_record.description, "Updated surrender details.")
