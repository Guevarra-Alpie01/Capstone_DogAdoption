from user.models import DogCaptureRequest
from dogadoption_admin.models import AdminNotification
from dogadoption_admin.admin_notification_utils import sync_expiry_notifications
from django.core.cache import cache


ADMIN_NOTIFICATIONS_CACHE_KEY = "admin_notifications_summary_v1"
ADMIN_NOTIFICATIONS_CACHE_TTL_SECONDS = 15


def _empty_admin_notifications_context():
    return {
        "admin_pending_capture_count": 0,
        "admin_unread_notifications": 0,
        "admin_latest_notifications": [],
    }


def admin_notifications(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_staff:
        return _empty_admin_notifications_context()

    try:
        if sync_expiry_notifications():
            cache.delete(ADMIN_NOTIFICATIONS_CACHE_KEY)

        cached = cache.get(ADMIN_NOTIFICATIONS_CACHE_KEY)
        if cached is not None:
            return cached

        payload = {
            "admin_pending_capture_count": DogCaptureRequest.objects.filter(status="pending").count(),
            "admin_unread_notifications": AdminNotification.objects.filter(is_read=False).count(),
            "admin_latest_notifications": list(
                AdminNotification.objects.order_by("-created_at")
                .values("id", "title", "message", "created_at", "is_read")[:5]
            ),
        }
        cache.set(
            ADMIN_NOTIFICATIONS_CACHE_KEY,
            payload,
            ADMIN_NOTIFICATIONS_CACHE_TTL_SECONDS,
        )
        return payload
    except Exception:
        return _empty_admin_notifications_context()
