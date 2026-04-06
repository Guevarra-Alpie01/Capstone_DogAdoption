from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from dogadoption_admin.models import GlobalAppointmentDate, Post, PostRequest


class PostRequestVerificationWindowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_user(
            username="verificationadmin",
            password="Secret123!",
            is_staff=True,
        )
        cls.first_member = User.objects.create_user(
            username="verificationmember1",
            password="Secret123!",
        )
        cls.second_member = User.objects.create_user(
            username="verificationmember2",
            password="Secret123!",
        )

    def setUp(self):
        cache.clear()
        self.appointment_date = timezone.localdate() + timedelta(days=2)
        GlobalAppointmentDate.objects.bulk_create(
            [
                GlobalAppointmentDate(
                    appointment_date=timezone.localdate() + timedelta(days=offset),
                    is_active=True,
                )
                for offset in range(-7, 15)
            ],
            ignore_conflicts=True,
        )
        self.flow_config = {
            "claim": {
                "confirm_route": "user:claim_confirm",
                "list_route": "user:claim_list",
                "history_route": "user:my_claims",
                "admin_bucket": "claim_posts",
                "accepted_post_status": "reunited",
                "initial_created_at": lambda now: now,
                "expired_created_at": lambda now: now - timedelta(days=1, hours=1),
                "home_action_url": lambda post_id: (
                    f'{reverse("user:claim_confirm", args=[post_id])}?return_to=home'
                ),
            },
            "adopt": {
                "confirm_route": "user:adopt_confirm",
                "list_route": "user:adopt_list",
                "history_route": "user:adopt_status",
                "admin_bucket": "adoption_posts",
                "accepted_post_status": "adopted",
                "initial_created_at": lambda now: now - timedelta(days=2),
                "expired_created_at": lambda now: now - timedelta(days=4, hours=1),
                "home_action_url": lambda post_id: reverse(
                    "user:adopt_confirm",
                    args=[post_id],
                ),
            },
        }

    def _client_for(self, user):
        client = Client()
        client.force_login(user)
        return client

    def _create_post(self, flow, *, created_at, claim_days=1):
        post = Post.objects.create(
            user=self.admin_user,
            caption=f"{flow.title()} Verification Dog",
            location="Bayawan",
            claim_days=claim_days,
        )
        Post.objects.filter(pk=post.pk).update(created_at=created_at)
        post.refresh_from_db()
        return post

    def _submit_request(self, flow, user, post):
        client = self._client_for(user)
        response = client.post(
            reverse(self.flow_config[flow]["confirm_route"], args=[post.id]),
            {"appointment_date": self.appointment_date.isoformat()},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.request["PATH_INFO"],
            reverse(self.flow_config[flow]["history_route"]),
        )
        return PostRequest.objects.get(
            user=user,
            post=post,
            request_type=flow,
        )

    def _set_created_at(self, model, obj_id, created_at):
        model.objects.filter(pk=obj_id).update(created_at=created_at)

    def _find_item(self, items, post_id):
        return next(item for item in items if item["post"].id == post_id)

    def _item_ids(self, items):
        return [item["post"].id for item in items]

    def _admin_feed_ids(self, items):
        return [
            item["post"].id
            for item in items
            if item.get("post_type") == "admin"
        ]

    def test_adoption_can_be_reserved_during_claim_phase(self):
        now = timezone.now()
        post = self._create_post(
            "claim",
            created_at=now,
            claim_days=2,
        )
        member_client = self._client_for(self.first_member)
        confirm_url = reverse("user:adopt_confirm", args=[post.id])

        get_response = member_client.get(confirm_url)

        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Reserve Adoption")
        self.assertContains(get_response, "in case the dog is not claimed by an owner")

        submit_response = member_client.post(
            confirm_url,
            {"appointment_date": self.appointment_date.isoformat()},
            follow=True,
        )

        self.assertEqual(submit_response.status_code, 200)
        self.assertEqual(
            submit_response.request["PATH_INFO"],
            reverse("user:adopt_status"),
        )

        request_record = PostRequest.objects.get(
            user=self.first_member,
            post=post,
            request_type="adopt",
        )
        self.assertEqual(request_record.status, "pending")
        self.assertEqual(request_record.approval_available_at, post.adoption_deadline())

    def test_pending_claim_requests_move_into_adoption_without_leaving_admin_review(self):
        now = timezone.now()
        post = self._create_post(
            "claim",
            created_at=self.flow_config["claim"]["initial_created_at"](now),
        )
        claim_request = self._submit_request("claim", self.first_member, post)
        self._set_created_at(
            PostRequest,
            claim_request.id,
            now - PostRequest.verification_window() - timedelta(hours=2),
        )
        self._set_created_at(
            Post,
            post.id,
            self.flow_config["claim"]["expired_created_at"](now),
        )
        post.refresh_from_db()

        member_client = self._client_for(self.second_member)

        claim_list_response = member_client.get(reverse("user:claim_list"))
        self.assertNotIn(post.id, self._item_ids(claim_list_response.context["posts"]))

        adopt_list_response = member_client.get(reverse("user:adopt_list"))
        adopt_item = self._find_item(adopt_list_response.context["posts"], post.id)
        self.assertEqual(adopt_item["phase"], "adopt")
        self.assertFalse(adopt_item["is_pending_review"])
        self.assertEqual(adopt_item["action_label"], "Adopt")
        self.assertContains(adopt_list_response, post.display_title)

        home_response = member_client.get(reverse("user:user_home"))
        home_item = self._find_item(home_response.context["posts"], post.id)
        self.assertEqual(home_item["post_type"], "admin")
        self.assertEqual(home_item["phase"], "adopt")
        self.assertFalse(home_item["is_pending_review"])

        self._submit_request("adopt", self.second_member, post)
        self.assertEqual(
            PostRequest.objects.filter(
                post=post,
                request_type="claim",
                status="pending",
            ).count(),
            1,
        )
        self.assertEqual(
            PostRequest.objects.filter(
                post=post,
                request_type="adopt",
                status="pending",
            ).count(),
            1,
        )

        admin_client = self._client_for(self.admin_user)
        dashboard_response = admin_client.get(reverse("dogadoption_admin:post_list"))
        self.assertIn(post.id, self._item_ids(dashboard_response.context["claim_posts"]))
        self.assertIn(post.id, self._item_ids(dashboard_response.context["adoption_posts"]))

    def test_expired_pending_adoption_stays_on_admin_dashboard_but_leaves_public_feeds(self):
        now = timezone.now()
        post = self._create_post(
            "adopt",
            created_at=self.flow_config["adopt"]["initial_created_at"](now),
        )
        request_record = self._submit_request("adopt", self.first_member, post)
        self._set_created_at(
            PostRequest,
            request_record.id,
            now - PostRequest.verification_window() - timedelta(hours=2),
        )
        self._set_created_at(
            Post,
            post.id,
            self.flow_config["adopt"]["expired_created_at"](now),
        )
        post.refresh_from_db()

        member_client = self._client_for(self.first_member)

        adopt_list_response = member_client.get(reverse("user:adopt_list"))
        self.assertNotIn(post.id, self._item_ids(adopt_list_response.context["posts"]))

        home_response = member_client.get(reverse("user:user_home"))
        self.assertNotIn(post.id, self._admin_feed_ids(home_response.context["posts"]))

        admin_client = self._client_for(self.admin_user)
        dashboard_response = admin_client.get(reverse("dogadoption_admin:post_list"))
        dashboard_item = self._find_item(
            dashboard_response.context["adoption_posts"],
            post.id,
        )
        self.assertTrue(dashboard_item["is_pending_review"])
        self.assertFalse(dashboard_item["show_countdown"])
        self.assertContains(dashboard_response, post.display_title)

    def test_admin_cannot_accept_requests_before_phase_review_opens_even_if_request_is_old_enough(self):
        now = timezone.now()
        admin_client = self._client_for(self.admin_user)

        cases = [
            {
                "flow": "claim",
                "post_created_at": now - timedelta(days=2),
                "request_created_at": now - timedelta(days=2),
                "claim_days": 3,
            },
            {
                "flow": "adopt",
                "post_created_at": now - timedelta(days=2),
                "request_created_at": now - timedelta(days=2),
                "claim_days": 1,
            },
        ]

        for case in cases:
            with self.subTest(flow=case["flow"]):
                post = self._create_post(
                    case["flow"],
                    created_at=case["post_created_at"],
                    claim_days=case["claim_days"],
                )
                request_record = self._submit_request(case["flow"], self.first_member, post)
                self._set_created_at(
                    PostRequest,
                    request_record.id,
                    case["request_created_at"],
                )
                request_record.refresh_from_db()

                dashboard_response = admin_client.get(reverse("dogadoption_admin:post_list"))
                dashboard_item = self._find_item(
                    dashboard_response.context[self.flow_config[case["flow"]]["admin_bucket"]],
                    post.id,
                )
                self.assertTrue(dashboard_item["is_pending_review"])
                self.assertFalse(dashboard_item["show_countdown"])
                self.assertContains(dashboard_response, "Accept after")
                self.assertContains(dashboard_response, "Verification until")
                self.assertEqual(
                    request_record.approval_available_at,
                    post.claim_deadline() if case["flow"] == "claim" else post.adoption_deadline(),
                )

                response = admin_client.post(
                    reverse(
                        "dogadoption_admin:update_request",
                        args=[request_record.id, "accept"],
                    ),
                    follow=True,
                )

                request_record.refresh_from_db()
                post.refresh_from_db()
                self.assertEqual(request_record.status, "pending")
                self.assertIsNone(request_record.scheduled_appointment_date)
                self.assertEqual(post.status, "rescued")
                self.assertContains(response, "Approval opens after")

    def test_admin_can_accept_requests_after_phase_and_verification_windows_finish(self):
        now = timezone.now()
        admin_client = self._client_for(self.admin_user)

        for flow, config in self.flow_config.items():
            with self.subTest(flow=flow):
                post = self._create_post(
                    flow,
                    created_at=config["initial_created_at"](now),
                )
                request_record = self._submit_request(flow, self.first_member, post)
                self._set_created_at(
                    Post,
                    post.id,
                    config["expired_created_at"](now),
                )
                self._set_created_at(
                    PostRequest,
                    request_record.id,
                    now - PostRequest.verification_window() - timedelta(minutes=1),
                )
                post.refresh_from_db()
                request_record.refresh_from_db()

                response = admin_client.post(
                    reverse(
                        "dogadoption_admin:update_request",
                        args=[request_record.id, "accept"],
                    ),
                    follow=True,
                )

                self.assertEqual(response.status_code, 200)
                request_record.refresh_from_db()
                post.refresh_from_db()
                self.assertEqual(request_record.status, "accepted")
                self.assertEqual(
                    request_record.scheduled_appointment_date,
                    self.appointment_date,
                )
                self.assertEqual(post.status, config["accepted_post_status"])

    def test_admin_calendar_save_preserves_past_dates_while_updating_current_and_future(self):
        GlobalAppointmentDate.objects.all().delete()
        today = timezone.localdate()
        past_date = today - timedelta(days=2)
        current_date = today
        removed_future_date = today + timedelta(days=3)
        kept_future_date = today + timedelta(days=5)

        for day in [past_date, current_date, removed_future_date]:
            GlobalAppointmentDate.objects.create(appointment_date=day, is_active=True)

        admin_client = self._client_for(self.admin_user)
        response = admin_client.post(
            reverse("dogadoption_admin:post_list"),
            {
                "form_type": "appointment_dates",
                "appointment_dates": ",".join(
                    [current_date.isoformat(), kept_future_date.isoformat()]
                ),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Appointment dates saved.")
        self.assertEqual(
            set(
                GlobalAppointmentDate.objects.order_by("appointment_date").values_list(
                    "appointment_date",
                    flat=True,
                )
            ),
            {past_date, current_date, kept_future_date},
        )

    def test_post_deadlines_follow_non_consecutive_admin_calendar_dates(self):
        GlobalAppointmentDate.objects.all().delete()
        today = timezone.localdate()
        schedule_offsets = [-2, 0, 3, 5, 6]
        for offset in schedule_offsets:
            GlobalAppointmentDate.objects.create(
                appointment_date=today + timedelta(days=offset),
                is_active=True,
            )

        created_at = timezone.make_aware(
            datetime.combine(today - timedelta(days=2), time(hour=9)),
            timezone.get_current_timezone(),
        )
        post = self._create_post(
            "claim",
            created_at=created_at,
            claim_days=2,
        )

        self.assertEqual(timezone.localtime(post.claim_deadline()).date(), today)
        self.assertEqual(
            timezone.localtime(post.adoption_deadline()).date(),
            today + timedelta(days=6),
        )
        self.assertEqual(post.current_phase(), "claim")

    def test_future_calendar_changes_shift_existing_post_deadlines(self):
        today = timezone.localdate()
        post = self._create_post(
            "claim",
            created_at=timezone.now(),
            claim_days=2,
        )

        initial_deadline = timezone.localtime(post.claim_deadline()).date()
        self.assertEqual(initial_deadline, today + timedelta(days=1))

        GlobalAppointmentDate.objects.filter(
            appointment_date=today + timedelta(days=1)
        ).delete()

        updated_deadline = timezone.localtime(post.claim_deadline()).date()
        self.assertEqual(updated_deadline, today + timedelta(days=2))
