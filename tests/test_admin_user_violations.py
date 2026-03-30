from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from dogadoption_admin.models import (
    AdminNotification,
    Post,
    PostRequest,
    UserViolationNotification,
    UserViolationRecord,
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

    def _record_violation(self, reason):
        return self.client.post(
            reverse("dogadoption_admin:admin_user_add_violation", args=[self.member.id]),
            {
                "reason": reason,
                "recorded_on": "2026-03-30",
                "details": f"Details for {reason}",
            },
            follow=True,
        )

    def test_add_violation_creates_summary_and_history_record(self):
        response = self._record_violation("Late registration compliance")

        self.assertEqual(response.status_code, 200)
        summary = UserViolationSummary.objects.get(user=self.member)
        record = UserViolationRecord.objects.get(summary=summary)

        self.assertEqual(summary.violation_count, 1)
        self.assertEqual(record.reason, "Late registration compliance")
        self.assertEqual(record.violation_number, 1)
        self.assertContains(response, "Violation recorded for Tracked Member.")

    def test_third_violation_creates_saved_notification_and_admin_alert(self):
        self._record_violation("Violation one")
        self._record_violation("Violation two")
        self._record_violation("Violation three")

        summary = UserViolationSummary.objects.get(user=self.member)
        notification = UserViolationNotification.objects.get(summary=summary)
        admin_alert = AdminNotification.objects.get(
            event_key=f"user-violation-threshold:{self.member.id}:3"
        )

        self.assertEqual(summary.violation_count, 3)
        self.assertEqual(summary.latest_notification, notification)
        self.assertEqual(notification.admin_notification, admin_alert)
        self.assertIn("3 recorded violations", notification.message)

    def test_history_api_returns_violation_records_and_latest_notification(self):
        self._record_violation("Violation one")
        self._record_violation("Violation two")
        self._record_violation("Violation three")

        response = self.client.get(
            reverse("dogadoption_admin:admin_user_violation_history", args=[self.member.id])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["user"]["id"], self.member.id)
        self.assertEqual(payload["violation_count"], 3)
        self.assertEqual(len(payload["records"]), 3)
        self.assertEqual(payload["latest_notification"]["letter_status"], "generated")

    def test_print_view_marks_threshold_letter_as_printed(self):
        self._record_violation("Violation one")
        self._record_violation("Violation two")
        self._record_violation("Violation three")

        response = self.client.get(
            reverse("dogadoption_admin:admin_user_violation_letter", args=[self.member.id])
        )

        notification = UserViolationNotification.objects.get(summary__user=self.member)
        notification.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(notification.letter_status, UserViolationNotification.STATUS_PRINTED)
        self.assertContains(response, "User ID / Registration ID")
        self.assertContains(response, "Tracked Member")

    def test_claim_based_violation_count_is_restored_for_detail_and_print(self):
        post = Post.objects.create(
            user=self.admin,
            caption="Claim violation source",
            location="Bayawan",
            claim_days=3,
        )
        PostRequest.objects.create(
            post=post,
            user=self.member,
            request_type="claim",
        )

        response = self.client.get(
            reverse("dogadoption_admin:admin_user_violations", args=[self.member.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["managed_violation_count"], 1)
        self.assertEqual(response.context["letter"]["violation_count"], 1)
        self.assertContains(response, "Print Letter")
