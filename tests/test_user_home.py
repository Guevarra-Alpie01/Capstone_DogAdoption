import os
import shutil
import tempfile
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from dogadoption_admin.models import DogAnnouncement, Post, PostImage
from user.models import FaceImage


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

    def test_admin_logout_redirects_to_public_home_feed_with_media(self):
        with self.settings(MEDIA_ROOT=self._temp_media_root):
            staff_user = User.objects.create_user(
                username="adminstaff",
                password="secret123",
                is_staff=True,
            )
            post = Post.objects.create(
                user=staff_user,
                caption="Admin Logout Feed Dog",
                location="Bayawan",
                claim_days=3,
            )
            image = PostImage.objects.create(
                post=post,
                image=SimpleUploadedFile(
                    "admin-logout-public-feed.jpg",
                    b"fake-image-bytes",
                    content_type="image/jpeg",
                ),
            )

            self.client.force_login(staff_user)
            response = self.client.get(
                reverse("dogadoption_admin:admin_logout"),
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("user:user_home"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTemplateUsed(response, "home/user_home.html")
        self.assertContains(response, post.caption)
        self.assertContains(response, image.image.url)

    def test_guest_ajax_announcement_reaction_requests_login_modal(self):
        staff_user = User.objects.create_user(
            username="announcementstaff",
            password="secret123",
            is_staff=True,
        )
        announcement = DogAnnouncement.objects.create(
            title="Guest Like Test",
            content="Testing guest like modal behavior.",
            created_by=staff_user,
        )

        response = self.client.post(
            reverse("user:announcement_react", args=[announcement.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {
                "ok": False,
                "auth_required": True,
                "auth_modal": "login",
                "login_url": reverse("user:login"),
            },
        )

    def test_guest_ajax_admin_view_requests_login_modal_json(self):
        response = self.client.get(
            reverse("dogadoption_admin:post_list"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {
                "ok": False,
                "auth_required": True,
                "auth_modal": "login",
                "login_url": reverse("user:login"),
            },
        )

    def test_nonstaff_ajax_admin_view_redirects_to_user_home(self):
        member = User.objects.create_user(
            username="regularmember",
            password="secret123",
        )
        self.client.force_login(member)

        response = self.client.get(
            reverse("dogadoption_admin:post_list"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {
                "ok": False,
                "redirect_url": reverse("user:user_home"),
            },
        )

    def test_guest_home_claim_button_uses_login_modal_trigger(self):
        staff_user = User.objects.create_user(
            username="claimstaff",
            password="secret123",
            is_staff=True,
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Claim Modal Feed Dog",
            location="Bayawan",
            claim_days=3,
        )

        response = self.client.get(reverse("user:user_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-auth-modal-trigger="login"', html=False)
        self.assertContains(
            response,
            f'data-auth-next-url="{reverse("user:claim_confirm", args=[post.id])}?return_to=home"',
            html=False,
        )

    def test_guest_claim_confirm_preserves_home_return_to_in_login_redirect(self):
        staff_user = User.objects.create_user(
            username="claimreturnstaff",
            password="secret123",
            is_staff=True,
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Claim Return Dog",
            location="Bayawan",
            claim_days=3,
        )
        claim_url = f'{reverse("user:claim_confirm", args=[post.id])}?return_to=home'

        response = self.client.get(claim_url)

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response["Location"])
        self.assertEqual(parsed.path, reverse("user:user_home"))
        self.assertEqual(parse_qs(parsed.query).get("auth_modal"), ["login"])
        self.assertEqual(parse_qs(parsed.query).get("next"), [claim_url])

    def test_guest_claim_confirm_redirects_to_home_with_login_modal(self):
        staff_user = User.objects.create_user(
            username="claimredirectstaff",
            password="secret123",
            is_staff=True,
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Claim Redirect Dog",
            location="Bayawan",
            claim_days=3,
        )
        claim_url = reverse("user:claim_confirm", args=[post.id])

        response = self.client.get(claim_url)

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response["Location"])
        self.assertEqual(parsed.path, reverse("user:user_home"))
        self.assertEqual(parse_qs(parsed.query).get("auth_modal"), ["login"])
        self.assertEqual(parse_qs(parsed.query).get("next"), [claim_url])

    def test_login_redirects_to_safe_claim_next_url(self):
        staff_user = User.objects.create_user(
            username="claimnextstaff",
            password="secret123",
            is_staff=True,
        )
        member = User.objects.create_user(
            username="claimmember",
            password="secret123",
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Claim Next Dog",
            location="Bayawan",
            claim_days=3,
        )
        claim_url = reverse("user:claim_confirm", args=[post.id])

        response = self.client.post(
            reverse("user:login"),
            {
                "username": member.username,
                "password": "secret123",
                "next": claim_url,
            },
        )

        self.assertRedirects(response, claim_url, fetch_redirect_response=False)

    def test_claim_confirm_cancel_returns_home_only_for_home_origin(self):
        staff_user = User.objects.create_user(
            username="claimcancelstaff",
            password="secret123",
            is_staff=True,
        )
        member = User.objects.create_user(
            username="claimcancelmember",
            password="secret123",
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Claim Cancel Home Dog",
            location="Bayawan",
            claim_days=3,
        )
        self.client.force_login(member)

        response = self.client.get(f'{reverse("user:claim_confirm", args=[post.id])}?return_to=home')

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("user:user_home")}" class="btn btn-claim-cancel"',
            html=False,
        )

    def test_claim_confirm_cancel_stays_on_claim_list_without_home_origin(self):
        staff_user = User.objects.create_user(
            username="claimlistcancelstaff",
            password="secret123",
            is_staff=True,
        )
        member = User.objects.create_user(
            username="claimlistcancelmember",
            password="secret123",
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Claim Cancel List Dog",
            location="Bayawan",
            claim_days=3,
        )
        self.client.force_login(member)

        response = self.client.get(reverse("user:claim_confirm", args=[post.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("user:claim_list")}" class="btn btn-claim-cancel"',
            html=False,
        )

    def test_claim_list_claim_button_does_not_include_home_return_to(self):
        staff_user = User.objects.create_user(
            username="claimlistbuttonstaff",
            password="secret123",
            is_staff=True,
        )
        member = User.objects.create_user(
            username="claimlistbuttonmember",
            password="secret123",
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Claim List Button Dog",
            location="Bayawan",
            claim_days=3,
        )
        self.client.force_login(member)

        response = self.client.get(reverse("user:claim_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("user:claim_confirm", args=[post.id])}" class="btn-action"',
            html=False,
        )

    def test_modal_login_error_re_renders_home_with_login_popup(self):
        staff_user = User.objects.create_user(
            username="claimloginerrorstaff",
            password="secret123",
            is_staff=True,
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Claim Modal Login Error Dog",
            location="Bayawan",
            claim_days=3,
        )
        claim_url = reverse("user:claim_confirm", args=[post.id])

        response = self.client.post(
            reverse("user:login"),
            {
                "username": "wronguser",
                "password": "wrongpass",
                "next": claim_url,
                "auth_source": "modal",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home/user_home.html")
        self.assertContains(response, "Invalid username or password")
        self.assertContains(response, f'value="{claim_url}"', html=False)

    def test_modal_signup_error_re_renders_home_with_signup_popup(self):
        staff_user = User.objects.create_user(
            username="claimsignuperrorstaff",
            password="secret123",
            is_staff=True,
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Claim Modal Signup Error Dog",
            location="Bayawan",
            claim_days=3,
        )
        claim_url = reverse("user:claim_confirm", args=[post.id])

        response = self.client.post(
            reverse("user:signup"),
            {
                "username": "",
                "password": "secret123A!",
                "confirm_password": "secret123A!",
                "first_name": "Guest",
                "last_name": "User",
                "address": "Tinago",
                "next": claim_url,
                "auth_source": "modal",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home/user_home.html")
        self.assertContains(response, "Username is required.")
        self.assertContains(response, f'value="{claim_url}"', html=False)

    def test_signup_complete_redirects_to_public_home_feed(self):
        with self.settings(MEDIA_ROOT=self._temp_media_root):
            temp_faces_dir = os.path.join(self._temp_media_root, "temp_faces")
            os.makedirs(temp_faces_dir, exist_ok=True)

            saved_paths = []
            for idx in range(4):
                relative_path = f"temp_faces/signup-test-{idx}.png"
                absolute_path = os.path.join(temp_faces_dir, f"signup-test-{idx}.png")
                with open(absolute_path, "wb") as handle:
                    handle.write(b"fake-face-image-bytes")
                saved_paths.append(relative_path)

            session = self.client.session
            session["signup_data"] = {
                "username": "freshsignupuser",
                "password": "Secret123!x",
                "first_name": "Fresh",
                "last_name": "Signup",
                "middle_initial": "",
                "address": "Tinago",
                "age": 18,
                "consent_given": False,
            }
            session["face_images_files"] = saved_paths
            session.save()

            response = self.client.post(
                reverse("user:signup_complete"),
                {"agree_terms": "1"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("user:user_home"))
        self.assertTemplateUsed(response, "home/user_home.html")
        self.assertContains(response, "Account created successfully. Please log in.")
        self.assertTrue(User.objects.filter(username="freshsignupuser").exists())
        self.assertEqual(FaceImage.objects.filter(user__username="freshsignupuser").count(), 4)
