from user.models import DogCaptureRequest
from dogadoption_admin.models import AdminNotification


def admin_notifications(request):
    pending_count = 0
    unread_count = 0
    latest = []
    try:
        pending_count = DogCaptureRequest.objects.filter(status="pending").count()
        unread_count = AdminNotification.objects.filter(is_read=False).count()
        latest = AdminNotification.objects.all()[:5]
    except Exception:
        pending_count = 0
        unread_count = 0
        latest = []

    return {
        "admin_pending_capture_count": pending_count,
        "admin_unread_notifications": unread_count,
        "admin_latest_notifications": latest,
    }
