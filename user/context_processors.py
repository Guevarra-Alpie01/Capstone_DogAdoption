from urllib.parse import urlencode

from django.urls import reverse

from .notification_utils import (
    build_user_notification_payload,
    get_user_notification_read_keys,
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
        read_keys = get_user_notification_read_keys(request)
        notifications = []
        unread_count = 0
        for item in payload.get("items", []):
            notification_key = item.get("key", "")
            target_url = item.get("url") or reverse("user:user_home")
            is_unread = bool(notification_key and notification_key not in read_keys)
            if is_unread:
                unread_count += 1
            notifications.append({
                **item,
                "is_unread": is_unread,
                "open_url": "{}?{}".format(
                    reverse("user:open_notification"),
                    urlencode({"key": notification_key, "next": target_url}),
                ),
            })

        return {
            "user_unread_notifications": unread_count,
            "user_latest_notifications": notifications,
            "user_notifications_seen_url": reverse("user:mark_notifications_seen"),
        }
    except Exception:
        return _empty_user_notifications_context()
