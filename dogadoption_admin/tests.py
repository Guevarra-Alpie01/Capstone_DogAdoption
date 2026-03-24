from datetime import datetime, time, timedelta

from django.core.cache import cache
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from django.templatetags.static import static
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import CitationForm, PostForm
from .models import (
    AdminNotification,
    Barangay,
    CertificateSettings,
    Citation,
    DewormingTreatmentRecord,
    Dog,
    DogImage,
    DogAnnouncement,
    DogRegistration,
    GlobalAppointmentDate,
    Penalty,
    PenaltySection,
    Post,
    PostRequest,
    VaccinationRecord,
)
from user.models import DogCaptureRequest, Profile


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


class CitationFormTests(TestCase):
    def setUp(self):
        Barangay.objects.update_or_create(
            name="Bugay",
            defaults={"is_active": True},
        )

    def test_owner_barangay_field_uses_autocomplete_widget_attrs(self):
        form = CitationForm()

        widget = form.fields["owner_barangay"].widget

        self.assertEqual(widget.attrs.get("data-barangay-autocomplete"), "true")
        self.assertEqual(widget.attrs.get("data-barangay-suggestions-id"), "citation-barangay-suggestions")
        self.assertEqual(widget.attrs.get("data-barangay-strict"), "true")
        self.assertEqual(
            str(widget.attrs.get("data-barangay-source-url")),
            reverse("dogadoption_admin:barangay_list_api"),
        )

    def test_owner_barangay_accepts_case_insensitive_match(self):
        form = CitationForm(
            data={
                "owner_first_name": "Maria",
                "owner_last_name": "Lopez",
                "owner_barangay": "bugay",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["owner_barangay"], "Bugay")


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

    def test_sync_admin_notifications_command_creates_today_expiry_alerts_without_duplicates(self):
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
        call_command("sync_admin_notifications")

        first_response = self.client.get(url)
        call_command("sync_admin_notifications")
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
        summary_response = self.client.get(reverse("dogadoption_admin:notification_summary"))
        self.assertEqual(summary_response.json()["unread_count"], 2)

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
        summary_response = self.client.get(reverse("dogadoption_admin:notification_summary"))
        self.assertEqual(summary_response.json()["unread_count"], 1)
        self.assertTrue(
            any(
                item["title"] == "Medicine expires today"
                for item in summary_response.json()["notifications"]
            )
        )

    def test_mark_notification_read_updates_unread_count(self):
        notification = AdminNotification.objects.create(
            title="Vaccination card expires today",
            message="Buddy (REG-100) vaccination card expires today",
            url=reverse("dogadoption_admin:admin_notifications"),
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dogadoption_admin:notification_read", args=[notification.id]),
            follow=True,
        )

        notification.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(notification.is_read)
        summary_response = self.client.get(reverse("dogadoption_admin:notification_summary"))
        self.assertEqual(summary_response.json()["unread_count"], 0)


class CertificateRegistrationFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username="admin_certificate_flow",
            password="secret123",
            is_staff=True,
        )
        self.owner = User.objects.create_user(
            username="registered_owner",
            password="secret123",
            first_name="Maria",
            last_name="Lopez",
        )
        Profile.objects.create(
            user=self.owner,
            address="Villareal, Bayawan City, Negros Oriental",
            age=29,
            consent_given=True,
            phone_number="+639171234567",
        )
        Barangay.objects.get_or_create(name="Villareal", defaults={"is_active": True})
        self.client.force_login(self.admin)

    def _certificate_payload(self, **overrides):
        payload = {
            "reg_no": "2026",
            "name_of_pet": "Bantay",
            "breed": "Aspin",
            "dob": "",
            "sex": "M",
            "status": "Intact",
            "color_markings": "Brown",
            "owner_first_name": "Maria",
            "owner_last_name": "Lopez",
            "barangay": "Villareal",
            "contact_no": "0917 123 4567",
        }
        payload.update(overrides)
        return payload

    def test_dog_certificate_generates_incrementing_registration_numbers(self):
        first_response = self.client.post(
            reverse("dogadoption_admin:dog_certificate"),
            self._certificate_payload(name_of_pet="Bantay"),
        )
        second_response = self.client.post(
            reverse("dogadoption_admin:dog_certificate"),
            self._certificate_payload(name_of_pet="Brownie"),
        )

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        registrations = list(DogRegistration.objects.order_by("id"))
        self.assertEqual([row.reg_no for row in registrations], ["CVET-2026-1", "CVET-2026-2"])
        self.assertEqual(CertificateSettings.objects.get().reg_no, "CVET-2026")

    def test_registration_user_search_api_returns_phone_number_for_autofill(self):
        response = self.client.get(
            reverse("dogadoption_admin:registration_user_search_api"),
            {"q": "Maria"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["full_name"], "Maria Lopez")
        self.assertEqual(results[0]["barangay"], "Villareal")
        self.assertEqual(results[0]["phone_number"], "+639171234567")


class AnalyticsDashboardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username="admin_analytics",
            password="secret123",
            is_staff=True,
        )
        self.request_user = User.objects.create_user(
            username="claimer",
            password="secret123",
        )

    def test_adoption_claim_chart_uses_request_activity_date_not_post_created_at(self):
        january_dt = timezone.make_aware(datetime(2026, 1, 15, 10, 0, 0), timezone.get_current_timezone())
        march_dt = timezone.make_aware(datetime(2026, 3, 9, 11, 0, 0), timezone.get_current_timezone())

        claim_post = Post.objects.create(
            user=self.admin,
            caption="Claimed dog",
            location="Bugay",
            status="reunited",
        )
        adopt_post = Post.objects.create(
            user=self.admin,
            caption="Adopted dog",
            location="San Jose",
            status="adopted",
        )
        Post.objects.filter(pk__in=[claim_post.pk, adopt_post.pk]).update(created_at=january_dt)

        claim_request = PostRequest.objects.create(
            post=claim_post,
            user=self.request_user,
            request_type="claim",
            status="accepted",
            scheduled_appointment_date=timezone.datetime(2026, 3, 9).date(),
        )
        adopt_request = PostRequest.objects.create(
            post=adopt_post,
            user=self.request_user,
            request_type="adopt",
            status="accepted",
            scheduled_appointment_date=timezone.datetime(2026, 3, 1).date(),
        )
        PostRequest.objects.filter(pk__in=[claim_request.pk, adopt_request.pk]).update(created_at=march_dt)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("dogadoption_admin:analytics_dashboard"))

        self.assertEqual(response.status_code, 200)
        rows = response.context["adoption_claim_trend_chart"]["rows"]
        self.assertIn(
            {"status": "claimed", "date": "2026-03-09", "total": 1},
            rows,
        )
        self.assertIn(
            {"status": "adopted", "date": "2026-03-01", "total": 1},
            rows,
        )
        self.assertNotIn(
            {"status": "claimed", "date": "2026-01-15", "total": 1},
            rows,
        )

    def test_registered_barangay_chart_exposes_date_based_events_for_filters(self):
        Dog.objects.create(
            date_registered=timezone.datetime(2026, 3, 5).date(),
            name="Alpha",
            sex="M",
            age="2 yrs",
            neutering_status="No",
            owner_name="Owner One",
            owner_address="Bugay",
            barangay="Bugay",
        )
        Dog.objects.create(
            date_registered=timezone.datetime(2026, 2, 12).date(),
            name="Beta",
            sex="F",
            age="1 yr",
            neutering_status="No",
            owner_name="Owner Two",
            owner_address="San Jose",
            barangay="San Jose",
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse("dogadoption_admin:analytics_dashboard"))

        self.assertEqual(response.status_code, 200)
        chart = response.context["barangay_chart"]
        self.assertEqual(chart["years"], [2026])
        self.assertIn({"barangay": "Bugay", "date": "2026-03-05"}, chart["events"])
        self.assertIn({"barangay": "San Jose", "date": "2026-02-12"}, chart["events"])


class RegistrationOwnerProfileTests(TestCase):
    GIF_BYTES = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
        b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00"
        b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    )

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_registration_api",
            password="secret123",
            is_staff=True,
        )
        self.owner = User.objects.create_user(
            username="owner_registered",
            password="secret123",
            first_name="Test",
            last_name="User",
        )
        self.owner_dog_1 = Dog.objects.create(
            date_registered=timezone.localdate(),
            name="Polejames",
            species="Canine",
            sex="M",
            age="1 yr",
            neutering_status="S",
            color="Red",
            owner_name="Test User",
            owner_user=self.owner,
            owner_address="Bugay",
            barangay="Bugay",
        )
        self.owner_dog_2 = Dog.objects.create(
            date_registered=timezone.localdate(),
            name="Jester",
            species="Canine",
            sex="M",
            age="2 yrs",
            neutering_status="C",
            color="White",
            owner_name="Test User",
            owner_user=self.owner,
            owner_address="Bugay",
            barangay="Bugay",
        )
        DogImage.objects.create(
            dog=self.owner_dog_1,
            image=SimpleUploadedFile("dog1_a.gif", self.GIF_BYTES, content_type="image/gif"),
        )
        DogImage.objects.create(
            dog=self.owner_dog_1,
            image=SimpleUploadedFile("dog1_b.gif", self.GIF_BYTES, content_type="image/gif"),
        )
        DogImage.objects.create(
            dog=self.owner_dog_2,
            image=SimpleUploadedFile("dog2_a.gif", self.GIF_BYTES, content_type="image/gif"),
        )

        self.client.force_login(self.admin)

    def test_registration_record_links_owner_avatar_to_profile_preview(self):
        response = self.client.get(reverse("dogadoption_admin:registration_record"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("dogadoption_admin:registration_owner_profile", args=[self.owner.id]),
        )
        self.assertNotContains(response, "Owner options")
        self.assertNotContains(response, "View Registration Photos")

    def test_registration_owner_profile_renders_read_only_preview(self):
        response = self.client.get(
            reverse("dogadoption_admin:registration_owner_profile", args=[self.owner.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Read-only owner preview")
        self.assertContains(response, "Registered Pets (2)")
        self.assertContains(response, "Polejames")
        self.assertContains(response, "Jester")


class RegistrationDuplicateOwnerTests(TestCase):
    GIF_BYTES = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
        b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00"
        b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    )

    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username="admin_duplicate_registration",
            password="secret123",
            is_staff=True,
        )
        self.primary_owner = User.objects.create_user(
            username="joker_original",
            password="secret123",
            first_name="Joker",
            last_name="Guevarra",
        )
        self.duplicate_owner = User.objects.create_user(
            username="joker_new",
            password="secret123",
            first_name="Joker",
            last_name="Guevarra",
        )
        self.barangay, _ = Barangay.objects.get_or_create(
            name="Bugay",
            defaults={"is_active": True},
        )
        Profile.objects.create(
            user=self.primary_owner,
            address="Bugay",
            age=25,
            consent_given=True,
            profile_image=SimpleUploadedFile(
                "joker.gif",
                self.GIF_BYTES,
                content_type="image/gif",
            ),
        )
        self.client.force_login(self.admin)

    def test_register_dogs_does_not_guess_owner_when_duplicate_name_is_typed_manually(self):
        response = self.client.post(
            reverse("dogadoption_admin:register_dogs"),
            {
                "barangay": self.barangay.name,
                "date": timezone.localdate().isoformat(),
                "name": "Brownie",
                "species": "Canine",
                "sex": "M",
                "age_value": "2",
                "age_unit": "years",
                "neutering": "No",
                "color": "Black",
                "owner_first_name": "Joker",
                "owner_last_name": "Guevarra",
                "owner_user_id": "",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        dog = Dog.objects.get(name="Brownie")
        self.assertEqual(dog.owner_name, "Joker Guevarra")
        self.assertIsNone(dog.owner_user)

    def test_registration_record_keeps_duplicate_name_accounts_in_separate_owner_rows(self):
        Dog.objects.create(
            date_registered=timezone.localdate(),
            name="Alpha",
            species="Canine",
            sex="M",
            age="1 yr",
            neutering_status="No",
            color="Brown",
            owner_name="Joker Guevarra",
            owner_name_key="joker guevarra",
            owner_user=self.primary_owner,
            owner_address="Bugay",
            barangay=self.barangay.name,
        )
        Dog.objects.create(
            date_registered=timezone.localdate(),
            name="Beta",
            species="Canine",
            sex="F",
            age="2 yrs",
            neutering_status="C",
            color="White",
            owner_name="Joker Guevarra",
            owner_name_key="joker guevarra",
            owner_user=self.primary_owner,
            owner_address="Bugay",
            barangay=self.barangay.name,
        )
        Dog.objects.create(
            date_registered=timezone.localdate(),
            name="Gamma",
            species="Canine",
            sex="M",
            age="3 yrs",
            neutering_status="S",
            color="Black",
            owner_name="Joker Guevarra",
            owner_name_key="joker guevarra",
            owner_user=self.duplicate_owner,
            owner_address="Bugay",
            barangay=self.barangay.name,
        )

        response = self.client.get(reverse("dogadoption_admin:registration_record"))

        self.assertEqual(response.status_code, 200)
        dogs = response.context["dogs"]
        self.assertEqual([dog.name for dog in dogs], ["Alpha", "Beta", "Gamma"])
        self.assertTrue(dogs[0].show_owner_fields)
        self.assertFalse(dogs[1].show_owner_fields)
        self.assertTrue(dogs[2].show_owner_fields)
        self.assertEqual(dogs[0].owner_profile_user_id, self.primary_owner.id)
        self.assertEqual(dogs[2].owner_profile_user_id, self.duplicate_owner.id)
        self.assertEqual(
            dogs[2].owner_profile_image_url,
            static("images/default-user-image.jpg"),
        )
        self.assertNotEqual(dogs[0].owner_profile_image_url, dogs[2].owner_profile_image_url)
        self.assertContains(
            response,
            reverse("dogadoption_admin:registration_owner_profile", args=[self.primary_owner.id]),
        )
        self.assertContains(
            response,
            reverse("dogadoption_admin:registration_owner_profile", args=[self.duplicate_owner.id]),
        )


class AdminPostGenderTests(TestCase):
    GIF_BYTES = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
        b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00"
        b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    )

    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username="admin_post_gender",
            password="secret123",
            is_staff=True,
        )
        Barangay.objects.get_or_create(name="Bugay", defaults={"is_active": True})
        self.client.force_login(self.admin)

    def _image_file(self, name="dog.gif"):
        return SimpleUploadedFile(name, self.GIF_BYTES, content_type="image/gif")

    def test_post_form_allows_optional_gender(self):
        form = PostForm(
            data={
                "caption": "Rescued dog",
                "gender": "",
                "location": "Bugay",
                "rescued_date": timezone.localdate().isoformat(),
                "claim_days": 3,
            }
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_admin_can_create_post_with_gender(self):
        response = self.client.post(
            reverse("dogadoption_admin:post_list"),
            {
                "form_type": "create_post",
                "caption": "Bantay",
                "gender": "male",
                "location": "Bugay",
                "rescued_date": timezone.localdate().isoformat(),
                "claim_days": 3,
                "images": self._image_file(),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        created_post = Post.objects.get(caption="Bantay")
        self.assertEqual(created_post.gender, "male")


class AdminPostHistoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username="admin_post_history",
            password="secret123",
            is_staff=True,
        )
        self.client.force_login(self.admin)

    def _set_created_at(self, post, created_at):
        Post.objects.filter(id=post.id).update(created_at=created_at)
        post.refresh_from_db()
        return post

    def test_post_list_history_only_shows_expired_unresolved_posts_with_pagination(self):
        now = timezone.now()
        for index in range(12):
            post = Post.objects.create(
                user=self.admin,
                caption=f"Archived Dog {index}",
                location="Bugay",
                status="rescued" if index % 2 == 0 else "under_care",
                claim_days=1,
            )
            self._set_created_at(post, now - timedelta(days=10 + index))

        active_post = Post.objects.create(
            user=self.admin,
            caption="Still Active",
            location="Bugay",
            status="rescued",
            claim_days=5,
        )
        self._set_created_at(active_post, now - timedelta(days=1))

        adopted_post = Post.objects.create(
            user=self.admin,
            caption="Already Adopted",
            location="Bugay",
            status="adopted",
            claim_days=1,
        )
        self._set_created_at(adopted_post, now - timedelta(days=12))

        reunited_post = Post.objects.create(
            user=self.admin,
            caption="Already Reclaimed",
            location="Bugay",
            status="reunited",
            claim_days=1,
        )
        self._set_created_at(reunited_post, now - timedelta(days=12))

        list_response = self.client.get(reverse("dogadoption_admin:post_list"))
        first_response = self.client.get(reverse("dogadoption_admin:post_history"))
        second_response = self.client.get(reverse("dogadoption_admin:post_history") + "?page=2")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertContains(list_response, reverse("dogadoption_admin:post_history"))
        self.assertEqual(first_response.context["history_total"], 12)
        self.assertEqual(len(first_response.context["history_posts"]), 10)
        self.assertEqual(len(second_response.context["history_posts"]), 2)
        first_history_captions = {
            item["post"].caption for item in first_response.context["history_posts"]
        }
        second_history_captions = {
            item["post"].caption for item in second_response.context["history_posts"]
        }
        self.assertContains(first_response, "Unclaimed and Unadopted Dogs")
        self.assertContains(first_response, "Posted Dog Archive")
        self.assertNotIn("Still Active", first_history_captions)
        self.assertNotIn("Already Adopted", first_history_captions)
        self.assertNotIn("Already Reclaimed", first_history_captions)
        self.assertNotIn("Still Active", second_history_captions)


class RegistrationRecordOwnerBlockTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username="admin_owner_blocks",
            password="secret123",
            is_staff=True,
        )
        self.joker = User.objects.create_user(
            username="joker_block",
            password="secret123",
            first_name="Joker",
            last_name="Guevarra",
        )
        self.argus = User.objects.create_user(
            username="argus_block",
            password="secret123",
            first_name="Argus",
            last_name="Rafaela",
        )
        self.client.force_login(self.admin)

    def test_registration_record_shows_owner_fields_again_when_same_owner_reappears_later(self):
        Dog.objects.create(
            date_registered=timezone.datetime(2026, 3, 10).date(),
            name="joker-first",
            species="Canine",
            sex="M",
            age="2 yrs",
            neutering_status="No",
            color="Black",
            owner_name="Joker Guevarra",
            owner_name_key="joker guevarra",
            owner_user=self.joker,
            owner_address="Sample 1",
            barangay="Bugay",
        )
        Dog.objects.create(
            date_registered=timezone.datetime(2026, 3, 10).date(),
            name="argus-only",
            species="Canine",
            sex="M",
            age="1 yr",
            neutering_status="C",
            color="Red",
            owner_name="Argus Rafaela",
            owner_name_key="argus rafaela",
            owner_user=self.argus,
            owner_address="Kalumboyan",
            barangay="Kalumboyan",
        )
        Dog.objects.create(
            date_registered=timezone.datetime(2026, 3, 11).date(),
            name="joker-second",
            species="Canine",
            sex="M",
            age="10 yrs",
            neutering_status="No",
            color="White",
            owner_name="Joker Guevarra",
            owner_name_key="joker guevarra",
            owner_user=self.joker,
            owner_address="Sample 1",
            barangay="Bugay",
        )

        response = self.client.get(reverse("dogadoption_admin:registration_record"))

        self.assertEqual(response.status_code, 200)
        dogs = response.context["dogs"]
        self.assertEqual([dog.name for dog in dogs], ["joker-first", "joker-second", "argus-only"])
        self.assertTrue(dogs[0].show_owner_fields)
        self.assertFalse(dogs[1].show_owner_fields)
        self.assertTrue(dogs[2].show_owner_fields)
        self.assertEqual(dogs[0].owner_display_number, 1)
        self.assertEqual(dogs[1].owner_display_number, "")
        self.assertEqual(dogs[2].owner_display_number, 2)
        self.assertEqual(dogs[0].owner_name, "Joker Guevarra")
        self.assertEqual(dogs[1].owner_name, "Joker Guevarra")
        self.assertEqual(dogs[2].owner_name, "Argus Rafaela")


class AdminUsersPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_users_page",
            password="secret123",
            is_staff=True,
        )
        self.owner = User.objects.create_user(
            username="owner_users_page",
            password="secret123",
            first_name="Owner",
            last_name="Person",
        )
        self.staff_account = User.objects.create_user(
            username="staff_should_hide",
            password="secret123",
            is_staff=True,
        )
        Profile.objects.create(
            user=self.owner,
            address="Bugay",
            age=30,
            consent_given=True,
        )
        Profile.objects.create(
            user=self.staff_account,
            address="Admin Office",
            age=30,
            consent_given=True,
        )
        claim_post = Post.objects.create(
            user=self.admin,
            caption="Claimable dog",
            location="Bugay",
            status="reunited",
        )
        PostRequest.objects.create(
            post=claim_post,
            user=self.owner,
            request_type="claim",
            status="accepted",
        )
        section = PenaltySection.objects.create(number=28)
        penalty = Penalty.objects.create(
            section=section,
            number=1,
            title="Rabies vaccination services fee",
            description="Test penalty",
            amount="50.00",
            active=True,
        )
        Citation.objects.create(
            owner=self.owner,
            owner_first_name="Owner",
            owner_last_name="Person",
            owner_barangay="Bugay",
            penalty=penalty,
        )
        self.client.force_login(self.admin)

    def test_admin_users_page_counts_claims_and_citations_and_links_to_registration_profile(self):
        response = self.client.get(reverse("dogadoption_admin:admin_users"))

        self.assertEqual(response.status_code, 200)
        users = list(response.context["users"])
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].id, self.owner.id)
        self.assertEqual(users[0].calculated_violations, 2)
        self.assertContains(
            response,
            reverse("dogadoption_admin:registration_owner_profile", args=[self.owner.id]),
        )
        self.assertNotContains(response, self.staff_account.username)


class AdminEditProfileTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_profile_old",
            password="secret123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )
        Profile.objects.create(
            user=self.admin,
            address="Admin Office",
            age=30,
            consent_given=True,
        )
        self.client.force_login(self.admin)

    def test_admin_profile_updates_username_and_password_only(self):
        response = self.client.post(
            reverse("dogadoption_admin:admin_edit_profile"),
            {
                "username": "admin_profile_new",
                "current_password": "secret123",
                "password": "newsecret123",
                "confirm_password": "newsecret123",
                "first_name": "Should",
                "last_name": "NotChange",
                "address": "Ignored",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.username, "admin_profile_new")
        self.assertEqual(self.admin.first_name, "Admin")
        self.assertEqual(self.admin.last_name, "User")
        self.assertTrue(self.admin.check_password("newsecret123"))

    def test_admin_profile_rejects_password_change_when_current_password_is_wrong(self):
        response = self.client.post(
            reverse("dogadoption_admin:admin_edit_profile"),
            {
                "username": "admin_profile_old",
                "current_password": "wrongpass",
                "password": "newsecret123",
                "confirm_password": "newsecret123",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.username, "admin_profile_old")
        self.assertTrue(self.admin.check_password("secret123"))
        self.assertContains(response, "Current password is incorrect.")


class AdminDogRequestTemplateTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="request_admin",
            password="secret123",
            is_staff=True,
        )
        self.requester = User.objects.create_user(
            username="request_user",
            password="secret123",
        )
        Profile.objects.create(
            user=self.requester,
            address="Bugay, Bayawan City",
            age=25,
            consent_given=True,
            phone_number="+639171234567",
        )
        self.client.force_login(self.admin)

    def test_admin_request_list_renders_walk_in_request_details(self):
        appointment_date = timezone.localdate() + timedelta(days=1)
        DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="capture",
            submission_type="walk_in",
            preferred_appointment_date=appointment_date,
            reason="stray",
        )

        response = self.client.get(reverse("dogadoption_admin:requests"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "request_user")
        self.assertContains(response, "+639171234567")
        self.assertContains(response, "Contact Number")
        self.assertContains(response, "Walk-in office request")

    def test_admin_request_update_page_renders_surrender_request_details(self):
        surrender_request = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="surrender",
            reason="stray",
        )

        response = self.client.get(
            reverse("dogadoption_admin:update_dog_capture_request", args=[surrender_request.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Request Dog Surrender")
        self.assertContains(response, "No dispatch location is required")
        self.assertNotContains(response, "Date Submitted")

    def test_admin_request_update_page_renders_online_surrender_location(self):
        surrender_request = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="surrender",
            submission_type="online",
            reason="stray",
            latitude="9.123456",
            longitude="122.654321",
        )

        response = self.client.get(
            reverse("dogadoption_admin:update_dog_capture_request", args=[surrender_request.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Request Dog Surrender")
        self.assertContains(response, "View in Google Maps")

    def test_admin_request_update_page_uses_shared_appointment_calendar(self):
        preferred_date = timezone.localdate() + timedelta(days=2)
        available_date = timezone.localdate() + timedelta(days=3)
        GlobalAppointmentDate.objects.create(
            appointment_date=available_date,
            created_by=self.admin,
        )
        surrender_request = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="surrender",
            submission_type="walk_in",
            reason="stray",
            preferred_appointment_date=preferred_date,
        )

        response = self.client.get(
            reverse("dogadoption_admin:update_dog_capture_request", args=[surrender_request.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose from Active Appointment Dates")
        self.assertContains(response, preferred_date.strftime("%b %d, %Y"))
        self.assertContains(response, "dog-request-appointment-dates")

    def test_admin_can_accept_request_with_active_calendar_date(self):
        available_date = timezone.localdate() + timedelta(days=4)
        GlobalAppointmentDate.objects.create(
            appointment_date=available_date,
            created_by=self.admin,
        )
        request_record = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="capture",
            submission_type="walk_in",
            reason="stray",
        )

        response = self.client.post(
            reverse("dogadoption_admin:update_dog_capture_request", args=[request_record.id]),
            {
                "action": "accept",
                "scheduled_date": available_date.isoformat(),
                "admin_message": "Please come on the scheduled date.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        request_record.refresh_from_db()
        self.assertEqual(request_record.status, "accepted")
        self.assertIsNotNone(request_record.scheduled_date)
        self.assertEqual(timezone.localtime(request_record.scheduled_date).date(), available_date)

    def test_scheduled_requests_sort_by_date_then_barangay_before_walk_in(self):
        first_date = timezone.localdate() + timedelta(days=1)
        second_date = timezone.localdate() + timedelta(days=2)
        past_date = timezone.localdate() - timedelta(days=1)

        online_request = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="capture",
            submission_type="online",
            reason="stray",
            barangay="Caranoche",
            city="Bayawan City",
            latitude="9.123456",
            longitude="122.654321",
            status="accepted",
            scheduled_date=timezone.make_aware(datetime.combine(first_date, time(hour=9))),
        )
        walk_in_request = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="surrender",
            submission_type="walk_in",
            reason="stray",
            status="accepted",
            scheduled_date=timezone.make_aware(datetime.combine(first_date, time(hour=10))),
        )
        future_request = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="capture",
            submission_type="online",
            reason="stray",
            barangay="Bangas",
            city="Bayawan City",
            latitude="9.223456",
            longitude="122.754321",
            status="accepted",
            scheduled_date=timezone.make_aware(datetime.combine(second_date, time(hour=9))),
        )
        past_request = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="capture",
            submission_type="walk_in",
            reason="stray",
            status="accepted",
            scheduled_date=timezone.make_aware(datetime.combine(past_date, time(hour=9))),
        )

        response = self.client.get(reverse("dogadoption_admin:requests") + "?tab=accepted")

        self.assertEqual(response.status_code, 200)
        accepted_ids = [req.id for req in response.context["accepted_requests"]]
        self.assertEqual(
            accepted_ids[:4],
            [online_request.id, walk_in_request.id, future_request.id, past_request.id],
        )

    def test_bulk_mark_done_moves_scheduled_requests_to_captured(self):
        scheduled_date = timezone.localdate() + timedelta(days=2)
        selected_request = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="capture",
            submission_type="online",
            reason="stray",
            status="accepted",
            latitude="9.123456",
            longitude="122.654321",
            scheduled_date=timezone.make_aware(datetime.combine(scheduled_date, time(hour=9))),
        )
        untouched_request = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="surrender",
            submission_type="walk_in",
            reason="stray",
            status="accepted",
            scheduled_date=timezone.make_aware(datetime.combine(scheduled_date, time(hour=10))),
        )

        response = self.client.post(
            reverse("dogadoption_admin:requests"),
            {
                "action": "bulk_mark_captured",
                "selected_request_ids": [str(selected_request.id)],
                "next": reverse("dogadoption_admin:requests") + "?tab=accepted",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        selected_request.refresh_from_db()
        untouched_request.refresh_from_db()
        self.assertEqual(selected_request.status, "captured")
        self.assertEqual(untouched_request.status, "accepted")

    def test_reschedule_single_updates_scheduled_request_date(self):
        original_date = timezone.localdate() + timedelta(days=2)
        new_date = timezone.localdate() + timedelta(days=5)
        GlobalAppointmentDate.objects.create(
            appointment_date=new_date,
            created_by=self.admin,
        )
        request_record = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="capture",
            submission_type="online",
            reason="stray",
            status="accepted",
            latitude="9.123456",
            longitude="122.654321",
            scheduled_date=timezone.make_aware(datetime.combine(original_date, time(hour=9))),
        )

        response = self.client.post(
            reverse("dogadoption_admin:requests"),
            {
                "action": "reschedule_single",
                "request_id": str(request_record.id),
                "scheduled_date": new_date.isoformat(),
                "next": reverse("dogadoption_admin:requests") + "?tab=accepted",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        request_record.refresh_from_db()
        self.assertEqual(timezone.localtime(request_record.scheduled_date).date(), new_date)

    def test_bulk_reschedule_updates_all_selected_scheduled_requests(self):
        original_date = timezone.localdate() + timedelta(days=2)
        new_date = timezone.localdate() + timedelta(days=6)
        GlobalAppointmentDate.objects.create(
            appointment_date=new_date,
            created_by=self.admin,
        )
        first_request = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="capture",
            submission_type="online",
            reason="stray",
            status="accepted",
            latitude="9.123456",
            longitude="122.654321",
            scheduled_date=timezone.make_aware(datetime.combine(original_date, time(hour=9))),
        )
        second_request = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="surrender",
            submission_type="walk_in",
            reason="stray",
            status="accepted",
            scheduled_date=timezone.make_aware(datetime.combine(original_date, time(hour=10))),
        )

        response = self.client.post(
            reverse("dogadoption_admin:requests"),
            {
                "action": "bulk_reschedule",
                "selected_request_ids": [str(first_request.id), str(second_request.id)],
                "scheduled_date": new_date.isoformat(),
                "next": reverse("dogadoption_admin:requests") + "?tab=accepted",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        first_request.refresh_from_db()
        second_request.refresh_from_db()
        self.assertEqual(timezone.localtime(first_request.scheduled_date).date(), new_date)
        self.assertEqual(timezone.localtime(second_request.scheduled_date).date(), new_date)

    def test_scheduled_requests_table_shows_phone_number_and_pagination(self):
        scheduled_date = timezone.localdate() + timedelta(days=2)
        for index in range(11):
            DogCaptureRequest.objects.create(
                requested_by=self.requester,
                request_type="capture",
                submission_type="online",
                reason="stray",
                barangay=f"Barangay {index}",
                city="Bayawan City",
                latitude=f"9.12{index:04d}"[:8],
                longitude=f"122.65{index:04d}"[:10],
                status="accepted",
                scheduled_date=timezone.make_aware(datetime.combine(scheduled_date + timedelta(days=index), time(hour=9))),
            )

        response = self.client.get(reverse("dogadoption_admin:requests") + "?tab=accepted")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Phone Number")
        self.assertContains(response, "+639171234567")
        self.assertTrue(response.context["accepted_page_obj"].has_next())

    def test_admin_request_map_shows_only_pending_online_requests(self):
        pending_request = DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="capture",
            submission_type="online",
            reason="stray",
            latitude="9.123456",
            longitude="122.654321",
        )
        DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="surrender",
            submission_type="online",
            reason="stray",
            status="accepted",
            latitude="9.223456",
            longitude="122.754321",
        )
        DogCaptureRequest.objects.create(
            requested_by=self.requester,
            request_type="capture",
            submission_type="online",
            reason="stray",
            status="declined",
            latitude="9.323456",
            longitude="122.854321",
        )

        response = self.client.get(reverse("dogadoption_admin:requests"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Filter by scheduled date")
        self.assertContains(response, "Dog Capture Requests")
        self.assertContains(response, "Dog Surrender Requests")
        self.assertEqual(len(response.context["map_points"]), 1)
        self.assertEqual(response.context["map_points"][0]["id"], pending_request.id)
        self.assertEqual(response.context["map_points"][0]["request_type_key"], "capture")
