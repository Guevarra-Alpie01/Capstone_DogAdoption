import os
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from dogadoption_admin.barangays import BAYAWAN_BARANGAYS
from dogadoption_admin.models import DogAnnouncement, Post, PostImage
from user.models import Profile, UserAdoptionPost


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

    def test_guest_can_open_announcement_pages_without_react_controls(self):
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

        list_response = self.client.get(reverse("user:announcement_list"))
        detail_response = self.client.get(reverse("user:announcement_detail", args=[announcement.id]))

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(list_response, announcement.title)
        self.assertContains(detail_response, announcement.title)
        self.assertNotContains(list_response, "React")
        self.assertNotContains(detail_response, "React")

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

    def test_guest_home_claim_button_opens_login_modal(self):
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
        self.assertContains(
            response,
            'data-auth-modal-trigger="login"',
            html=False,
        )
        self.assertContains(
            response,
            'data-auth-next-url="/user/claim/',
            html=False,
        )
        self.assertContains(
            response,
            '?return_to=home"',
            html=False,
        )

    def test_home_feed_excludes_admin_announcements_and_uses_date_only_headers(self):
        staff_user = User.objects.create_user(
            username="feedstaff",
            password="secret123",
            is_staff=True,
        )
        member = User.objects.create_user(
            username="feedmember",
            password="secret123",
            first_name="Feed",
            last_name="Member",
        )
        Post.objects.create(
            user=staff_user,
            caption="Visible Rescue Dog",
            location="Bayawan",
            claim_days=3,
        )
        UserAdoptionPost.objects.create(
            owner=member,
            dog_name="Friendly Pup",
            location="Mabigo",
            description="Healthy and ready for adoption.",
        )
        DogAnnouncement.objects.create(
            title="Hidden Announcement",
            content="Announcement content that should stay off the home feed.",
            created_by=staff_user,
        )
        cache.clear()

        response = self.client.get(reverse("user:user_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visible Rescue Dog")
        self.assertContains(response, "Friendly Pup")
        self.assertNotContains(response, "Announcement content that should stay off the home feed.")
        self.assertContains(response, 'class="post-author post-author--date-only"', html=False)
        self.assertNotContains(response, "author-avatar-img", html=False)
        self.assertNotContains(response, 'class="author-name"', html=False)

    def test_home_page_renders_claim_and_adopt_featured_carousels(self):
        staff_user = User.objects.create_user(
            username="carouselstaff",
            password="secret123",
            is_staff=True,
        )
        claim_post = Post.objects.create(
            user=staff_user,
            caption="Claim Carousel Dog",
            breed="golden_retriever",
            location="Villareal",
            claim_days=3,
        )
        adopt_post = Post.objects.create(
            user=staff_user,
            caption="Adopt Carousel Dog",
            breed="beagle",
            location="Mabigo",
            claim_days=1,
        )
        Post.objects.filter(pk=adopt_post.pk).update(
            created_at=timezone.now() - timedelta(days=2)
        )
        adopt_post.refresh_from_db()
        claim_deadline_label = timezone.localtime(claim_post.claim_deadline()).strftime("%b %d, %Y")

        response = self.client.get(reverse("user:user_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Claim Dog")
        self.assertContains(response, "Adopt Dog")
        self.assertContains(response, claim_post.display_breed)
        self.assertContains(response, adopt_post.display_breed)
        self.assertContains(response, f'href="{reverse("user:claim_list")}"', html=False)
        self.assertContains(response, f'href="{reverse("user:adopt_list")}"', html=False)
        self.assertContains(response, "home-carousel-claim-1")
        self.assertContains(response, "home-carousel-adopt-1")
        self.assertContains(response, "View Details")
        self.assertContains(response, "Open Post Page")
        self.assertContains(response, "data-dog-detail-toggle", html=False)
        self.assertContains(response, "data-dog-detail-panel", html=False)
        self.assertContains(response, "Barangay")
        self.assertContains(response, "Claim Ends")
        self.assertContains(response, claim_deadline_label)

    def test_search_results_claim_posts_show_reserve_adoption_action(self):
        staff_user = User.objects.create_user(
            username="reservehomefeedstaff",
            password="secret123",
            is_staff=True,
        )
        member = User.objects.create_user(
            username="reservehomefeedmember",
            password="secret123",
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Reserve Home Feed Dog",
            location="Bayawan",
            claim_days=3,
        )
        self.client.force_login(member)

        response = self.client.get(
            reverse("user:home_search"),
            {"q": "Reserve"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reserve Adoption")
        self.assertContains(
            response,
            f'href="{reverse("user:adopt_confirm", args=[post.id])}?return_to=home"',
            html=False,
        )

    def test_guest_home_renders_mobile_navbar_actions(self):
        response = self.client.get(reverse("user:user_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="sidebarToggle"', html=False)
        self.assertContains(response, 'class="d-flex align-items-center gap-2 user-topbar-auth-actions"', html=False)
        self.assertContains(response, f'href="{reverse("user:login")}" class="auth-btn login-btn border-0"', html=False)
        self.assertContains(response, f'href="{reverse("user:signup")}" class="auth-btn signup-btn border-0"', html=False)

    def test_guest_claim_confirm_preserves_home_return_to_in_login_modal_redirect(self):
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

    def test_guest_adopt_confirm_preserves_home_return_to_in_login_modal_redirect(self):
        staff_user = User.objects.create_user(
            username="adoptreturnstaff",
            password="secret123",
            is_staff=True,
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Adopt Return Dog",
            location="Bayawan",
            claim_days=3,
        )
        adopt_url = f'{reverse("user:adopt_confirm", args=[post.id])}?return_to=home'

        response = self.client.get(adopt_url)

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response["Location"])
        self.assertEqual(parsed.path, reverse("user:user_home"))
        self.assertEqual(parse_qs(parsed.query).get("auth_modal"), ["login"])
        self.assertEqual(parse_qs(parsed.query).get("next"), [adopt_url])

    def test_guest_claim_confirm_redirects_to_home_login_modal(self):
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

    def test_guest_can_open_find_a_dog_listing_without_login(self):
        staff_user = User.objects.create_user(
            username="guestfinderstaff",
            password="secret123",
            is_staff=True,
        )
        Post.objects.create(
            user=staff_user,
            caption="Guest Finder Dog",
            location="Bayawan",
            claim_days=3,
        )

        response = self.client.get(reverse("user:claim_list"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "adopt/adopt_list.html")
        self.assertContains(response, "Dog Rescue Finder")
        self.assertContains(response, 'data-auth-modal-trigger="login"', html=False)

    def test_guest_can_open_post_detail_without_login(self):
        staff_user = User.objects.create_user(
            username="guestdetailstaff",
            password="secret123",
            is_staff=True,
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Guest Detail Dog",
            location="Bayawan",
            claim_days=3,
        )

        response = self.client.get(reverse("user:post_detail", args=[post.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home/post_detail.html")
        self.assertContains(response, "Guest Detail Dog")
        self.assertContains(response, "Back to feed")

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
            f'href="{reverse("user:claim_confirm", args=[post.id])}"',
            html=False,
        )
        self.assertNotContains(response, 'data-auth-modal-trigger="login"', html=False)

    def test_claim_list_shows_reserve_adoption_button_for_claim_phase_posts(self):
        staff_user = User.objects.create_user(
            username="claimlistreservestaff",
            password="secret123",
            is_staff=True,
        )
        member = User.objects.create_user(
            username="claimlistreservemember",
            password="secret123",
        )
        post = Post.objects.create(
            user=staff_user,
            caption="Claim List Reserve Dog",
            location="Bayawan",
            claim_days=3,
        )
        self.client.force_login(member)

        response = self.client.get(reverse("user:claim_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reserve Adoption")
        self.assertContains(
            response,
            f'href="{reverse("user:adopt_confirm", args=[post.id])}"',
            html=False,
        )

    def test_adopt_list_defaults_to_adoption_phase_in_rescue_finder(self):
        staff_user = User.objects.create_user(
            username="finderadoptstaff",
            password="secret123",
            is_staff=True,
        )
        member = User.objects.create_user(
            username="finderadoptmember",
            password="secret123",
        )
        claim_post = Post.objects.create(
            user=staff_user,
            caption="Claim Window Dog",
            location="Bayawan",
            breed="beagle",
            age_group="young",
            size_group="medium",
            gender="male",
            claim_days=3,
        )
        adopt_post = Post.objects.create(
            user=staff_user,
            caption="Adoption Window Dog",
            location="Tinago",
            breed="labrador",
            age_group="adult",
            size_group="large",
            gender="female",
            claim_days=3,
        )
        Post.objects.filter(id=adopt_post.id).update(
            created_at=timezone.now() - timedelta(days=4)
        )
        self.client.force_login(member)

        response = self.client.get(reverse("user:adopt_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="purpose"', html=False)
        self.assertEqual(response.context["current_purpose"], "adopt")
        self.assertEqual(len(response.context["posts"]), 1)
        self.assertEqual(response.context["posts"][0]["post"].id, adopt_post.id)
        self.assertNotEqual(response.context["posts"][0]["post"].id, claim_post.id)

    def test_claim_list_filter_preferences_sort_best_match_first(self):
        staff_user = User.objects.create_user(
            username="finderclaimstaff",
            password="secret123",
            is_staff=True,
        )
        member = User.objects.create_user(
            username="finderclaimmember",
            password="secret123",
        )
        matching_post = Post.objects.create(
            user=staff_user,
            caption="Labrador Match",
            location="Bayawan Proper",
            breed="labrador",
            age_group="adult",
            size_group="large",
            gender="male",
            coat_length="short",
            colors=["black"],
            claim_days=3,
        )
        non_matching_post = Post.objects.create(
            user=staff_user,
            caption="Beagle Mismatch",
            location="Villareal",
            breed="beagle",
            age_group="young",
            size_group="small",
            gender="female",
            coat_length="medium",
            colors=["tricolor"],
            claim_days=3,
        )
        self.client.force_login(member)

        response = self.client.get(
            reverse("user:claim_list"),
            {
                "purpose": "all",
                "breed": "labrador",
                "gender": "male",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_purpose"], "all")
        self.assertEqual(response.context["posts"][0]["post"].id, matching_post.id)
        self.assertEqual(response.context["active_filter_count"], 2)
        self.assertTrue(response.context["recommended_posts"])
        self.assertEqual(response.context["recommended_posts"][0]["post"].id, matching_post.id)
        self.assertNotEqual(response.context["posts"][0]["post"].id, non_matching_post.id)

    def test_claim_list_location_filter_displays_all_28_barangays(self):
        staff_user = User.objects.create_user(
            username="finderlocationstaff",
            password="secret123",
            is_staff=True,
        )
        member = User.objects.create_user(
            username="finderlocationmember",
            password="secret123",
        )
        Post.objects.create(
            user=staff_user,
            caption="Bugay Dog",
            location="Bugay",
            claim_days=3,
        )
        self.client.force_login(member)

        response = self.client.get(reverse("user:claim_list"))

        self.assertEqual(response.status_code, 200)
        location_section = next(
            section
            for section in response.context["filter_sections"]
            if section["key"] == "location"
        )
        self.assertEqual(len(location_section["options"]), 28)
        self.assertEqual(
            [option["value"] for option in location_section["options"]],
            list(BAYAWAN_BARANGAYS),
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

    def test_login_page_shows_google_button_markup_when_configured(self):
        with self.settings(
            GOOGLE_CLIENT_ID="test-google-client-id.apps.googleusercontent.com",
        ):
            response = self.client.get(reverse("user:login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "login.html")
        self.assertContains(response, 'data-google-auth-button', html=False)
        self.assertContains(
            response,
            'data-google-client-id="test-google-client-id.apps.googleusercontent.com"',
            html=False,
        )
        self.assertContains(response, "https://accounts.google.com/gsi/client", html=False)
        self.assertNotContains(response, "Google sign-in is not configured yet.", html=False)

    def test_login_page_shows_google_config_message_when_client_id_missing(self):
        with self.settings(GOOGLE_CLIENT_ID=""):
            response = self.client.get(reverse("user:login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "login.html")
        self.assertContains(
            response,
            "Google sign-in is not configured yet. Add",
            html=False,
        )
        self.assertNotContains(response, 'data-google-auth-button', html=False)
        self.assertNotContains(response, "https://accounts.google.com/gsi/client", html=False)

    def test_signup_requires_google_credential(self):
        response = self.client.post(
            reverse("user:signup"),
            {
                "username": "freshsignupuser",
                "password": "Secret123!x",
                "confirm_password": "Secret123!x",
                "first_name": "Fresh",
                "last_name": "Signup",
                "address": "Tinago",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "signup.html")
        self.assertContains(response, "Sign up with Google is required to finish creating your account.")
        self.assertFalse(User.objects.filter(username="freshsignupuser").exists())

    @patch(
        "user.views._verify_google_signup_credential",
        return_value={
            "email": "freshsignup@example.com",
            "sub": "google-sub-123",
            "given_name": "Fresh",
            "family_name": "Signup",
        },
    )
    def test_signup_sends_verification_email_and_blocks_login(self, mocked_google_verify):
        response = self.client.post(
            reverse("user:signup"),
            {
                "username": "freshsignupuser",
                "password": "Secret123!x",
                "confirm_password": "Secret123!x",
                "first_name": "Fresh",
                "last_name": "Signup",
                "address": "Tinago",
                "google_credential": "mock-google-id-token",
            },
            follow=True,
        )

        mocked_google_verify.assert_called_once_with("mock-google-id-token")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("user:login"))
        self.assertTemplateUsed(response, "login.html")
        self.assertContains(
            response,
            "Account created for freshsignup@example.com. Check your email to verify your account before logging in.",
        )

        user = User.objects.get(username="freshsignupuser")
        self.assertEqual(user.email, "freshsignup@example.com")
        self.assertFalse(user.is_active)
        self.assertFalse(user.profile.email_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(user.email, mail.outbox[0].to)
        self.assertIn("/user/verify-email/", mail.outbox[0].body)

        login_response = self.client.post(
            reverse("user:login"),
            {
                "username": "freshsignupuser",
                "password": "Secret123!x",
            },
        )

        self.assertEqual(login_response.status_code, 200)
        self.assertContains(login_response, "Please verify your email address before logging in.")

    @patch(
        "user.views._verify_google_login_credential",
        return_value={
            "email": "googlelogin@example.com",
            "sub": "google-login-sub-123",
            "given_name": "Google",
            "family_name": "Login",
        },
    )
    def test_google_login_logs_in_existing_user_directly(self, mocked_google_verify):
        user = User.objects.create_user(
            username="googleloginuser",
            password="Secret123!x",
            first_name="Google",
            last_name="Login",
            email="googlelogin@example.com",
            is_active=False,
        )
        Profile.objects.create(
            user=user,
            address="Tinago",
            age=18,
            consent_given=True,
            email_verified=False,
        )

        response = self.client.post(
            reverse("user:login"),
            {
                "google_credential": "mock-google-login-token",
            },
        )

        mocked_google_verify.assert_called_once_with("mock-google-login-token")
        self.assertRedirects(response, reverse("user:user_home"), fetch_redirect_response=False)

        user.refresh_from_db()
        user.profile.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.profile.email_verified)
        self.assertEqual(self.client.session.get("_auth_user_id"), str(user.pk))

    @patch(
        "user.views._verify_google_login_credential",
        return_value={
            "email": "newgooglelogin@example.com",
            "sub": "google-login-sub-456",
            "given_name": "New",
            "family_name": "Google",
        },
    )
    def test_google_login_redirects_new_user_to_signup_with_session(self, mocked_google_verify):
        response = self.client.post(
            reverse("user:login"),
            {
                "google_credential": "mock-google-login-token",
            },
            follow=True,
        )

        mocked_google_verify.assert_called_once_with("mock-google-login-token")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("user:signup"))
        self.assertTemplateUsed(response, "signup.html")
        self.assertContains(response, "You are already using your Google account.")

        social_signup_data = self.client.session.get("google_signup_data") or {}
        self.assertEqual(social_signup_data.get("email"), "newgooglelogin@example.com")
        self.assertTrue(social_signup_data.get("username"))

    @patch(
        "user.views._verify_google_login_credential",
        return_value={
            "email": "redirectlogin@example.com",
            "sub": "google-login-sub-789",
            "given_name": "Redirect",
            "family_name": "Login",
        },
    )
    def test_google_redirect_login_logs_in_existing_user_directly(self, mocked_google_verify):
        user = User.objects.create_user(
            username="redirectgoogleloginuser",
            password="Secret123!x",
            first_name="Redirect",
            last_name="Login",
            email="redirectlogin@example.com",
            is_active=False,
        )
        Profile.objects.create(
            user=user,
            address="Tinago",
            age=18,
            consent_given=True,
            email_verified=False,
        )

        self.client.cookies["g_csrf_token"] = "csrf-token-123"
        response = self.client.post(
            reverse("user:google_auth_login"),
            {
                "credential": "mock-google-login-token",
                "g_csrf_token": "csrf-token-123",
            },
        )

        mocked_google_verify.assert_called_once_with("mock-google-login-token")
        self.assertRedirects(response, reverse("user:user_home"), fetch_redirect_response=False)

        user.refresh_from_db()
        user.profile.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.profile.email_verified)
        self.assertEqual(self.client.session.get("_auth_user_id"), str(user.pk))

    @patch(
        "user.views._verify_google_login_credential",
        return_value={
            "email": "redirectnew@example.com",
            "sub": "google-login-sub-790",
            "given_name": "Redirect",
            "family_name": "New",
        },
    )
    def test_google_redirect_login_bridges_new_user_to_signup(self, mocked_google_verify):
        self.client.cookies["g_csrf_token"] = "csrf-token-456"
        response = self.client.post(
            reverse("user:google_auth_login"),
            {
                "credential": "mock-google-login-token",
                "g_csrf_token": "csrf-token-456",
            },
            follow=True,
        )

        mocked_google_verify.assert_called_once_with("mock-google-login-token")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("user:signup"))
        self.assertTemplateUsed(response, "signup.html")
        self.assertContains(response, "You are already using your Google account.")

        social_signup_data = self.client.session.get("google_signup_data") or {}
        self.assertEqual(social_signup_data.get("email"), "redirectnew@example.com")
        self.assertTrue(social_signup_data.get("username"))

    def test_google_signup_session_can_complete_without_reverifying_token(self):
        session = self.client.session
        session["google_signup_data"] = {
            "email": "sessiongoogle@example.com",
            "google_sub": "google-session-sub-789",
            "first_name": "Session",
            "last_name": "Google",
            "full_name": "Session Google",
            "username": "sessiongoogle",
        }
        session.save()

        response = self.client.post(
            reverse("user:signup"),
            {
                "username": "sessiongoogleuser",
                "password": "Secret123!x",
                "confirm_password": "Secret123!x",
                "first_name": "Session",
                "last_name": "Google",
                "address": "Tinago",
            },
        )

        self.assertRedirects(response, reverse("user:login"), fetch_redirect_response=False)

        user = User.objects.get(username="sessiongoogleuser")
        self.assertEqual(user.email, "sessiongoogle@example.com")
        self.assertFalse(user.is_active)
        self.assertFalse(user.profile.email_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(user.email, mail.outbox[0].to)
        self.assertNotIn("google_signup_data", self.client.session)

    def test_verify_email_activates_user_and_allows_login(self):
        user = User.objects.create_user(
            username="verifyme",
            password="Secret123!x",
            first_name="Verify",
            last_name="Me",
            email="verifyme@example.com",
            is_active=False,
        )
        Profile.objects.create(
            user=user,
            address="Tinago",
            age=18,
            consent_given=True,
            email_verified=False,
        )

        verification_url = reverse(
            "user:verify_email",
            args=[
                urlsafe_base64_encode(force_bytes(user.pk)),
                default_token_generator.make_token(user),
            ],
        )

        response = self.client.get(verification_url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("user:login"))
        self.assertContains(response, "Email verified. You can now log in.")

        user.refresh_from_db()
        user.profile.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.profile.email_verified)

        login_response = self.client.post(
            reverse("user:login"),
            {
                "username": "verifyme",
                "password": "Secret123!x",
            },
        )

        self.assertRedirects(login_response, reverse("user:user_home"), fetch_redirect_response=False)
