from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import DogAnnouncement


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
