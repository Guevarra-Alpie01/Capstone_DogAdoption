from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from .notification_utils import (
    USER_NOTIFICATIONS_SEEN_SESSION_KEY,
    build_user_notification_payload,
)


def _empty_user_notifications_context():
    return {
        "user_unread_notifications": 0,
        "user_latest_notifications": [],
        "user_notifications_seen_url": "",
    }


def user_notifications(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or user.is_staff:
        return _empty_user_notifications_context()

    try:
        payload = build_user_notification_payload(user)
        last_seen_raw = request.session.get(USER_NOTIFICATIONS_SEEN_SESSION_KEY, "")
        last_seen_at = parse_datetime(last_seen_raw) if last_seen_raw else None
        if last_seen_at and timezone.is_naive(last_seen_at):
            last_seen_at = timezone.make_aware(last_seen_at, timezone.get_current_timezone())

        notifications = []
        unread_count = 0
        for item in payload.get("items", []):
            created_at = item.get("created_at")
            is_unread = bool(created_at and (last_seen_at is None or created_at > last_seen_at))
            if is_unread:
                unread_count += 1
            notifications.append({
                **item,
                "is_unread": is_unread,
            })

        return {
            "user_unread_notifications": unread_count,
            "user_latest_notifications": notifications,
            "user_notifications_seen_url": reverse("user:mark_notifications_seen"),
        }
    except Exception:
        return _empty_user_notifications_context()
