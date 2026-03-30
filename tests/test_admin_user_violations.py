from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from dogadoption_admin.models import (
    AdminNotification,
    Post,
    PostRequest,
    UserViolationNotification,
    UserViolationSummary,
)
from user.models import Profile


class AdminUserViolationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="violationadmin",
            password="Secret123!",
            first_name="Violation",
            last_name="Admin",
            is_staff=True,
        )
        self.member = User.objects.create_user(
            username="trackedmember",
            password="Secret123!",
            first_name="Tracked",
            last_name="Member",
        )
        Profile.objects.create(
            user=self.member,
            address="Purok 1, Villareal, Bayawan City, Negros Oriental",
            age=29,
            consent_given=True,
        )
        self.client.force_login(self.admin)

    def _create_claim_violations(self, count):
        for index in range(count):
            post = Post.objects.create(
                user=self.admin,
                caption=f"Claim violation source {index + 1}",
                location="Bayawan",
                claim_days=3,
            )
            PostRequest.objects.create(
                post=post,
                user=self.member,
                request_type="claim",
            )

    def test_users_page_hides_removed_manual_violation_controls(self):
        response = self.client.get(reverse("dogadoption_admin:admin_users"))
        user_row = next(row for row in response.context["users"] if row["id"] == self.member.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(user_row["violation_count"], 0)
        self.assertNotContains(response, "Add Violation")
        self.assertNotContains(response, "Open JSON")
        self.assertNotContains(response, user_row["violation_url"])

    def test_claim_based_violation_button_and_detail_page_work_without_history_section(self):
        self._create_claim_violations(1)

        users_response = self.client.get(reverse("dogadoption_admin:admin_users"))
        detail_response = self.client.get(
            reverse("dogadoption_admin:admin_user_violations", args=[self.member.id])
        )
        user_row = next(row for row in users_response.context["users"] if row["id"] == self.member.id)

        self.assertEqual(users_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(user_row["violation_count"], 1)
        self.assertContains(users_response, user_row["violation_url"])
        self.assertEqual(detail_response.context["managed_violation_count"], 1)
        self.assertEqual(detail_response.context["letter"]["violation_count"], 1)
        self.assertNotContains(detail_response, "Add Violation")
        self.assertNotContains(detail_response, "Violation Records")
        self.assertNotContains(detail_response, "Open JSON")
        self.assertNotContains(detail_response, 'target="_blank"')
        self.assertContains(detail_response, "Print Letter")

    def test_threshold_notice_generated_from_claim_based_violation_count(self):
        self._create_claim_violations(3)

        response = self.client.get(
            reverse("dogadoption_admin:admin_user_violations", args=[self.member.id])
        )

        summary = UserViolationSummary.objects.get(user=self.member)
        notification = UserViolationNotification.objects.get(summary=summary)
        admin_alert = AdminNotification.objects.get(
            event_key=f"user-violation-threshold:{self.member.id}:3"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["managed_violation_count"], 3)
        self.assertEqual(summary.violation_count, 3)
        self.assertEqual(summary.latest_notification, notification)
        self.assertEqual(notification.admin_notification, admin_alert)
        self.assertIn("3 recorded violations", notification.message)

    def test_print_view_marks_threshold_letter_as_printed(self):
        self._create_claim_violations(3)

        response = self.client.get(
            reverse("dogadoption_admin:admin_user_violation_letter", args=[self.member.id])
        )

        notification = UserViolationNotification.objects.get(summary__user=self.member)
        notification.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(notification.letter_status, UserViolationNotification.STATUS_PRINTED)
        self.assertContains(response, "User ID / Registration ID")
        self.assertContains(response, "Tracked Member")
        self.assertContains(response, 'onload="prepareViolationPrint();"')
        self.assertContains(response, "goBackToViolationDetail(event)")
