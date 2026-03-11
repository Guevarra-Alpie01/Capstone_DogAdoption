from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from django.utils import timezone

from dogadoption_admin.models import (
    Citation,
    Dog,
    DogAnnouncement,
    DogImage,
    Penalty,
    PenaltySection,
    Post,
    PostRequest,
)
from user.notification_utils import remember_request_reviewed_at
from user.models import MissingDogPost, Profile, UserAdoptionPost, UserAdoptionRequest


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


class UserToUserAdoptionRequestFlowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner_user", password="secret123")
        self.requester = User.objects.create_user(username="requester_user", password="secret123")
        Profile.objects.create(
            user=self.requester,
            address="Test Address",
            age=25,
            phone_number="09171234567",
            facebook_url="https://facebook.com/requester",
        )
        self.post = UserAdoptionPost.objects.create(
            owner=self.owner,
            dog_name="Buddy",
            description="Friendly dog",
            location="Barangay 3",
            status="available",
        )
        self.client.force_login(self.requester)

    def test_get_adopt_user_post_shows_confirmation_page(self):
        response = self.client.get(reverse("user:adopt_user_post", args=[self.post.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "adopt/adopt_user_confirm.html")
        self.assertContains(response, "Confirm Adoption Request")
        self.assertContains(response, self.post.dog_name)

    def test_post_adopt_user_post_creates_request_and_redirects_home(self):
        response = self.client.post(reverse("user:adopt_user_post", args=[self.post.id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("user:user_home"))
        self.assertTrue(
            UserAdoptionRequest.objects.filter(post=self.post, requester=self.requester).exists()
        )


class UserHomeFeedTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(
            username="feed_owner",
            password="secret123",
        )
        for index in range(14):
            UserAdoptionPost.objects.create(
                owner=self.owner,
                dog_name=f"Dog {index}",
                description=f"Friendly dog {index}",
                location="Barangay 1",
                status="available",
            )

    def test_home_feed_removes_refresh_button_and_emits_feed_token(self):
        response = self.client.get(reverse("user:user_home"))

        self.assertEqual(response.status_code, 200)
        feed_token = response.context["feed_token"]
        self.assertTrue(feed_token)
        self.assertNotContains(response, "Refresh Feed")
        self.assertNotContains(response, "refresh=1")
        self.assertContains(response, f'feed_token" value="{feed_token}"')
        self.assertContains(response, f"feed_token={feed_token}")

    def test_load_more_uses_same_feed_token_without_reshuffling_seen_posts(self):
        first_response = self.client.get(reverse("user:user_home"))
        feed_token = first_response.context["feed_token"]
        first_page_posts = {
            (item["post_type"], item["post"].id)
            for item in first_response.context["posts"]
        }

        second_response = self.client.get(
            reverse("user:user_home"),
            {"feed_token": feed_token, "page": 2},
        )

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.context["feed_token"], feed_token)
        self.assertEqual(second_response.context["page_obj"].number, 2)

        second_page_posts = {
            (item["post_type"], item["post"].id)
            for item in second_response.context["posts"]
        }
        self.assertTrue(second_page_posts)
        self.assertFalse(first_page_posts.intersection(second_page_posts))

    def test_load_more_remains_available_on_deeper_pages_for_large_feeds(self):
        for index in range(14, 180):
            UserAdoptionPost.objects.create(
                owner=self.owner,
                dog_name=f"Extra Dog {index}",
                description=f"Friendly extra dog {index}",
                location="Barangay 1",
                status="available",
            )

        first_response = self.client.get(reverse("user:user_home"))
        feed_token = first_response.context["feed_token"]
        self.assertTrue(first_response.context["page_obj"].has_next())

        deep_response = self.client.get(
            reverse("user:user_home"),
            {"feed_token": feed_token, "page": 10},
        )

        self.assertEqual(deep_response.status_code, 200)
        self.assertEqual(deep_response.context["page_obj"].number, 10)
        self.assertTrue(deep_response.context["posts"])
        self.assertTrue(deep_response.context["page_obj"].has_next())


class EditProfileRegisteredDogsTests(TestCase):
    GIF_BYTES = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
        b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00"
        b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    )

    def setUp(self):
        self.user = User.objects.create_user(
            username="profile_user",
            password="secret123",
            first_name="Jester",
            last_name="Santiago",
        )
        self.other_user = User.objects.create_user(
            username="other_owner",
            password="secret123",
        )
        self.client.force_login(self.user)

    def _image_file(self, name="registered.gif"):
        return SimpleUploadedFile(name, self.GIF_BYTES, content_type="image/gif")

    def test_edit_profile_shows_registered_dogs_linked_to_user(self):
        dog = Dog.objects.create(
            date_registered=timezone.localdate(),
            name="Rocket",
            species="Canine",
            sex="M",
            age="2 yrs",
            neutering_status="No",
            color="Brown",
            owner_name="Jester Santiago",
            owner_user=self.user,
            barangay="Bugay",
        )
        DogImage.objects.create(dog=dog, image=self._image_file())

        Dog.objects.create(
            date_registered=timezone.localdate(),
            name="Other Dog",
            species="Canine",
            sex="F",
            age="1 yr",
            neutering_status="S",
            color="Black",
            owner_name="Another Owner",
            owner_user=self.other_user,
            barangay="Banga",
        )

        response = self.client.get(reverse("user:edit_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Registered Dogs (1)")
        self.assertContains(response, "Rocket")
        self.assertNotContains(response, "Other Dog")
        self.assertEqual(response.context["registered_dogs_total"], 1)
        self.assertEqual(len(response.context["registered_dogs"]), 1)
        self.assertEqual(response.context["registered_dogs"][0]["photo_count"], 1)


class EditProfileViolationCountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="violation_user",
            password="secret123",
        )
        self.client.force_login(self.user)

        section = PenaltySection.objects.create(number=28)
        penalty_1 = Penalty.objects.create(
            section=section,
            number=1,
            title="Rabies vaccination services fee",
            amount="100.00",
        )
        penalty_2 = Penalty.objects.create(
            section=section,
            number=2,
            title="Lodging fee",
            amount="150.00",
        )

        citation_1 = Citation.objects.create(owner=self.user, penalty=penalty_1)
        citation_1.penalties.add(penalty_1, penalty_2)

        citation_2 = Citation.objects.create(owner=self.user, penalty=penalty_2)
        citation_2.penalties.add(penalty_2)

    def test_violation_total_counts_citation_tickets_not_penalties(self):
        response = self.client.get(reverse("user:edit_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["user_violation_count"], 2)
        self.assertContains(response, "Violations (2)")
        self.assertContains(response, "Total 2")


class AdminUserProfilePreviewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_preview",
            password="secret123",
            is_staff=True,
        )
        self.target_user = User.objects.create_user(
            username="target_profile",
            password="secret123",
            first_name="Target",
            last_name="User",
        )

    def test_admin_can_open_user_side_profile_preview(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("user:admin_view_user_profile", args=[self.target_user.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Target User")
        self.assertContains(response, "Posts")
        self.assertContains(response, "Registered Dogs")

    def test_non_admin_cannot_open_user_side_profile_preview(self):
        self.client.force_login(self.target_user)
        response = self.client.get(reverse("user:admin_view_user_profile", args=[self.target_user.id]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("user:login"), response.url)


class UserHomeSearchTests(TestCase):
    GIF_BYTES = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
        b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00"
        b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    )

    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user(
            username="search_staff",
            password="secret123",
            is_staff=True,
            first_name="Staff",
            last_name="Account",
        )
        self.normal_user = User.objects.create_user(
            username="pet_owner",
            password="secret123",
            first_name="Pet",
            last_name="Owner",
        )
        Post.objects.create(
            user=self.staff,
            caption="Riley",
            location="Central",
            status="rescued",
            rescued_date=timezone.localdate(),
        )
        DogAnnouncement.objects.create(
            title="Staff advisory",
            content="Official rescue update",
            created_by=self.staff,
        )
        self.user_post = UserAdoptionPost.objects.create(
            owner=self.normal_user,
            dog_name="Bingo",
            description="Friendly rescue dog",
            location="Barangay 2",
            status="available",
        )
        self.missing_post = MissingDogPost.objects.create(
            owner=self.normal_user,
            dog_name="Comet",
            description="Missing near market",
            image=self._image_file("missing-search.gif"),
            date_lost=timezone.localdate(),
            time_lost="08:30",
            location="Market road",
            status="missing",
        )

    def _image_file(self, name="search.gif"):
        return SimpleUploadedFile(name, self.GIF_BYTES, content_type="image/gif")

    def test_search_by_username_returns_posts_for_that_user(self):
        response = self.client.get(reverse("user:home_search"), {"q": "pet_owner"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["search_performed"])
        self.assertTrue(
            any(
                item["post_type"] in {"user", "missing"} and item["post"].owner_id == self.normal_user.id
                for item in response.context["posts"]
            )
        )

    def test_search_by_dog_name_returns_matching_dog_post(self):
        response = self.client.get(reverse("user:home_search"), {"q": "Bingo"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any(
                item["post_type"] == "user" and item["post"].id == self.user_post.id
                for item in response.context["posts"]
            )
        )

    def test_search_without_filters_shows_prompt_empty_state(self):
        response = self.client.get(reverse("user:home_search"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["search_performed"])
        self.assertEqual(response.context["result_count"], 0)
        self.assertContains(response, "Enter a keyword to begin searching.")


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
