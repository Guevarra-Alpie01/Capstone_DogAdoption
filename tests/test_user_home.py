import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from dogadoption_admin.models import Post, PostImage


class UserHomeFeedTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._temp_media_root = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._temp_media_root, ignore_errors=True)
        super().tearDownClass()

    def test_logout_redirects_to_public_home_feed_with_media(self):
        with self.settings(MEDIA_ROOT=self._temp_media_root):
            staff_user = User.objects.create_user(
                username="staffuser",
                password="secret123",
                is_staff=True,
            )
            member = User.objects.create_user(
                username="memberuser",
                password="secret123",
            )
            post = Post.objects.create(
                user=staff_user,
                caption="Public Feed Dog",
                location="Bayawan",
                claim_days=3,
            )
            image = PostImage.objects.create(
                post=post,
                image=SimpleUploadedFile(
                    "public-feed-dog.jpg",
                    b"fake-image-bytes",
                    content_type="image/jpeg",
                ),
            )

            self.client.force_login(member)
            response = self.client.post(reverse("user:logout"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("user:user_home"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTemplateUsed(response, "home/user_home.html")
        self.assertContains(response, post.caption)
        self.assertContains(response, image.image.url)
