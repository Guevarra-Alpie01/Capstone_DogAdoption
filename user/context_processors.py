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
