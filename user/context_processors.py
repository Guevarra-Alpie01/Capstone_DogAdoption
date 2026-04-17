from django.conf import settings
from django.urls import reverse

from .avatar_cache import DEFAULT_AVATAR_URL, get_cached_profile_avatar_url
from .notification_utils import build_user_notification_summary


def _empty_user_notifications_context():
    return {
        "user_unread_notifications": 0,
        "user_latest_notifications": [],
        "user_notifications_seen_url": "",
        "user_notifications_summary_url": "",
        "user_notification_mark_read_url": "",
        "user_topbar_avatar_url": DEFAULT_AVATAR_URL,
    }


def user_notifications(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or user.is_staff:
        return _empty_user_notifications_context()

    summary = build_user_notification_summary(request)
    return {
        "user_unread_notifications": summary["unread_count"],
        "user_latest_notifications": summary["notifications"],
        "user_notifications_seen_url": reverse("user:mark_notifications_seen"),
        "user_notifications_summary_url": reverse("user:notification_summary"),
        "user_notification_mark_read_url": reverse("user:mark_notification_read"),
        "user_topbar_avatar_url": get_cached_profile_avatar_url(user),
    }


def auth_ui(request):
    google_client_id = (getattr(settings, "GOOGLE_CLIENT_ID", "") or "").strip()
    if not google_client_id:
        extra_client_ids = getattr(settings, "GOOGLE_CLIENT_IDS", [])
        if isinstance(extra_client_ids, str):
            extra_client_ids = [value.strip() for value in extra_client_ids.split(",") if value.strip()]
        google_client_id = (extra_client_ids[0] if extra_client_ids else "").strip()
    return {
        "google_auth_enabled": bool(google_client_id),
        "google_signup_enabled": bool(google_client_id),
        "google_client_id": google_client_id,
    }
