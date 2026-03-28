ADMIN_NOTIFICATIONS_CACHE_KEY = "admin_notifications_summary_v1"
ADMIN_NOTIFICATIONS_CACHE_TTL_SECONDS = 15

from user.avatar_cache import DEFAULT_AVATAR_URL, get_cached_profile_avatar_url

from .access import get_admin_access_namespace


def _empty_admin_notifications_context():
    return {
        "admin_pending_capture_count": 0,
        "admin_unread_notifications": 0,
        "admin_latest_notifications": [],
        "admin_notifications_summary_url": "",
        "admin_access": get_admin_access_namespace(None),
        "admin_topbar_avatar_url": DEFAULT_AVATAR_URL,
    }


def admin_notifications(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_staff:
        return _empty_admin_notifications_context()

    from django.urls import reverse

    admin_access = get_admin_access_namespace(user)
    if not admin_access.is_full_admin:
        return {
            "admin_pending_capture_count": 0,
            "admin_unread_notifications": 0,
            "admin_latest_notifications": [],
            "admin_notifications_summary_url": "",
            "admin_access": admin_access,
            "admin_topbar_avatar_url": get_cached_profile_avatar_url(user),
        }

    return {
        "admin_pending_capture_count": 0,
        "admin_unread_notifications": 0,
        "admin_latest_notifications": [],
        "admin_notifications_summary_url": reverse("dogadoption_admin:notification_summary"),
        "admin_access": admin_access,
        "admin_topbar_avatar_url": get_cached_profile_avatar_url(user),
    }
