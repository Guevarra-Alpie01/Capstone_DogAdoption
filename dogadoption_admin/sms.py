import base64
import logging
import urllib.parse
import urllib.request

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def _format_location(req):
    if req.latitude is not None and req.longitude is not None:
        lat = float(req.latitude)
        lng = float(req.longitude)
        map_link = f"https://maps.google.com/?q={lat},{lng}"
        return f"{lat:.6f}, {lng:.6f} (Map: {map_link})"

    parts = []
    if req.barangay:
        parts.append(req.barangay)
    if req.city:
        parts.append(req.city)
    return ", ".join(parts) if parts else "Location not provided"


def build_capture_message(req):
    scheduled = req.scheduled_date
    if scheduled:
        scheduled = timezone.localtime(scheduled).strftime("%b %d, %Y %I:%M %p")
    else:
        scheduled = "Not set"

    location = _format_location(req)
    return (
        f"Dog capture scheduled. Location: {location}. "
        f"Time: {scheduled}. Request #{req.id}."
    )


def send_sms(to_numbers, body):
    backend = getattr(settings, "SMS_BACKEND", "console").lower()
    to_numbers = [n for n in (to_numbers or []) if n]

    if not to_numbers:
        logger.warning("SMS skipped: no recipient numbers.")
        return False

    if backend == "twilio":
        return _send_twilio_sms(to_numbers, body)

    # Default console backend for development
    logger.info("SMS backend=console recipients=%s body=%s", to_numbers, body)
    return True


def _send_twilio_sms(to_numbers, body):
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
    token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
    from_number = getattr(settings, "TWILIO_FROM_NUMBER", "")

    if not sid or not token or not from_number:
        logger.warning("Twilio credentials missing; SMS not sent.")
        return False

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    auth = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("utf-8")

    ok = True
    for to_number in to_numbers:
        data = urllib.parse.urlencode({
            "To": to_number,
            "From": from_number,
            "Body": body,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=data)
        req.add_header("Authorization", f"Basic {auth}")

        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status >= 400:
                    ok = False
                    logger.warning("Twilio SMS failed for %s status=%s", to_number, resp.status)
        except Exception as exc:
            ok = False
            logger.exception("Twilio SMS error for %s: %s", to_number, exc)

    return ok
