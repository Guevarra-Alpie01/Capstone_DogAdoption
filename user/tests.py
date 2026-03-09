from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from django.utils import timezone

from dogadoption_admin.models import DogAnnouncement, Post, PostRequest
from user.notification_utils import remember_request_reviewed_at
from user.models import MissingDogPost, UserAdoptionPost


class AnnouncementListBucketTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            password="secret123",
            is_staff=True,
        )
        self.user = User.objects.create_user(
            username="regular_user",
            password="secret123",
        )

        self.pinned_post = DogAnnouncement.objects.create(
            title="Pinned notice",
            content="Pinned body",
            category=DogAnnouncement.CATEGORY_DOG_ANNOUNCEMENT,
            display_bucket=DogAnnouncement.BUCKET_PINNED,
            created_by=self.admin,
        )
        self.campaign_post = DogAnnouncement.objects.create(
            title="Campaign notice",
            content="Campaign body",
            category=DogAnnouncement.CATEGORY_DOG_ANNOUNCEMENT,
            display_bucket=DogAnnouncement.BUCKET_CAMPAIGN,
            created_by=self.admin,
        )
        self.regular_post = DogAnnouncement.objects.create(
            title="Regular notice",
            content="Regular body",
            category=DogAnnouncement.CATEGORY_DOG_LAW,
            display_bucket=DogAnnouncement.BUCKET_ORDINARY,
            created_by=self.admin,
        )

    def test_user_announcement_page_uses_saved_admin_buckets(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("user:announcement_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [post.id for post in response.context["pinned_announcements"]],
            [self.pinned_post.id],
        )
        self.assertEqual(
            [post.id for post in response.context["campaign_announcements"]],
            [self.campaign_post.id],
        )
        self.assertEqual(
            [post.id for post in response.context["regular_announcements"]],
            [self.regular_post.id],
        )

    def test_campaign_posts_do_not_depend_on_category_name_matching(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("user:announcement_list"))

        self.assertEqual(response.status_code, 200)
        campaign_ids = [post.id for post in response.context["campaign_announcements"]]
        self.assertIn(self.campaign_post.id, campaign_ids)


class UserPostCreationFlowTests(TestCase):
    GIF_BYTES = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
        b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00"
        b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    )

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="poster",
            password="secret123",
        )
        self.client.force_login(self.user)

    def _image_file(self, name="dog.gif"):
        return SimpleUploadedFile(name, self.GIF_BYTES, content_type="image/gif")

    def test_home_adoption_post_redirects_with_fresh_feed_and_renders_new_post(self):
        self.client.get(reverse("user:user_home"))

        response = self.client.post(
            reverse("user:user_home"),
            {
                "home_create_post": "1",
                "post_type": "adoption",
                "dog_name": "Brownie",
                "description": "Friendly dog ready for adoption.",
                "location": "Barangay 1",
                "main_image": self._image_file(),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("feed_token=", response["Location"])
        self.assertTrue(UserAdoptionPost.objects.filter(dog_name="Brownie", owner=self.user).exists())

        follow_response = self.client.get(response["Location"])
        self.assertEqual(follow_response.status_code, 200)
        self.assertTrue(
            any(
                item["post_type"] == "user" and item["post"].dog_name == "Brownie"
                for item in follow_response.context["posts"]
            )
        )

    def test_create_post_missing_dog_redirects_with_fresh_feed_and_renders_new_post(self):
        self.client.get(reverse("user:user_home"))

        response = self.client.post(
            reverse("user:create_post"),
            {
                "post_type": "missing",
                "dog_name": "Max",
                "description": "Last seen near the plaza.",
                "image": self._image_file("missing.gif"),
                "date_lost": "2026-03-08",
                "time_lost": "09:30",
                "location": "Town Plaza",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("feed_token=", response["Location"])
        self.assertTrue(MissingDogPost.objects.filter(dog_name="Max", owner=self.user).exists())

        follow_response = self.client.get(response["Location"])
        self.assertEqual(follow_response.status_code, 200)
        self.assertTrue(
            any(
                item["post_type"] == "missing" and item["post"].dog_name == "Max"
                for item in follow_response.context["posts"]
            )
        )


class UserNotificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username="notif_admin",
            password="secret123",
            is_staff=True,
        )
        self.user = User.objects.create_user(
            username="notif_user",
            password="secret123",
        )
        self.other_user = User.objects.create_user(
            username="community_user",
            password="secret123",
        )
        self.client.force_login(self.user)

    def test_notification_context_includes_accepted_request_and_recent_posts(self):
        rescued_post = Post.objects.create(
            user=self.admin,
            caption="Admin rescued a new dog",
            location="Barangay 1",
            status="adopted",
        )
        accepted_request = PostRequest.objects.create(
            post=rescued_post,
            user=self.user,
            request_type="adopt",
            status="accepted",
        )
        remember_request_reviewed_at(accepted_request.id, timezone.now())
        announcement = DogAnnouncement.objects.create(
            title="Official update",
            content="Announcement body",
            created_by=self.admin,
        )
        community_post = UserAdoptionPost.objects.create(
            owner=self.other_user,
            dog_name="Brownie",
            description="Friendly dog",
            location="Barangay 2",
            status="available",
        )

        response = self.client.get(reverse("user:adopt_status"))

        self.assertEqual(response.status_code, 200)
        notifications = response.context["user_latest_notifications"]
        self.assertGreaterEqual(response.context["user_unread_notifications"], 1)
        self.assertTrue(any(item["kind"] == "accepted_request" for item in notifications))
        self.assertTrue(any(item["kind"] == "announcement" and str(announcement.id) in item["url"] for item in notifications))
        self.assertTrue(any(item["kind"] == "admin_post" and str(rescued_post.id) in item["url"] for item in notifications))
        self.assertTrue(any(item["kind"] == "community_post" and community_post.owner.username in item["message"] for item in notifications))
        self.assertEqual(accepted_request.scheduled_appointment_date, None)

    def test_mark_notifications_seen_clears_unread_count(self):
        rescued_post = Post.objects.create(
            user=self.admin,
            caption="Accepted request post",
            location="Barangay 3",
            status="reunited",
        )
        PostRequest.objects.create(
            post=rescued_post,
            user=self.user,
            request_type="claim",
            status="accepted",
        )
        accepted_request = PostRequest.objects.get(
            post=rescued_post,
            user=self.user,
            request_type="claim",
        )
        remember_request_reviewed_at(accepted_request.id, timezone.now())

        first_response = self.client.get(reverse("user:my_claims"))
        self.assertGreater(first_response.context["user_unread_notifications"], 0)

        mark_response = self.client.post(reverse("user:mark_notifications_seen"))
        self.assertEqual(mark_response.status_code, 200)

        second_response = self.client.get(reverse("user:my_claims"))
        self.assertEqual(second_response.context["user_unread_notifications"], 0)
