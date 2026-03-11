from datetime import datetime

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from django.templatetags.static import static
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    AdminNotification,
    Barangay,
    Citation,
    DewormingTreatmentRecord,
    Dog,
    DogImage,
    DogAnnouncement,
    DogRegistration,
    Penalty,
    PenaltySection,
    Post,
    PostRequest,
    VaccinationRecord,
)
from user.models import Profile


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
