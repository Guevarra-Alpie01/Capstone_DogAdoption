from django.conf import settings
from django.urls import reverse

from .avatar_cache import DEFAULT_AVATAR_URL, get_cached_profile_avatar_url


def _empty_user_notifications_context():
    return {
        "user_unread_notifications": 0,
        "user_latest_notifications": [],
        "user_notifications_seen_url": "",
        "user_notifications_summary_url": "",
        "user_topbar_avatar_url": DEFAULT_AVATAR_URL,
    }


def user_notifications(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or user.is_staff:
        return _empty_user_notifications_context()

    return {
        "user_unread_notifications": 0,
        "user_latest_notifications": [],
        "user_notifications_seen_url": reverse("user:mark_notifications_seen"),
        "user_notifications_summary_url": reverse("user:notification_summary"),
        "user_topbar_avatar_url": get_cached_profile_avatar_url(user),
    }


def auth_ui(request):
    google_client_id = (getattr(settings, "GOOGLE_CLIENT_ID", "") or "").strip()
    facebook_app_id = (getattr(settings, "FACEBOOK_APP_ID", "") or "").strip()
    facebook_app_secret = (getattr(settings, "FACEBOOK_APP_SECRET", "") or "").strip()
    return {
        "google_signup_enabled": bool(google_client_id),
        "google_client_id": google_client_id,
        "facebook_auth_enabled": bool(facebook_app_id and facebook_app_secret),
        "facebook_app_id": facebook_app_id,
    }
