from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from dogadoption_admin.models import DogAnnouncement


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
