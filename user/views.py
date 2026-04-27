from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.validators import ASCIIUsernameValidator
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.views.decorators.http import require_POST, require_http_methods
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q
from django.db import IntegrityError, transaction
from django.views.decorators.csrf import csrf_exempt
import os
import base64
import binascii
import hashlib
import json
import re
import random
import secrets
import shutil
from django.http import JsonResponse
from django.core.files.base import ContentFile
from django.conf import settings
from django.core.cache import cache
from datetime import datetime, timedelta
from functools import wraps
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.http import (
    url_has_allowed_host_and_scheme,
    urlsafe_base64_decode,
    urlsafe_base64_encode,
)
from django.templatetags.static import static
from django.utils.html import strip_tags
from urllib.parse import urlencode
import math

# Shared models from the admin app
from dogadoption_admin.access import get_admin_access, get_staff_landing_url, is_route_allowed
from dogadoption_admin.barangays import BAYAWAN_BARANGAYS
from dogadoption_admin.citation_subitems import citation_fee_total, normalize_subitems
from dogadoption_admin.models import (
    AdminNotification,
    AnnouncementComment,
    Barangay,
    Citation,
    Dog,
    DogAnnouncement,
    DogAnnouncementImage,
    DogImage,
    GlobalAppointmentDate,
    Post,
    PostImage,
    PostRequest,
)
from dogadoption_admin.context_processors import ADMIN_NOTIFICATIONS_CACHE_KEY

# Models from the user app
from .models import Profile, DogCaptureRequest, DogCaptureRequestImage, DogCaptureRequestLandmarkImage, ClaimImage
from .models import UserAdoptionPost, UserAdoptionImage, UserAdoptionRequest, MissingDogPost, MissingDogPhoto, DogSighting

# Forms and notification helpers
from .forms import DogSightingForm, MissingDogPostForm, RescueFinderForm, UserAdoptionPostForm
from .avatar_cache import invalidate_cached_profile_avatar
from .auth_modal_session import (
    build_home_auth_modal_url as _build_home_auth_modal_url_impl,
    redirect_modal_login_error,
)
from .notification_utils import (
    build_user_notification_payload,
    build_user_notification_summary,
    build_user_registered_dog_vaccination_status_map,
    build_user_vaccination_reminder_summary,
    bump_user_home_feed_namespace,
    get_user_home_feed_namespace,
    invalidate_user_notification_content,
    invalidate_user_notification_payload,
    mark_user_notification_read,
    mark_user_notifications_read,
)

# Administrative and user models above are shared across multiple public flows.
# The view module is grouped below by shared helpers and user navigation links.

# =============================================================================
# Shared imports, constants, and helper utilities
# =============================================================================

ACTIVE_BARANGAY_LOOKUP_CACHE_KEY = "user_active_barangay_lookup"
ACTIVE_BARANGAY_LOOKUP_CACHE_TTL_SECONDS = 300
HOME_FEED_SESSION_TOKEN_KEY = "user_home_feed_token"
BARANGAY_API_DEFAULT_LIMIT = 200
BARANGAY_API_MAX_LIMIT = 200
DEFAULT_REQUEST_CITY = "Bayawan City"
DOG_CAPTURE_MAX_ACCEPTABLE_GPS_ACCURACY_METERS = 1000
ADMIN_POST_HISTORY_CACHE_KEY = "dogadoption_admin_post_history_ids_v1"
DOG_SURRENDER_REQUEST_TYPE = "surrender"
DOG_ONLINE_SUBMISSION_TYPE = "online"
DOG_SURRENDER_MIN_DOG_PHOTOS = 2
SURRENDER_DOG_PHOTOS_REQUIREMENT_TEXT = (
    "Upload at least 2 photos - one of dog alone, one with owner/dog together."
)
DOG_SURRENDER_FORM_CONTEXT = {
    "surrender_gender_choices": Post.GENDER_CHOICES,
    "surrender_color_choices": Post.COLOR_CHOICES,
    "surrender_breed_choices": Post.BREED_CHOICES,
    "surrender_age_group_choices": Post.AGE_GROUP_CHOICES,
    "surrender_min_dog_photos": DOG_SURRENDER_MIN_DOG_PHOTOS,
    "surrender_dog_photos_hint": SURRENDER_DOG_PHOTOS_REQUIREMENT_TEXT,
}
PHILIPPINES_COUNTRY_CODE = "+63"
SIGNUP_USERNAME_MIN_LENGTH = 3
SIGNUP_USERNAME_MAX_LENGTH = User._meta.get_field("username").max_length
_signup_username_validator = ASCIIUsernameValidator()
RESCUE_FINDER_PAGE_SIZE = 12
RESCUE_FINDER_RECOMMENDATION_LIMIT = 4
HOME_FEATURED_CAROUSEL_LIMIT = 5
HOME_FEATURED_UNIFIED_CAROUSEL_LIMIT = 8
HOME_SPOTLIGHT_DISPLAY_LIMIT = 4
HOME_SPOTLIGHT_FALLBACK_CANDIDATE_LIMIT = 60
HOME_FEATURED_CANDIDATE_LIMIT = 60
HOME_SPOTLIGHT_URGENCY_THRESHOLD_SECONDS = 24 * 60 * 60
GOOGLE_SIGNUP_SESSION_KEY = "google_signup_data"
LOGIN_USERNAME_PREFILL_SESSION_KEY = "login_username_prefill"
LOGIN_INVALID_CREDENTIALS_MESSAGE = "Invalid username or password."


def _safe_media_url(file_field):
    """Return a file URL safely when an optional image/file is present."""
    if not file_field:
        return ""
    try:
        return file_field.url
    except Exception:
        return ""


def _first_prefetched_image_url(images):
    """Read the first prefetched image URL from a related image collection."""
    first_image = next(iter(images), None)
    if not first_image:
        return ""
    return _safe_media_url(getattr(first_image, "image", None))


def _prefetched_image_urls(images):
    """Ordered list of public image URLs (for find-a-dog lightbox gallery)."""
    urls = []
    for img in images:
        u = _safe_media_url(getattr(img, "image", None))
        if u:
            urls.append(u)
    return urls


def _build_user_profile_url(user_id, *, next_url="", back_label="Back"):
    """Build a read-only profile preview URL for a user account."""
    profile_url = reverse("user:view_user_profile", args=[user_id])
    query_params = {}
    if next_url:
        query_params["next"] = next_url
        if back_label:
            query_params["label"] = back_label
    if not query_params:
        return profile_url
    return f"{profile_url}?{urlencode(query_params)}"


def _parse_gps_accuracy_meters(raw_value):
    """Return a positive numeric GPS accuracy in meters, or None."""
    try:
        accuracy = float((raw_value or "").strip())
    except (AttributeError, TypeError, ValueError):
        return None
    if not math.isfinite(accuracy) or accuracy <= 0:
        return None
    return accuracy


def _build_profile_destination_url(request, user_id, *, next_url="", back_label="Back"):
    """Route profile links to self-edit, public preview, or admin preview."""
    if request.user.is_authenticated and request.user.is_staff:
        return reverse("user:admin_view_user_profile", args=[user_id])
    if request.user.is_authenticated and request.user.id == user_id:
        return reverse("user:edit_profile")
    return _build_user_profile_url(
        user_id,
        next_url=next_url,
        back_label=back_label,
    )


def _safe_preview_back_url(request, raw_url):
    """Accept only local preview return URLs."""
    if not raw_url:
        return ""
    if url_has_allowed_host_and_scheme(
        raw_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return raw_url
    return ""


def _build_request_action_url(request_id, action, *, next_url=""):
    """Build request action links with an optional safe return URL."""
    action_url = reverse("user:user_adoption_request_action", args=[request_id, action])
    if not next_url:
        return action_url
    return f"{action_url}?{urlencode({'next': next_url})}"


def _normalize_signup_username(raw_username):
    """Normalize signup usernames before validation and storage."""
    return User.objects.model.normalize_username((raw_username or "").strip())


def _build_signup_form_data(*, username="", first_name="", last_name="", raw_barangay=""):
    """Preserve the safe, non-password signup fields across validation errors."""
    return {
        "username": username,
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "address": _clean_barangay(raw_barangay),
    }


def _google_client_ids():
    """Return configured Google OAuth web client IDs as a deduplicated ordered list."""
    raw_values = []
    primary = getattr(settings, "GOOGLE_CLIENT_ID", "")
    if isinstance(primary, (list, tuple)):
        raw_values.extend(primary)
    else:
        raw_values.append(primary)

    extra = getattr(settings, "GOOGLE_CLIENT_IDS", [])
    if isinstance(extra, str):
        raw_values.extend(extra.split(","))
    elif isinstance(extra, (list, tuple)):
        raw_values.extend(extra)

    result = []
    seen = set()
    for raw in raw_values:
        value = (raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _primary_google_client_id():
    """Return the preferred Google client ID used to render GIS buttons."""
    client_ids = _google_client_ids()
    return client_ids[0] if client_ids else ""


def _peek_google_token_audience(raw_credential):
    """Best-effort audience extraction used for clearer Google mismatch errors."""
    token = (raw_credential or "").strip()
    parts = token.split(".")
    if len(parts) < 2:
        return ""

    payload_part = parts[1]
    payload_part += "=" * ((4 - len(payload_part) % 4) % 4)
    try:
        payload_raw = base64.urlsafe_b64decode(payload_part.encode("ascii"))
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception:
        return ""

    aud = payload.get("aud")
    if isinstance(aud, list):
        for value in aud:
            normalized = (value or "").strip()
            if normalized:
                return normalized
        return ""
    return (aud or "").strip()


def _auth_ui_context():
    """Expose the public auth template flags shared by login and signup views."""
    google_client_id = _primary_google_client_id()
    return {
        "google_auth_enabled": bool(google_client_id),
        "google_signup_enabled": bool(google_client_id),
        "google_client_id": google_client_id,
    }


def _build_google_signup_username(*, email="", first_name="", last_name="", social_id=""):
    """Suggest a safe username when Google pre-fills a signup form."""
    candidates = [
        (email or "").split("@", 1)[0],
        f"{first_name}.{last_name}".strip("."),
        f"{first_name}{last_name}",
        social_id,
    ]
    for candidate in candidates:
        candidate = re.sub(r"[^A-Za-z0-9.@_+-]+", "", (candidate or "").strip())
        candidate = candidate.strip(".@_+-")
        if len(candidate) >= SIGNUP_USERNAME_MIN_LENGTH:
            return candidate[:SIGNUP_USERNAME_MAX_LENGTH]
    fallback = f"google_{(social_id or secrets.token_hex(4))[:10]}"
    return fallback[:SIGNUP_USERNAME_MAX_LENGTH]


def _build_unique_google_username(*, email="", first_name="", last_name="", social_id=""):
    """Return a collision-resistant username for a newly created Google account."""
    base_username = _normalize_signup_username(
        _build_google_signup_username(
            email=email,
            first_name=first_name,
            last_name=last_name,
            social_id=social_id,
        )
    )
    if base_username and not User.objects.filter(username__iexact=base_username).exists():
        return base_username

    social_fragment = re.sub(r"[^A-Za-z0-9]+", "", (social_id or "").strip())[:8] or secrets.token_hex(4)
    candidate_base = base_username or f"google_{social_fragment}"
    candidate_base = candidate_base.strip(".@_+-") or f"google_{social_fragment}"

    for suffix in range(1, 25):
        suffix_text = "" if suffix == 1 else f"_{suffix}"
        max_base_len = SIGNUP_USERNAME_MAX_LENGTH - len(suffix_text)
        candidate = f"{candidate_base[:max_base_len]}{suffix_text}".strip(".@_+-")
        if len(candidate) < SIGNUP_USERNAME_MIN_LENGTH:
            continue
        if not User.objects.filter(username__iexact=candidate).exists():
            return candidate

    fallback = f"google_{social_fragment}_{secrets.token_hex(2)}"
    return fallback[:SIGNUP_USERNAME_MAX_LENGTH]


def _clear_social_signup_session(request):
    """Remove any cached social signup payloads from the session."""
    request.session.pop(GOOGLE_SIGNUP_SESSION_KEY, None)


def _get_social_signup_state(request):
    """Return the latest social signup source and its cached payload."""
    google_signup_data = request.session.get(GOOGLE_SIGNUP_SESSION_KEY) or {}
    if google_signup_data:
        return "google", google_signup_data

    return "", {}


def _store_google_signup_payload(request, payload):
    """Persist Google identity data so the signup page can prefill fields."""
    _clear_social_signup_session(request)
    signup_data = {
        "email": payload.get("email", ""),
        "google_sub": payload.get("sub", ""),
        "first_name": payload.get("given_name", ""),
        "last_name": payload.get("family_name", ""),
        "full_name": payload.get("name", ""),
        "username": _build_google_signup_username(
            email=payload.get("email", ""),
            first_name=payload.get("given_name", ""),
            last_name=payload.get("family_name", ""),
            social_id=payload.get("sub", ""),
        ),
    }
    request.session[GOOGLE_SIGNUP_SESSION_KEY] = signup_data
    request.session.modified = True


def _merge_social_signup_data(request, signup_form_data=None):
    """Prefill signup fields from the most recent social auth callback."""
    _, social_signup_data = _get_social_signup_state(request)
    merged = {
        "username": social_signup_data.get("username", ""),
        "first_name": social_signup_data.get("first_name", ""),
        "last_name": social_signup_data.get("last_name", ""),
        "address": "",
    }
    if signup_form_data:
        merged.update(signup_form_data)
    return merged


def _render_signup_error(request, signup_form_data, message):
    """Re-open the signup modal with a single validation error message."""
    next_url = _get_safe_next_url(request, request.POST.get("next"))
    if (request.POST.get("auth_source") or "").strip() == "modal":
        return _render_home_with_auth_modal(
            request,
            "signup",
            auth_next=next_url,
            signup_error=message,
            signup_form_data=signup_form_data,
        )
    return _render_signup_page(
        request,
        error=message,
        signup_form_data=signup_form_data,
        next_url=next_url,
    )


def _render_login_page(request, *, error="", login_form_data=None, next_url=""):
    """Render the dedicated login page used for standalone auth flows."""
    return render(
        request,
        "login.html",
        {
            "error": error,
            "login_form_data": login_form_data or {},
            "auth_next": next_url,
            **_auth_ui_context(),
        },
    )


def _render_signup_page(request, *, error="", signup_form_data=None, next_url=""):
    """Render the dedicated signup page used for standalone auth flows."""
    return render(
        request,
        "signup.html",
        {
            "error": error,
            "signup_form_data": signup_form_data or {},
            "auth_next": next_url,
            **_auth_ui_context(),
        },
    )


def privacy_policy(request):
    """Render the public privacy policy page used by Meta review."""
    return render(
        request,
        "legal/privacy_policy.html",
    )


def data_deletion(request):
    """Render the public data deletion instructions page used by Meta review."""
    return render(
        request,
        "legal/data_deletion.html",
    )


def _validate_signup_username(username):
    """Require a safe username format and block case-insensitive duplicates."""
    if not username:
        raise ValidationError("Username is required.")
    if len(username) < SIGNUP_USERNAME_MIN_LENGTH:
        raise ValidationError(
            f"Username must be at least {SIGNUP_USERNAME_MIN_LENGTH} characters long."
        )
    if len(username) > SIGNUP_USERNAME_MAX_LENGTH:
        raise ValidationError(
            f"Username must be {SIGNUP_USERNAME_MAX_LENGTH} characters or fewer."
        )
    _signup_username_validator(username)
    if User.objects.filter(username__iexact=username).exists():
        raise ValidationError("Username already exists.")
    return username


def _normalize_signup_email(raw_email):
    """Normalize the verified signup email before saving it to the user record."""
    return (User.objects.normalize_email((raw_email or "").strip()) or "").strip().lower()


def _user_has_verified_email(user):
    """Return True for legacy accounts or for profiles already marked verified."""
    if not user or getattr(user, "is_staff", False):
        return True
    profile = getattr(user, "profile", None)
    return bool(getattr(profile, "email_verified", True))


def _user_requires_email_verification(user):
    """Return True when a public account is still blocked pending email verification."""
    return bool(user and not user.is_staff and not user.is_active and not _user_has_verified_email(user))


def _build_public_absolute_uri(request, relative_url):
    """Build an absolute URL for emails, honoring an optional site-base override."""
    site_base_url = (getattr(settings, "SITE_BASE_URL", "") or "").strip().rstrip("/")
    if site_base_url:
        return f"{site_base_url}{relative_url}"
    return request.build_absolute_uri(relative_url)


def _build_email_verification_url(request, user, *, next_url=""):
    """Create the email verification link for an inactive signup account."""
    verification_path = reverse(
        "user:verify_email",
        args=[
            urlsafe_base64_encode(force_bytes(user.pk)),
            default_token_generator.make_token(user),
        ],
    )
    if next_url:
        verification_path = f"{verification_path}?{urlencode({'next': next_url})}"
    return _build_public_absolute_uri(request, verification_path)


def _send_signup_verification_email(request, user, *, next_url=""):
    """Send the verification email required before the user can log in."""
    verification_url = _build_email_verification_url(request, user, next_url=next_url)
    sent_count = send_mail(
        "Verify your Bayawan Vet account",
        (
            f"Hello {user.first_name or user.username},\n\n"
            "Your Bayawan Vet account has been created, but you must verify your email address "
            "before you can log in.\n\n"
            f"Verify your account: {verification_url}\n\n"
            "If you did not request this account, you can ignore this message."
        ),
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
    if sent_count != 1:
        raise RuntimeError("We couldn't send the verification email. Please try again later.")


def _verify_google_identity_credential(
    raw_credential,
    *,
    missing_message,
    config_message,
    unavailable_message,
):
    """Validate the Google Identity Services ID token for auth flows."""
    credential = (raw_credential or "").strip()
    if not credential:
        raise ValidationError(missing_message)

    google_client_ids = _google_client_ids()
    if not google_client_ids:
        raise ValidationError(config_message)

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as exc:
        raise ValidationError(unavailable_message) from exc

    try:
        google_payload = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            None,
        )
    except ValueError as exc:
        raise ValidationError(
            "Google could not verify the selected account. Check your GOOGLE_CLIENT_ID Web client value and try again."
        ) from exc

    token_audience = _peek_google_token_audience(credential)
    if token_audience and token_audience not in google_client_ids:
        raise ValidationError(
            "Google client ID mismatch. Update GOOGLE_CLIENT_ID in your .env to the Web client ID used in Google Cloud."
        )

    if google_payload.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise ValidationError("Google could not verify the selected account. Please try again.")

    google_email = _normalize_signup_email(google_payload.get("email"))
    if not google_email:
        raise ValidationError("Your Google account did not provide an email address.")
    if not google_payload.get("email_verified"):
        raise ValidationError("Your Google account email must already be verified before signup.")

    google_sub = (google_payload.get("sub") or "").strip()
    if not google_sub:
        raise ValidationError("Google could not verify the selected account. Please try again.")

    return {
        "email": google_email,
        "sub": google_sub,
        "given_name": (google_payload.get("given_name") or "").strip(),
        "family_name": (google_payload.get("family_name") or "").strip(),
    }


def _verify_google_signup_credential(raw_credential):
    """Validate the Google Identity Services ID token used during signup."""
    return _verify_google_identity_credential(
        raw_credential,
        missing_message="Google sign-up could not be verified. Please try again.",
        config_message="Google signup is not configured yet. Please contact the administrator.",
        unavailable_message="Google signup is unavailable because the server dependency is missing.",
    )


def _verify_google_login_credential(raw_credential):
    """Validate the Google Identity Services ID token used during login."""
    return _verify_google_identity_credential(
        raw_credential,
        missing_message="Continue with Google is required to finish signing in.",
        config_message="Google sign-in is not configured yet. Please contact the administrator.",
        unavailable_message="Google sign-in is unavailable because the server dependency is missing.",
    )


def _verify_google_redirect_csrf(request):
    """Validate the anti-CSRF token that Google posts back in redirect mode."""
    form_token = (request.POST.get("g_csrf_token") or "").strip()
    cookie_token = (request.COOKIES.get("g_csrf_token") or "").strip()
    if not form_token or not cookie_token or form_token != cookie_token:
        raise ValidationError("Google sign-in could not be verified. Please try again.")


def _create_google_user_account(google_account):
    """Create a local user and profile for a verified Google identity."""
    google_email = google_account["email"]
    google_first_name = (google_account.get("given_name") or "").strip()
    google_last_name = (google_account.get("family_name") or "").strip()
    google_sub = (google_account.get("sub") or "").strip()

    for _ in range(5):
        username = _build_unique_google_username(
            email=google_email,
            first_name=google_first_name,
            last_name=google_last_name,
            social_id=google_sub,
        )
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    password=None,
                    first_name=google_first_name,
                    last_name=google_last_name,
                    email=google_email,
                    is_active=True,
                )
                Profile.objects.create(
                    user=user,
                    middle_initial="",
                    address="",
                    age=18,
                    consent_given=True,
                    email_verified=True,
                    profile_image=_ensure_default_profile_image_exists(),
                )
            return user
        except IntegrityError:
            continue

    raise RuntimeError("We couldn't create your Google account right now. Please try again.")


def _create_manual_user_account(*, username, password, first_name, last_name, barangay):
    """Create an active local account for a manual signup submission."""
    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
            email="",
            is_active=True,
        )
        Profile.objects.create(
            user=user,
            middle_initial="",
            address=barangay,
            age=18,
            consent_given=True,
            email_verified=True,
            profile_image=_ensure_default_profile_image_exists(),
        )
    return user


def _complete_google_login(request, google_account, *, next_url=""):
    """Log in an existing Google user or create a local account for a new one."""
    google_email = google_account["email"]
    existing_user = (
        User.objects.select_related("profile")
        .filter(email__iexact=google_email)
        .order_by("id")
        .first()
    )

    if existing_user is not None:
        profile, _ = Profile.objects.get_or_create(
            user=existing_user,
            defaults={
                "address": "",
                "age": 18,
                "consent_given": True,
                "email_verified": True,
            },
        )
        profile_updates = []
        if not profile.email_verified:
            profile.email_verified = True
            profile_updates.append("email_verified")
        if profile_updates:
            profile.save(update_fields=profile_updates)

        user_updates = []
        if not existing_user.is_active:
            existing_user.is_active = True
            user_updates.append("is_active")
        if user_updates:
            existing_user.save(update_fields=user_updates)

        existing_user.backend = settings.GOOGLE_LOGIN_AUTH_BACKEND
        login(request, existing_user)
        _clear_social_signup_session(request)
        messages.success(request, "Signed in with Google.")
        if existing_user.is_staff:
            response = redirect(next_url or get_staff_landing_url(existing_user))
            response.set_cookie("admin_sessionid", request.session.session_key)
            return response

        if not profile.address and not next_url:
            response = redirect("user:complete_google_profile")
        elif next_url:
            response = redirect(next_url)
        else:
            response = redirect("user:user_home")
        response.delete_cookie("admin_sessionid")
        return response

    try:
        created_user = _create_google_user_account(google_account)
    except RuntimeError as exc:
        messages.error(request, str(exc))
        login_url = reverse("user:login")
        if next_url:
            login_url = f"{login_url}?{urlencode({'next': next_url})}"
        return redirect(login_url)

    created_user.backend = settings.GOOGLE_LOGIN_AUTH_BACKEND
    login(request, created_user)
    _clear_social_signup_session(request)
    _clear_signup_session_state(request, delete_temp_faces=True)
    messages.success(request, "Signed in with Google.")

    if created_user.is_staff:
        if next_url:
            response = redirect(next_url)
        else:
            response = redirect(get_staff_landing_url(created_user))
        response.set_cookie("admin_sessionid", request.session.session_key)
        return response

    response = redirect("user:complete_google_profile")
    response.delete_cookie("admin_sessionid")
    return response


@login_required(login_url="/user/user-login/")
def complete_google_profile(request):
    """Let a new Google user fill in their barangay before entering the app."""
    profile = getattr(request.user, "profile", None)
    if profile is None:
        profile, _ = Profile.objects.get_or_create(
            user=request.user,
            defaults={"address": "", "age": 18, "consent_given": True},
        )

    if profile.address:
        return redirect("user:user_home")

    if request.method == "POST":
        raw_barangay = request.POST.get("address", "").strip()
        barangay = _resolve_barangay_name(raw_barangay)
        if not barangay:
            return render(request, "complete_profile.html", {
                "error": "Please select a valid barangay from the suggestions.",
                "form_barangay": raw_barangay,
            })
        profile.address = barangay
        profile.save(update_fields=["address"])
        messages.success(request, "Profile updated! Welcome to the app.")
        return redirect("user:user_home")

    return render(request, "complete_profile.html")


def _delete_temp_signup_face_images(image_paths):
    """Remove temporary signup face images when a signup attempt is reset."""
    for relative_path in image_paths or []:
        full_path = os.path.join(settings.MEDIA_ROOT, relative_path)
        if os.path.exists(full_path):
            os.remove(full_path)


def _clear_signup_session_state(request, *, delete_temp_faces=False):
    """Clear all temporary signup session state, optionally deleting temp files."""
    if delete_temp_faces:
        _delete_temp_signup_face_images(request.session.get("face_images_files", []))
    request.session.pop("signup_data", None)
    request.session.pop("face_images_files", None)
    request.session.pop("signup_face_upload_token", None)


def _clear_signup_face_progress(request):
    """Reset captured face-auth progress while keeping typed signup details."""
    _delete_temp_signup_face_images(request.session.get("face_images_files", []))
    request.session.pop("face_images_files", None)
    request.session.pop("signup_face_upload_token", None)
    signup_data = request.session.get("signup_data")
    if signup_data:
        signup_data["consent_given"] = False
        request.session["signup_data"] = signup_data


def _has_pending_signup_face_progress(request):
    """Return True when the session still has unfinished face-auth progress."""
    signup_data = request.session.get("signup_data") or {}
    return bool(
        request.session.get("face_images_files")
        and not signup_data.get("consent_given")
    )


def _build_registered_dog_payloads(dogs, vaccination_status_by_dog_id=None):
    """Convert registered dog rows into template-friendly profile cards."""
    rows = []
    for dog in dogs:
        vaccination_status = (vaccination_status_by_dog_id or {}).get(dog.id, {})
        photo_urls = []
        for image in dog.images.all():
            image_url = _safe_media_url(getattr(image, "image", None))
            if image_url:
                photo_urls.append(image_url)
        rows.append({
            "id": dog.id,
            "name": dog.name or "Unnamed Dog",
            "species": dog.species or "Canine",
            "sex_label": dog.get_sex_display() if dog.sex else "-",
            "age": dog.age or "-",
            "neutering_label": dog.get_neutering_status_display() if dog.neutering_status else "-",
            "color": dog.color or "-",
            "date_registered": dog.date_registered,
            "location": dog.barangay or dog.owner_address or "",
            "photo_urls": photo_urls,
            "photo_count": len(photo_urls),
            "card_id": vaccination_status.get("anchor_id") or f"registered-dog-{dog.id}",
            "vaccination_status_key": vaccination_status.get("status_key", "no_record"),
            "vaccination_status_label": vaccination_status.get(
                "status_label",
                "No Vaccination Record",
            ),
            "vaccination_status_message": vaccination_status.get(
                "status_message",
                "No vaccination record is on file yet for this registered dog.",
            ),
            "vaccination_expiry_date": vaccination_status.get("expiry_date"),
            "vaccination_date": vaccination_status.get("vaccination_date"),
            "has_vaccination_record": vaccination_status.get("has_vaccination_record", False),
        })
    return rows


def _get_or_create_profile_dashboard_profile(profile_user):
    profile = Profile.objects.filter(user=profile_user).first()
    if profile is not None:
        return profile
    return Profile.objects.create(
        user=profile_user,
        address="",
        age=18,
        consent_given=True,
    )


def _build_profile_post_rows(profile_user, recent_post_limit, default_profile_avatar_url):
    adoption_posts = list(
        UserAdoptionPost.objects.filter(owner=profile_user)
        .annotate(
            request_count=Count("requests", distinct=True),
            pending_request_count=Count(
                "requests",
                filter=Q(requests__status="pending"),
                distinct=True,
            ),
        )
        .prefetch_related(
            Prefetch(
                "images",
                queryset=UserAdoptionImage.objects.only("id", "post_id", "image").order_by("id"),
            ),
            Prefetch(
                "requests",
                queryset=UserAdoptionRequest.objects.select_related(
                    "requester", "requester__profile"
                ).only(
                    "id",
                    "status",
                    "created_at",
                    "post_id",
                    "requester_id",
                    "requester__username",
                    "requester__first_name",
                    "requester__last_name",
                    "requester__profile__profile_image",
                    "requester__profile__phone_number",
                    "requester__profile__facebook_url",
                ).order_by("-created_at"),
            ),
        )
        .only(
            "id",
            "dog_name",
            "breed",
            "breed_other",
            "age_group",
            "size_group",
            "gender",
            "coat_length",
            "colors",
            "color_other",
            "age",
            "location",
            "status",
            "created_at",
        )
        .order_by("-created_at")[:recent_post_limit]
    )
    missing_posts = list(
        MissingDogPost.objects.filter(owner=profile_user)
        .only("id", "dog_name", "age", "location", "status", "created_at", "image")
        .order_by("-created_at")[:recent_post_limit]
    )

    profile_posts = []
    for post in adoption_posts:
        request_items = []
        request_panel_id = f"post-requests-{post.id}"
        request_return_url = f"{reverse('user:edit_profile')}#{request_panel_id}"
        for adoption_request in post.requests.all():
            requester = adoption_request.requester
            requester_profile = getattr(requester, "profile", None)
            request_items.append({
                "id": adoption_request.id,
                "requester_name": requester.get_full_name() or requester.username,
                "requester_username": requester.username,
                "requester_avatar_url": _profile_image_url_or_default(
                    requester,
                    default_profile_avatar_url,
                ),
                "requester_profile_url": _build_user_profile_url(
                    requester.id,
                    next_url=request_return_url,
                    back_label="Back to Profile",
                ),
                "phone_number": getattr(requester_profile, "phone_number", ""),
                "facebook_url": getattr(requester_profile, "facebook_url", ""),
                "status_key": adoption_request.status,
                "status_label": adoption_request.get_status_display(),
                "created_label": _format_posted_label(adoption_request.created_at),
                "accept_url": _build_request_action_url(
                    adoption_request.id,
                    "accept",
                    next_url=request_return_url,
                ),
                "decline_url": _build_request_action_url(
                    adoption_request.id,
                    "decline",
                    next_url=request_return_url,
                ),
            })

        profile_posts.append({
            "id": post.id,
            "post_type": "adoption",
            "post_type_label": "Adoption",
            "title": post.dog_name,
            "breed_label": post.display_breed,
            "age_label": post.display_age_group or (str(post.age) if post.age else ""),
            "location": post.location,
            "status_key": post.status,
            "status_label": post.get_status_display(),
            "posted_label": _format_posted_label(post.created_at),
            "created_at": post.created_at,
            "image_url": _first_prefetched_image_url(post.images.all()),
            "request_count": int(getattr(post, "request_count", 0) or 0),
            "pending_request_count": int(getattr(post, "pending_request_count", 0) or 0),
            "requests": request_items,
            "request_panel_id": request_panel_id,
        })

    for post in missing_posts:
        profile_posts.append({
            "id": post.id,
            "post_type": "missing",
            "post_type_label": "Missing",
            "title": post.dog_name,
            "age": post.age,
            "location": post.location,
            "status_key": post.status,
            "status_label": post.get_status_display(),
            "posted_label": _format_posted_label(post.created_at),
            "created_at": post.created_at,
            "image_url": _safe_media_url(post.image),
            "request_count": 0,
            "pending_request_count": 0,
            "requests": [],
            "request_panel_id": "",
        })

    profile_posts.sort(key=lambda item: item["created_at"], reverse=True)
    return profile_posts[:recent_post_limit]


def _build_profile_adopted_post_rows(profile_user, recent_post_limit):
    staff_adopt_requests = list(
        PostRequest.objects.filter(
            user=profile_user,
            request_type="adopt",
            status="accepted",
        )
        .select_related("post")
        .prefetch_related(
            Prefetch(
                "post__images",
                queryset=PostImage.objects.only("id", "post_id", "image").order_by("id"),
            )
        )
        .order_by("-created_at")[:recent_post_limit]
    )
    user_adopt_requests = list(
        UserAdoptionRequest.objects.filter(
            requester=profile_user,
            status="approved",
        )
        .select_related("post", "post__owner", "post__owner__profile")
        .prefetch_related(
            Prefetch(
                "post__images",
                queryset=UserAdoptionImage.objects.only("id", "post_id", "image").order_by("id"),
            )
        )
        .order_by("-created_at")[:recent_post_limit]
    )

    adopted_posts = []
    for req in staff_adopt_requests:
        post = req.post
        adopted_posts.append({
            "id": post.id,
            "source": "staff",
            "source_label": "Staff Post",
            "title": post.caption or "Untitled Post",
            "location": post.location,
            "adopted_label": _format_posted_label(req.created_at),
            "created_at": req.created_at,
            "image_url": _first_prefetched_image_url(post.images.all()),
        })

    for req in user_adopt_requests:
        post = req.post
        adopted_posts.append({
            "id": post.id,
            "source": "user",
            "source_label": "User Post",
            "title": post.dog_name or "Untitled Post",
            "location": post.location,
            "adopted_label": _format_posted_label(req.created_at),
            "created_at": req.created_at,
            "image_url": _first_prefetched_image_url(post.images.all()),
            "owner_name": post.owner.get_full_name() or post.owner.username,
            "owner_profile_url": _build_user_profile_url(post.owner_id),
        })

    adopted_posts.sort(key=lambda item: item["created_at"], reverse=True)
    return adopted_posts[:recent_post_limit]


def _profile_public_adoption_stats(profile_user):
    """
    Counts for the profile header: user-submitted adoption listings (excl. declined)
    and completed adoptions where this user was the adopter (staff + user posts).
    """
    dogs_posted = (
        UserAdoptionPost.objects.filter(owner=profile_user)
        .exclude(status="declined")
        .count()
    )
    staff_adoptions = PostRequest.objects.filter(
        user=profile_user,
        request_type="adopt",
        status="accepted",
    ).count()
    user_adoptions = UserAdoptionRequest.objects.filter(
        requester=profile_user,
        status="approved",
    ).count()
    return {
        "profile_stat_dogs_posted": dogs_posted,
        "profile_stat_adoptions": staff_adoptions + user_adoptions,
    }


def _build_incoming_profile_requests(profile_user, default_profile_avatar_url):
    incoming_requests_limit = 6
    incoming_requests_qs = list(
        UserAdoptionRequest.objects.filter(post__owner=profile_user)
        .select_related("post", "requester", "requester__profile")
        .only(
            "id",
            "status",
            "created_at",
            "post_id",
            "post__dog_name",
            "requester_id",
            "requester__username",
            "requester__first_name",
            "requester__last_name",
            "requester__profile__profile_image",
        )
        .order_by("-created_at")[:incoming_requests_limit]
    )
    incoming_requests = []
    for adoption_request in incoming_requests_qs:
        requester = adoption_request.requester
        incoming_requests.append({
            "id": adoption_request.id,
            "dog_name": adoption_request.post.dog_name,
            "requester_name": requester.get_full_name() or requester.username,
            "requester_username": requester.username,
            "requester_avatar_url": _profile_image_url_or_default(
                requester,
                default_profile_avatar_url,
            ),
            "requester_profile_url": _build_user_profile_url(
                adoption_request.requester_id,
                next_url=reverse("user:user_adoption_requests"),
                back_label="Back to Requests",
            ),
            "status_key": adoption_request.status,
            "status_label": adoption_request.get_status_display(),
            "created_label": _format_posted_label(adoption_request.created_at),
        })

    return {
        "incoming_requests": incoming_requests,
        "incoming_requests_limit": incoming_requests_limit,
        "incoming_requests_total": UserAdoptionRequest.objects.filter(post__owner=profile_user).count(),
    }


def _build_profile_registered_dogs(profile_user):
    registered_dogs_limit = 12
    registered_dogs_qs = list(
        Dog.objects.filter(owner_user=profile_user)
        .prefetch_related(
            Prefetch(
                "images",
                queryset=DogImage.objects.only("id", "dog_id", "image").order_by("created_at", "id"),
            )
        )
        .only(
            "id",
            "name",
            "species",
            "sex",
            "age",
            "neutering_status",
            "color",
            "date_registered",
            "owner_address",
            "barangay",
        )
        .order_by("-date_registered", "-id")[:registered_dogs_limit]
    )
    vaccination_status_by_dog_id = build_user_registered_dog_vaccination_status_map(
        profile_user,
        registered_dogs_qs,
    )
    return {
        "registered_dogs": _build_registered_dog_payloads(
            registered_dogs_qs,
            vaccination_status_by_dog_id=vaccination_status_by_dog_id,
        ),
        "registered_dogs_limit": registered_dogs_limit,
        "registered_dogs_total": Dog.objects.filter(owner_user=profile_user).count(),
    }


def _build_profile_violation_summary(profile_user):
    user_citations = (
        Citation.objects.filter(owner=profile_user)
        .select_related("penalty", "penalty__section")
        .prefetch_related("penalties", "penalties__section")
        .order_by("-date_issued", "-id")
    )
    user_violation_records = []
    for citation in user_citations:
        penalties = list(citation.penalties.all())
        if not penalties and citation.penalty_id:
            penalties = [citation.penalty]

        violation_labels = [
            f"Sec. {penalty.section.number} #{penalty.number} - {penalty.title}"
            for penalty in penalties
        ]
        sub_norm = normalize_subitems(getattr(citation, "penalty_subitems", None))
        for row in sub_norm:
            violation_labels.append(row.get("label") or row.get("code") or "Fee line")
        total_amount = citation_fee_total(penalties, sub_norm)

        user_violation_records.append(
            {
                "citation_id": citation.id,
                "date_issued": citation.date_issued,
                "violations": violation_labels,
                "violation_count": len(penalties) + len(sub_norm),
                "total_amount": total_amount,
                "remarks": (citation.remarks or "").strip(),
            }
        )

    return {
        "user_violation_count": len(user_violation_records),
        "user_violation_records": user_violation_records,
    }


def _build_profile_dashboard_context(profile_user):
    """Build the profile page context used by user and admin preview modes."""
    profile = _get_or_create_profile_dashboard_profile(profile_user)

    recent_post_limit = 6
    default_profile_avatar_url = static("images/default-user-image.jpg")
    return {
        "profile_user": profile_user,
        "profile": profile,
        "profile_posts": _build_profile_post_rows(
            profile_user,
            recent_post_limit,
            default_profile_avatar_url,
        ),
        "profile_posts_limit": recent_post_limit,
        "adopted_posts": _build_profile_adopted_post_rows(profile_user, recent_post_limit),
        "adopted_posts_limit": recent_post_limit,
        # Sighting reputation
        "verified_sightings": profile.verified_sightings,
        "sighting_badge": profile.sighting_badge,
        "next_sighting_badge": profile.next_sighting_badge,
        **_profile_public_adoption_stats(profile_user),
        **_build_incoming_profile_requests(profile_user, default_profile_avatar_url),
        **_build_profile_registered_dogs(profile_user),
        **_build_profile_violation_summary(profile_user),
    }

# =============================================================================
# Shared authentication, onboarding, and profile utilities
# =============================================================================

def user_only(view_func):
    """Allow only authenticated non-staff users to access a view."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            if _is_ajax_request(request):
                return JsonResponse({
                    "ok": False,
                    "auth_required": True,
                    "auth_modal": "login",
                    "login_url": reverse("user:login"),
                }, status=401)
            return redirect(_build_login_redirect_url(request, request.get_full_path()))
        if request.user.is_staff:
            landing_url = get_staff_landing_url(request.user)
            if _is_ajax_request(request):
                return JsonResponse({
                    "ok": False,
                    "redirect_url": landing_url,
                }, status=403)
            return redirect(landing_url)
        return view_func(request, *args, **kwargs)

    return wrapper


def _is_ajax_request(request):
    """Return True when the request was sent from frontend fetch/XHR code."""
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _get_safe_next_url(request, raw_value=""):
    """Return a safe in-app continuation URL or an empty string."""
    next_url = (raw_value or "").strip()
    if not next_url:
        return ""
    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return ""


def _build_home_auth_modal_url(request, auth_modal="login", next_url=""):
    """Build a safe home-page URL that re-opens an auth modal."""
    return _build_home_auth_modal_url_impl(request, auth_modal, next_url)


def _build_login_redirect_url(request, next_url=""):
    """Build a safe login-page URL with an optional continuation target."""
    login_url = reverse("user:login")
    safe_next_url = _get_safe_next_url(request, next_url)
    if not safe_next_url:
        return login_url
    return "{}?{}".format(login_url, urlencode({"next": safe_next_url}))


def _require_public_member_or_auth_modal(request, *, next_url=""):
    """
    Guard public claim/adopt entry points.

    Guests are sent to the public home page with the login modal ready, while
    staff still go to their admin landing page.
    """
    if not request.user.is_authenticated:
        if _is_ajax_request(request):
            return JsonResponse({
                "ok": False,
                "auth_required": True,
                "auth_modal": "login",
                "login_url": reverse("user:login"),
            }, status=401)
        return redirect(
            _build_home_auth_modal_url(
                request,
                "login",
                next_url or request.get_full_path(),
            )
        )
    if request.user.is_staff:
        landing_url = get_staff_landing_url(request.user)
        if _is_ajax_request(request):
            return JsonResponse({
                "ok": False,
                "redirect_url": landing_url,
            }, status=403)
        return redirect(landing_url)
    return None


def login_view(request):
    """Authenticate a user and redirect staff accounts to the admin app."""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect(get_staff_landing_url(request.user))
        resume_url = _get_safe_next_url(request, request.GET.get("next"))
        if resume_url:
            return redirect(resume_url)
        return redirect("user:user_home")

    next_url = _get_safe_next_url(
        request,
        (request.POST.get("next") if request.method == "POST" else request.GET.get("next")) or request.GET.get("next"),
    )

    login_form_prefill = {}
    if request.method == "GET":
        prefill_username = (request.session.pop(LOGIN_USERNAME_PREFILL_SESSION_KEY, None) or "").strip()
        if prefill_username:
            login_form_prefill = {"username": prefill_username}

    auth_source = (request.POST.get("auth_source") or "").strip() if request.method == "POST" else ""

    def render_login_error(message, username=""):
        login_form_data = {"username": username or ""}
        if auth_source == "modal":
            return redirect_modal_login_error(
                request,
                message=message,
                username=login_form_data["username"],
                next_url=next_url,
            )
        return _render_login_page(
            request,
            error=message,
            login_form_data=login_form_data,
            next_url=next_url,
        )

    if request.method == "POST":
        google_credential = (request.POST.get("google_credential") or request.POST.get("credential") or "").strip()
        if google_credential:
            try:
                google_account = _verify_google_login_credential(google_credential)
            except ValidationError as exc:
                return render_login_error(" ".join(exc.messages))
            return _complete_google_login(request, google_account, next_url=next_url)

        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password")

        if not username or not password:
            return render_login_error("Username and password are required.", username)

        existing_user = User.objects.filter(username__iexact=username).select_related("profile").first()
        if _user_requires_email_verification(existing_user):
            return render_login_error("Please verify your email address before logging in.", username)

        # Backends: VetAdminProfileAuthBackend (managed staff + profile hash) then ModelBackend.
        auth_username = existing_user.username if existing_user is not None else username
        user = authenticate(request, username=auth_username, password=password)

        if user is not None:
            if user.is_staff:
                login(request, user)
                response = redirect(get_staff_landing_url(user))
                response.set_cookie("admin_sessionid", request.session.session_key)
                return response

            login(request, user)
            response = redirect(next_url or "user:user_home")
            response.delete_cookie("admin_sessionid")
            return response

        invalid_msg = LOGIN_INVALID_CREDENTIALS_MESSAGE
        if auth_source == "modal":
            return render_login_error(invalid_msg, username)

        request.session[LOGIN_USERNAME_PREFILL_SESSION_KEY] = username
        request.session.modified = True
        messages.error(request, invalid_msg)
        login_redirect = reverse("user:login")
        if next_url:
            login_redirect = f"{login_redirect}?{urlencode({'next': next_url})}"
        return redirect(login_redirect)

    # GET: never show the broken standalone login page. Always redirect to
    # the home page with the shared auth modal open (preserves ?next=).
    return redirect(_build_home_auth_modal_url(request, "login", next_url))


@csrf_exempt
@require_POST
def google_auth_login_view(request):
    """Handle the Google redirect-based login POST from the GIS button."""
    next_url = _get_safe_next_url(
        request,
        request.GET.get("next") or request.POST.get("next"),
    )

    try:
        _verify_google_redirect_csrf(request)
        google_credential = (request.POST.get("credential") or request.POST.get("google_credential") or "").strip()
        google_account = _verify_google_login_credential(google_credential)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        login_url = reverse("user:login")
        if next_url:
            login_url = f"{login_url}?{urlencode({'next': next_url})}"
        return redirect(login_url)

    return _complete_google_login(request, google_account, next_url=next_url)


@require_POST
def logout_view(request):
    """Log out the current session and clear any admin session cookie."""
    logout(request)
    response = _redirect_to_user_home_with_fresh_feed()
    response.delete_cookie("admin_sessionid")
    return response


@require_POST
@user_only
def mark_notifications_seen(request):
    """Mark the latest user notifications as read for the current session."""
    payload = build_user_notification_payload(request.user)
    mark_user_notifications_read(
        request,
        [item.get("key", "") for item in payload.get("items", [])],
    )
    summary = build_user_notification_summary(request)
    return JsonResponse({"ok": True, "unread_count": summary["unread_count"]})


@require_POST
@user_only
def mark_notification_read(request):
    """Mark a single notification as read (session-scoped); returns updated unread count."""
    notification_key = ""
    content_type = (request.content_type or "").lower()
    if "application/json" in content_type:
        try:
            body = json.loads(request.body.decode() or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {}
        if isinstance(body, dict):
            notification_key = (body.get("key") or "").strip()
    else:
        notification_key = (request.POST.get("key") or "").strip()

    if notification_key:
        mark_user_notification_read(request, notification_key)
    summary = build_user_notification_summary(request)
    return JsonResponse({"ok": True, "unread_count": summary["unread_count"]})


@user_only
def notification_summary(request):
    """Return the current user's notification badge and dropdown data."""
    return JsonResponse(build_user_notification_summary(request))


@user_only
def open_notification(request):
    """Mark one user notification as read, then continue to its destination."""
    notification_key = (request.GET.get("key") or "").strip()
    payload = build_user_notification_payload(request.user)
    matching_item = next(
        (
            item for item in payload.get("items", [])
            if item.get("key", "").strip() == notification_key
        ),
        None,
    )

    if notification_key:
        mark_user_notification_read(request, notification_key)

    target = (
        matching_item.get("url")
        if matching_item and matching_item.get("url")
        else request.GET.get("next", "")
    )
    if not url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        target = reverse("user:user_home")
    return redirect(target)


def _clean_barangay(value):
    return " ".join((value or "").split()).strip()


def _normalize_ph_phone_number(value):
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) == 12 and digits.startswith("639"):
        return f"+{digits}"
    if len(digits) == 11 and digits.startswith("09"):
        return f"{PHILIPPINES_COUNTRY_CODE}{digits[1:]}"
    if len(digits) == 10 and digits.startswith("9"):
        return f"{PHILIPPINES_COUNTRY_CODE}{digits}"
    return ""


def _format_ph_phone_number(value):
    normalized = _normalize_ph_phone_number(value)
    if not normalized:
        return _clean_barangay(value)
    local_number = normalized[len(PHILIPPINES_COUNTRY_CODE):]
    return f"{PHILIPPINES_COUNTRY_CODE} {local_number[:3]} {local_number[3:6]} {local_number[6:]}"


def _normalize_barangay(value):
    return "".join(ch.lower() for ch in _clean_barangay(value) if ch.isalnum())


def _resolve_barangay_name(value):
    """Resolve free-text barangay input against the active barangay list."""
    normalized = _normalize_barangay(value)
    if not normalized:
        return ""
    lookup = cache.get(ACTIVE_BARANGAY_LOOKUP_CACHE_KEY)
    if lookup is None:
        lookup = {
            _normalize_barangay(name): name
            for name in Barangay.objects.filter(is_active=True).values_list("name", flat=True)
        }
        cache.set(
            ACTIVE_BARANGAY_LOOKUP_CACHE_KEY,
            lookup,
            ACTIVE_BARANGAY_LOOKUP_CACHE_TTL_SECONDS,
        )
    return lookup.get(normalized, "")


def _ensure_default_profile_image_exists():
    """Copy the default profile image into media storage when needed."""
    default_relative_path = "profile_images/default-user-image.jpg"
    target_path = os.path.join(settings.MEDIA_ROOT, default_relative_path)
    if os.path.exists(target_path):
        return default_relative_path

    source_path = os.path.join(
        settings.BASE_DIR,
        "user",
        "static",
        "images",
        "default-user-image.jpg",
    )
    if not os.path.exists(source_path):
        return default_relative_path

    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    try:
        shutil.copyfile(source_path, target_path)
    except OSError:
        pass

    return default_relative_path


def _profile_image_url_or_default(user, fallback_url):
    """Return a profile image URL or a static fallback for display cards."""
    profile = getattr(user, "profile", None)
    image_field = getattr(profile, "profile_image", None)
    image_url = _safe_media_url(image_field)
    return image_url or fallback_url


def _clean_announcement_text_for_display(raw_html):
    """Strip announcement HTML down to clean display text."""
    text = strip_tags(raw_html or "").replace("\xa0", " ")
    lines = text.splitlines()
    cleaned_lines = [line.lstrip() for line in lines]
    return "\n".join(cleaned_lines).strip()


def _format_posted_label(dt):
    """Render a compact relative time label for feed-style timestamps."""
    if not dt:
        return ""
    now = timezone.now()
    delta = now - dt
    if delta < timedelta(minutes=1):
        return "Just now"
    if delta < timedelta(hours=1):
        minutes = max(int(delta.total_seconds() // 60), 1)
        return f"{minutes}m"
    if delta < timedelta(days=1):
        hours = max(int(delta.total_seconds() // 3600), 1)
        return f"{hours}h"
    if delta < timedelta(days=7):
        days = max(int(delta.total_seconds() // 86400), 1)
        return f"{days}d"
    return dt.strftime("%b %d, %Y")


def _format_datetime_label(dt):
    if not dt:
        return ""
    localized = timezone.localtime(dt) if timezone.is_aware(dt) else dt
    return localized.strftime("%b %d, %Y %I:%M %p")


def _split_time_left(diff):
    total_seconds = max(int(diff.total_seconds()), 0)
    days = total_seconds // 86400
    remainder = total_seconds % 86400
    hours = remainder // 3600
    remainder = remainder % 3600
    minutes = remainder // 60
    return days, hours, minutes


def _clean_rescue_card_copy(value):
    return " ".join(strip_tags(value or "").replace("\xa0", " ").split()).strip()


def _truncate_rescue_card_copy(value, limit=148):
    cleaned = _clean_rescue_card_copy(value)
    if len(cleaned) <= limit:
        return cleaned
    truncated = cleaned[: max(limit - 1, 1)].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return f"{truncated or cleaned[: limit - 1]}..."


def _pluralized_time_label(value, singular):
    return f"{value} {singular}" if value == 1 else f"{value} {singular}s"


def _featured_time_left_emphasis(phase_payload):
    days = phase_payload["days_left"]
    hours = phase_payload["hours_left"]
    minutes = phase_payload["minutes_left"]
    if days > 0:
        return f"{_pluralized_time_label(days, 'day')} left"
    if hours > 0:
        return f"{_pluralized_time_label(hours, 'hour')} left"
    if minutes > 0:
        return f"{_pluralized_time_label(minutes, 'minute')} left"
    return "Ending soon"


def _featured_time_left_tone(phase_payload):
    total_minutes = (
        phase_payload["days_left"] * 24 * 60
        + phase_payload["hours_left"] * 60
        + phase_payload["minutes_left"]
    )
    if total_minutes <= 6 * 60:
        return "critical"
    if total_minutes <= 24 * 60:
        return "urgent"
    return "steady"


def _featured_time_left_context(phase, phase_payload):
    if phase == "claim":
        return "Before the owner redemption window closes."
    return "Before the adoption window closes."


def _post_phase_payload(post):
    phase = post.current_phase() if hasattr(post, "current_phase") else "closed"
    is_pending_review = (
        phase in {"claim", "adopt"}
        and bool(getattr(post, f"has_pending_{phase}_request", False))
    )
    pending_review_until = (
        post.pending_request_review_available_at(phase)
        if is_pending_review and hasattr(post, "pending_request_review_available_at")
        else None
    )
    days = hours = minutes = 0
    if phase in {"claim", "adopt"}:
        days, hours, minutes = _split_time_left(post.time_left())
    return {
        "phase": phase,
        "days_left": days,
        "hours_left": hours,
        "minutes_left": minutes,
        "is_pending_review": is_pending_review,
        "pending_review_until": pending_review_until,
        "pending_review_until_label": _format_datetime_label(pending_review_until),
    }


def _is_post_time_expired(post, phase_payload):
    """
    Return True if the post should be hidden from the public feed.

    A post is expired when:
    - Its phase is 'closed' (both claim and adoption deadlines have passed), OR
    - Its remaining countdown is at zero (days == hours == minutes == 0).

    This applies regardless of whether there are pending adoption or claim
    requests — once the deadline is over the listing is removed from the
    user-facing pages immediately.
    """
    phase = phase_payload.get("phase", "closed")
    if phase == "closed":
        return True
    return (
        phase_payload.get("days_left", 0) == 0 and
        phase_payload.get("hours_left", 0) == 0 and
        phase_payload.get("minutes_left", 0) == 0
    )


def _viewer_staff_post_request_map(user, post_ids):
    """Map staff Post id -> claim/adopt flags for PostRequest rows by this user (any status)."""
    if not user or not getattr(user, "is_authenticated", False) or not post_ids:
        return {}
    normalized_ids = list({int(pk) for pk in post_ids})
    flags = {pid: {"claim": False, "adopt": False} for pid in normalized_ids}
    for pid, rtype in PostRequest.objects.filter(
        user=user, post_id__in=normalized_ids
    ).values_list("post_id", "request_type"):
        if pid in flags and rtype in ("claim", "adopt"):
            flags[pid][rtype] = True
    return flags


def _staff_post_public_cta_flags(phase, user, vf):
    """Which claim/reserve/adopt buttons to show on public cards (guests always see CTAs).

    Logged-in users: claim and reserve (adopt-type request during claim phase) are mutually
    exclusive — only one request type per post. Same for adopt phase vs an existing claim row.
    """
    vf = vf or {"claim": False, "adopt": False}
    if not user or not getattr(user, "is_authenticated", False):
        return {
            "show_claim_cta": phase == "claim",
            "show_reserve_adoption_cta": phase == "claim",
            "show_adopt_cta": phase == "adopt",
        }
    has_claim = vf["claim"]
    has_adopt = vf["adopt"]
    return {
        "show_claim_cta": phase == "claim" and not has_claim and not has_adopt,
        "show_reserve_adoption_cta": phase == "claim" and not has_claim and not has_adopt,
        "show_adopt_cta": phase == "adopt" and not has_adopt and not has_claim,
    }


def _base_public_post_queryset():
    return Post.with_pending_request_state(
        Post.objects.select_related(
            "user", "user__profile"
        ).filter(is_history=False).prefetch_related(
            Prefetch(
                "images",
                queryset=PostImage.objects.only("id", "post_id", "image").order_by("id"),
            )
        )
    ).order_by("-created_at")


def _base_user_adoption_post_queryset():
    return UserAdoptionPost.objects.select_related(
        "owner", "owner__profile"
    ).prefetch_related("images").order_by("-created_at")


def _build_rescue_finder_form(*args, location_choices=None, default_purpose="all", **kwargs):
    return RescueFinderForm(
        *args,
        location_choices=location_choices,
        default_purpose=default_purpose,
        **kwargs,
    )


def _finder_default_purpose(listing_mode):
    """Fresh visits and cleared filters use Purpose = All so every listing is visible."""
    return "all"


def _normalize_rescue_location(value):
    return " ".join((value or "").split()).casefold()


def _merge_rescue_finder_locations(*location_groups):
    merged = []
    seen = set()
    for group in location_groups:
        for value in group or []:
            cleaned = " ".join((value or "").split()).strip()
            if not cleaned:
                continue
            key = _normalize_rescue_location(cleaned)
            if key in seen:
                continue
            seen.add(key)
            merged.append(cleaned)
    return merged


def _rescue_finder_choice_map(field):
    return {
        str(value): label
        for value, label in field.choices
        if value not in {"", None}
    }


def _rescue_finder_post_matches(post, key, value):
    if not value:
        return False
    if key == "color":
        raw_colors = post.colors or []
        if isinstance(raw_colors, str):
            raw_colors = [raw_colors]
        return value in raw_colors
    if key == "location":
        return _normalize_rescue_location(post.location) == _normalize_rescue_location(value)
    return getattr(post, key, "") == value


def _rescue_finder_match_score(post, selected_filters):
    return sum(
        1
        for key, value in selected_filters.items()
        if value and _rescue_finder_post_matches(post, key, value)
    )


def _rescue_finder_phase_priority(phase, preferred_phase):
    if preferred_phase in {"claim", "adopt"}:
        return 0 if phase == preferred_phase else 1
    return 0 if phase == "claim" else 1


def _rescue_finder_title(post):
    return " ".join((post.display_title or "Dog Listing").split())


def _announcement_feed_share_url(request, announcement_id):
    """Public share link: announcements board with ?highlight=<id> (scrolls to the card)."""
    base = request.build_absolute_uri(reverse("user:announcement_list"))
    return f"{base}?{urlencode({'highlight': str(announcement_id)})}"


def _finder_share_url_staff(request, post, phase_payload):
    """
    Public share link: Find a Dog listing scrolled to this card (guests can view the card).
    Claim-phase staff posts use the claim list; adopt-phase use the adopt list; closed posts
    fall back to the read-only post detail overlay.
    """
    phase = phase_payload["phase"]
    pid = post.id
    hl = urlencode({"highlight": f"staff:{pid}"})
    if phase == "claim":
        base = request.build_absolute_uri(reverse("user:redeem_list"))
        return f"{base}?purpose=claim&{hl}"
    if phase == "adopt":
        base = request.build_absolute_uri(reverse("user:adopt_list"))
        return f"{base}?purpose=adopt&{hl}"
    return request.build_absolute_uri(reverse("user:post_detail", args=[pid]))


def _finder_share_url_user_adoption(request, user_post_id):
    """Share link to Find a Dog with the user adoption card highlighted."""
    base = request.build_absolute_uri(reverse("user:adopt_list"))
    return f"{base}?{urlencode({'purpose': 'adopt', 'highlight': f'user:{user_post_id}'})}"


def _parse_finder_highlight(raw):
    raw = (raw or "").strip()
    if ":" not in raw:
        return None, None
    kind, _, rest = raw.partition(":")
    kind = kind.strip().lower()
    rest = rest.strip()
    if kind not in {"staff", "user"} or not rest.isdigit():
        return None, None
    return kind, int(rest)


def _absolute_uri_for_og(request, path_or_url):
    """Build an absolute http(s) URL for Open Graph image fields."""
    if not path_or_url:
        return ""
    raw = (path_or_url or "").strip()
    if raw.startswith(("http://", "https://")):
        return raw
    if raw.startswith("//"):
        return f"{request.scheme}:{raw}"
    return request.build_absolute_uri(raw if raw.startswith("/") else f"/{raw}")


def _finder_highlight_open_graph(request):
    """
    When ?highlight= points at a finder card, expose og:image and text for link previews
    (Facebook, Messenger, X, etc.).
    """
    kind, hid = _parse_finder_highlight(request.GET.get("highlight"))
    if not kind or not hid:
        return {}

    og_url = request.build_absolute_uri(request.get_full_path())
    site = "Bayawan Vet"

    if kind == "staff":
        post = (
            Post.objects.filter(id=hid, is_history=False)
            .prefetch_related("images")
            .first()
        )
        if not post:
            return {}
        img_rel = _first_prefetched_image_url(post.images.all())
        og_image = _absolute_uri_for_og(request, img_rel)
        title = _rescue_finder_title(post)
        location_label = " ".join((post.location or "").split()) or "Bayawan City"
        phase_payload = _post_phase_payload(post)
        phase = phase_payload["phase"]
        if phase == "claim":
            phase_note = "Owner redemption window is open."
        elif phase == "adopt":
            phase_note = "Ready for adoption."
        else:
            phase_note = "Bayawan Vet rescue listing."
        desc = f"{title} — {location_label}. {phase_note}"
        if len(desc) > 300:
            desc = f"{desc[:297].rstrip()}..."
        return {
            "finder_og_title": f"{title} | {site}",
            "finder_og_description": desc,
            "finder_og_image": og_image,
            "finder_og_url": og_url,
        }

    if kind == "user":
        upost = (
            UserAdoptionPost.objects.filter(id=hid)
            .prefetch_related("images")
            .first()
        )
        if not upost:
            return {}
        img_rel = _first_prefetched_image_url(upost.images.all())
        og_image = _absolute_uri_for_og(request, img_rel)
        loc = " ".join((upost.location or "").split()) or "Bayawan City"
        dog = (upost.dog_name or "Dog").strip() or "Dog"
        breed = upost.display_breed or "Adoption"
        desc = f"{dog} ({breed}) — {loc}. Community adoption listing on Bayawan Vet."
        if len(desc) > 300:
            desc = f"{desc[:297].rstrip()}..."
        return {
            "finder_og_title": f"{dog} — {breed} | {site}",
            "finder_og_description": desc,
            "finder_og_image": og_image,
            "finder_og_url": og_url,
        }

    return {}


def _missing_dog_og_context_for_post(request, post):
    """
    Open Graph fields for one missing-dog post. og:url is the public per-post page so
    Facebook and other apps open the same URL users share.
    """
    site = "Bayawan Vet"
    dog = (post.dog_name or "Dog").strip() or "Dog"
    loc = " ".join((post.location or "").split()) or "Bayawan City"
    breed = (post.display_breed or "").strip()
    if breed:
        title = f"{dog} — Missing ({breed}) | {site}"
    else:
        title = f"{dog} — Missing Dog | {site}"
    desc = f"Help find {dog}. Last seen near {loc}. Report a sighting on Bayawan Vet."
    if len(desc) > 300:
        desc = f"{desc[:297].rstrip()}..."

    if post.image:
        og_image = _absolute_uri_for_og(request, post.image.url)
    else:
        og_image = request.build_absolute_uri(static("images/bayawan_logo.webp"))

    og_url = request.build_absolute_uri(
        reverse("user:missing_dog_public_detail", args=[post.pk])
    )
    return {
        "missing_og_title": title,
        "missing_og_description": desc,
        "missing_og_image": og_image,
        "missing_og_url": og_url,
    }


def _missing_dog_public_share_url(request, post_id):
    """Absolute URL for the public one-post page (all share UIs use this)."""
    return request.build_absolute_uri(
        reverse("user:missing_dog_public_detail", args=[post_id])
    )


def _missing_dog_highlight_open_graph(request):
    """
    When ?highlight=<id> points at a missing-dog post, expose og tags for link previews.
    Canonical og:url is the per-post public URL (not the list querystring).
    """
    raw = (request.GET.get("highlight") or "").strip()
    if not raw.isdigit():
        return {}
    pk = int(raw)
    post = MissingDogPost.objects.filter(
        pk=pk, status__in=["missing", "found"]
    ).first()
    if not post:
        return {}
    return _missing_dog_og_context_for_post(request, post)


def _announcement_highlight_open_graph(request):
    """Open Graph tags when ?highlight=<id> targets a specific announcement card."""
    raw = (request.GET.get("highlight") or "").strip()
    if not raw.isdigit():
        return {}
    pk = int(raw)
    post = (
        DogAnnouncement.objects.select_related("created_by")
        .prefetch_related(
            Prefetch(
                "images",
                queryset=DogAnnouncementImage.objects.only(
                    "id",
                    "announcement_id",
                    "image",
                    "created_at",
                ).order_by("created_at", "id"),
                to_attr="prefetched_images",
            ),
        )
        .filter(pk=pk)
        .first()
    )
    if not post:
        return {}

    og_image = ""
    if post.background_image:
        og_image = request.build_absolute_uri(post.background_image.url)
    elif getattr(post, "prefetched_images", None):
        og_image = request.build_absolute_uri(post.prefetched_images[0].image.url)
    else:
        og_image = request.build_absolute_uri(static("images/bayawan_logo.webp"))

    plain = strip_tags(post.content or "").strip()
    if len(plain) > 200:
        plain = f"{plain[:197].rstrip()}..."
    if not plain:
        plain = "Announcement from Bayawan Vet."

    title = (post.title or "Announcement").strip()
    og_url = request.build_absolute_uri(request.get_full_path())
    site = "Bayawan Vet"

    return {
        "announcement_og_title": f"{title} | {site}",
        "announcement_og_description": plain,
        "announcement_og_image": og_image,
        "announcement_og_url": og_url,
    }


def _finder_maybe_redirect_for_highlight(
    request,
    claim_items,
    adopt_items,
    user_adoption_items,
    selected_purpose,
):
    """
    When ?highlight= is present, redirect to the correct purpose and page so the
    target card is in the unified paginated list.
    """
    kind, hid = _parse_finder_highlight(request.GET.get("highlight"))
    if not kind or not hid:
        return None

    path = request.path
    params = request.GET.copy()
    highlight_val = f"{kind}:{hid}"

    def _find_index(entries):
        if kind == "user":
            return next(
                (
                    i
                    for i, e in enumerate(entries)
                    if e[0] == "user" and e[1].get("post_id") == hid
                ),
                None,
            )
        return next(
            (
                i
                for i, e in enumerate(entries)
                if e[0] == "staff" and e[1]["post"].id == hid
            ),
            None,
        )

    purpose_candidates = [selected_purpose]
    if selected_purpose != "all":
        purpose_candidates.append("all")

    target_idx = None
    target_purpose = None
    for purpose in purpose_candidates:
        entries = _finder_unified_entries(
            purpose, claim_items, adopt_items, user_adoption_items
        )
        idx = _find_index(entries)
        if idx is not None:
            target_idx = idx
            target_purpose = purpose
            break

    if target_idx is None:
        return None

    page_need = target_idx // RESCUE_FINDER_PAGE_SIZE + 1
    cur_page = int(request.GET.get("page") or 1)
    params["highlight"] = highlight_val

    if target_purpose != selected_purpose or cur_page != page_need:
        params["purpose"] = target_purpose
        params["page"] = str(page_need)
        return f"{path}?{params.urlencode()}"
    return None


def _announcement_maybe_redirect_for_highlight(request):
    raw = (request.GET.get("highlight") or "").strip()
    if not raw.isdigit():
        return None
    pk = int(raw)
    bucket_data = DogAnnouncement.objects.filter(pk=pk).values_list("display_bucket", flat=True).first()
    if bucket_data is None:
        return None
    if bucket_data == DogAnnouncement.BUCKET_PINNED:
        return None

    regular_qs = (
        _announcement_feed_queryset()
        .exclude(display_bucket=DogAnnouncement.BUCKET_PINNED)
        .order_by("-created_at")
    )
    ids = list(regular_qs.values_list("id", flat=True))
    if pk not in ids:
        return None

    pos = ids.index(pk)
    page_need = pos // PUBLIC_ANNOUNCEMENT_PAGE_SIZE + 1
    cur = int(request.GET.get("page") or 1)
    if cur == page_need:
        return None

    params = request.GET.copy()
    params["page"] = str(page_need)
    params["highlight"] = str(pk)
    return f"{reverse('user:announcement_list')}?{params.urlencode()}"


def _build_rescue_finder_card_item(
    request,
    post,
    phase_payload,
    match_score,
    *,
    viewer_request_map=None,
):
    phase = phase_payload["phase"]
    days = phase_payload["days_left"]
    hours = phase_payload["hours_left"]
    minutes = phase_payload["minutes_left"]
    pending_review_until_label = phase_payload["pending_review_until_label"]
    location_label = " ".join((post.location or "").split()) or "Location not listed"
    countdown_deadline = (
        post.claim_deadline()
        if phase == "claim"
        else post.adoption_deadline()
    )
    countdown_deadline_local = (
        timezone.localtime(countdown_deadline)
        if countdown_deadline and timezone.is_aware(countdown_deadline)
        else countdown_deadline
    )
    phase_title = "Ready to Redeem" if phase == "claim" else "Ready for Adoption"
    share_url = _finder_share_url_staff(request, post, phase_payload)
    action_url = (
        reverse("user:redeem_confirm", args=[post.id])
        if phase == "claim"
        else reverse("user:adopt_confirm", args=[post.id])
    )
    reserve_adoption_url = reverse("user:adopt_confirm", args=[post.id])
    vf = {"claim": False, "adopt": False}
    if getattr(request.user, "is_authenticated", False):
        if viewer_request_map is None:
            viewer_request_map = _viewer_staff_post_request_map(request.user, [post.id])
        vf = viewer_request_map.get(post.id, vf)
    cta_flags = _staff_post_public_cta_flags(phase, request.user, vf)
    return {
        "post": post,
        "phase": phase,
        "phase_label": "Redeem" if phase == "claim" else "Adopt",
        "phase_title": phase_title,
        "days_left": days,
        "hours_left": hours,
        "minutes_left": minutes,
        "main_image_url": _first_prefetched_image_url(post.images.all()),
        "lightbox_image_json": json.dumps(_prefetched_image_urls(post.images.all())),
        "title": _rescue_finder_title(post),
        "breed_label": post.display_breed or "Unknown Breed",
        "age_label": post.display_age_group or "Age not listed",
        "size_label": post.display_size_group or "Size not listed",
        "gender_label": post.get_gender_display() if post.gender else "Gender not listed",
        "coat_label": post.display_coat_length or "Coat not listed",
        "color_label": post.display_colors or "Color not listed",
        "location_label": location_label,
        "barangay_label": location_label,
        "detail_url": reverse("user:post_detail", args=[post.id]),
        "action_label": "Redeem" if phase == "claim" else "Adopt",
        "action_url": action_url,
        "reserve_adoption_url": reserve_adoption_url,
        "viewer_has_claim_request": vf["claim"],
        "viewer_has_adopt_request": vf["adopt"],
        **cta_flags,
        "time_left_badge": f"{days}d {hours}h {minutes}m left",
        "countdown_date_heading": "Redemption Ends" if phase == "claim" else "Adoption Ends",
        "countdown_date_label": (
            countdown_deadline_local.strftime("%b %d, %Y")
            if countdown_deadline_local
            else "Date pending"
        ),
        "share_url": share_url,
        "match_score": match_score,
        "is_pending_review": phase_payload["is_pending_review"],
        "show_countdown": phase in {"claim", "adopt"} and bool(countdown_deadline),
        "pending_state_label": "",
        "pending_state_detail": "",
        "pending_review_until_label": pending_review_until_label,
        "deadline_iso": countdown_deadline.isoformat() if countdown_deadline else "",
        "sort_deadline_ts": (
            countdown_deadline.timestamp()
            if countdown_deadline
            else float("inf")
        ),
    }


def _build_rescue_finder_filter_sections(form, selected_filters):
    icon_map = {
        "breed": "bi bi-tag",
        "age_group": "bi bi-calendar-heart",
        "size_group": "bi bi-arrows-angle-expand",
        "gender": "bi bi-gender-ambiguous",
        "coat_length": "bi bi-scissors",
        "color": "bi bi-palette",
        "location": "bi bi-geo-alt",
    }
    sections = []
    for key in RescueFinderForm.FILTER_FIELDS:
        field = form.fields[key]
        choice_map = _rescue_finder_choice_map(field)
        sections.append({
            "key": key,
            "label": field.label,
            "icon_class": icon_map.get(key, "bi bi-sliders"),
            "value": selected_filters.get(key, ""),
            "value_label": choice_map.get(selected_filters.get(key, ""), ""),
            "clear_label": field.choices[0][1] if field.choices else "",
            "options": [
                {"value": str(value), "label": label}
                for value, label in field.choices
                if value not in {"", None}
            ],
        })
    return sections


def _build_rescue_finder_selected_chips(form, selected_filters):
    chips = []
    for key in RescueFinderForm.FILTER_FIELDS:
        value = selected_filters.get(key, "")
        if not value:
            continue
        field = form.fields[key]
        chips.append({
            "key": key,
            "label": field.label,
            "value_label": _rescue_finder_choice_map(field).get(value, value),
        })
    return chips


def _filter_public_posts(posts_qs, listing_mode, filter_type):
    posts = list(posts_qs)
    Post.attach_active_appointment_dates(posts)
    active_statuses = ["rescued", "under_care"]

    if listing_mode == "claim":
        allowed_filters = {"all", "ready_claim", "reunited"}
        if filter_type not in allowed_filters:
            filter_type = "all"

        if filter_type == "ready_claim":
            posts = [
                post
                for post in posts
                if post.status in active_statuses and post.current_phase() == "claim"
            ]
        elif filter_type == "reunited":
            posts = [post for post in posts if post.status == "reunited"]
        else:
            posts = [
                post
                for post in posts
                if post.status == "reunited"
                or (post.status in active_statuses and post.current_phase() == "claim")
            ]
        return posts, filter_type

    allowed_filters = {"all", "ready_adopt", "adopted"}
    if filter_type not in allowed_filters:
        filter_type = "all"

    if filter_type == "ready_adopt":
        posts = [
            post
            for post in posts
            if post.status in active_statuses and post.current_phase() == "adopt"
        ]
    elif filter_type == "adopted":
        posts = [post for post in posts if post.status == "adopted"]
    else:
        posts = [
            post
            for post in posts
            if post.status == "adopted"
            or (post.status in active_statuses and post.current_phase() == "adopt")
        ]

    return posts, filter_type


def _filter_user_adoption_posts(posts_qs, filter_type):
    allowed_filters = {"all", "ready_adopt", "adopted"}
    if filter_type not in allowed_filters:
        filter_type = "all"

    if filter_type == "ready_adopt":
        posts_qs = posts_qs.filter(status="available")
    elif filter_type == "adopted":
        posts_qs = posts_qs.filter(status="adopted")

    return posts_qs, filter_type


def _finder_unified_sort_key(entry):
    """Sort by soonest window end (claim or adopt), then match quality, then stability."""
    kind, item = entry
    deadline_ts = item.get("sort_deadline_ts")
    if deadline_ts is None:
        deadline_ts = float("inf")
    if kind == "user":
        return (
            deadline_ts,
            -item.get("match_score", 0),
            0 if item.get("main_image_url") else 1,
            -item["created_at"].timestamp(),
            item["post_id"],
        )
    return (
        deadline_ts,
        -item.get("match_score", 0),
        0 if item.get("main_image_url") else 1,
        item["post"].id,
    )


def _finder_unified_entries(selected_purpose, claim_items, adopt_items, user_adoption_items):
    """Merge finder rows for the active Purpose filter (single scrollable list)."""
    if selected_purpose == "all":
        parts = (
            [("staff", c) for c in claim_items]
            + [("staff", a) for a in adopt_items]
            + [("user", u) for u in user_adoption_items]
        )
    elif selected_purpose == "claim":
        parts = [("staff", c) for c in claim_items]
    elif selected_purpose == "adopt":
        parts = [("staff", a) for a in adopt_items] + [("user", u) for u in user_adoption_items]
    else:
        parts = []
    parts.sort(key=_finder_unified_sort_key)
    return parts


def _build_public_post_listing(request, listing_mode):
    """Build the rescue finder page using real rescue-post phases and profile filters."""
    preferred_purpose = _finder_default_purpose(listing_mode)
    raw_open_posts = list(
        _base_public_post_queryset()
        .filter(status__in=["rescued", "under_care"])
    )
    Post.attach_active_appointment_dates(raw_open_posts)

    open_post_rows = []
    location_map = {}
    phase_counts = {"all": 0, "claim": 0, "adopt": 0}
    for post in raw_open_posts:
        phase_payload = _post_phase_payload(post)
        phase = phase_payload["phase"]
        if phase not in {"claim", "adopt"}:
            continue
        if _is_post_time_expired(post, phase_payload):
            continue
        open_post_rows.append((post, phase_payload))
        phase_counts["all"] += 1
        phase_counts[phase] += 1
        location_value = " ".join((post.location or "").split())
        if location_value:
            location_map.setdefault(_normalize_rescue_location(location_value), location_value)

    finder_form = _build_rescue_finder_form(
        location_choices=_merge_rescue_finder_locations(
            BAYAWAN_BARANGAYS,
            sorted(location_map.values(), key=str.lower),
        ),
        default_purpose=preferred_purpose,
    )
    purpose_choice_map = _rescue_finder_choice_map(finder_form.fields["purpose"])
    selected_purpose = (request.GET.get("purpose") or "").strip()
    if selected_purpose not in purpose_choice_map:
        selected_purpose = preferred_purpose

    selected_filters = {}
    for key in RescueFinderForm.FILTER_FIELDS:
        raw_value = (request.GET.get(key) or "").strip()
        allowed_values = _rescue_finder_choice_map(finder_form.fields[key])
        selected_filters[key] = raw_value if raw_value in allowed_values else ""

    active_filter_chips = _build_rescue_finder_selected_chips(finder_form, selected_filters)
    active_filter_count = len(active_filter_chips)

    open_post_ids = [p.id for p, _ in open_post_rows]
    viewer_staff_request_map = _viewer_staff_post_request_map(request.user, open_post_ids)

    claim_items = []
    adopt_items = []

    def _staff_finder_sort_key(item):
        ts = item.get("sort_deadline_ts")
        if ts is None:
            ts = float("inf")
        return (
            ts,
            -item["match_score"],
            0 if item["main_image_url"] else 1,
            item["post"].id,
        )
    for post, phase_payload in open_post_rows:
        phase = phase_payload["phase"]
        match_score = _rescue_finder_match_score(post, selected_filters)
        card = _build_rescue_finder_card_item(
            request,
            post,
            phase_payload,
            match_score,
            viewer_request_map=viewer_staff_request_map,
        )
        if phase == "claim":
            claim_items.append(card)
        else:
            adopt_items.append(card)
    claim_items.sort(key=_staff_finder_sort_key)
    adopt_items.sort(key=_staff_finder_sort_key)

    user_adoption_qs = (
        UserAdoptionPost.objects
        .filter(status="available")
        .select_related("owner", "owner__profile")
        .prefetch_related(
            Prefetch(
                "images",
                queryset=UserAdoptionImage.objects.only("id", "post_id", "image").order_by("id"),
            )
        )
        .order_by("-created_at")
    )
    user_adoption_items = []
    for upost in user_adoption_qs:
        if any(
            selected_filters[k]
            and not _rescue_finder_post_matches(upost, k, selected_filters[k])
            for k in selected_filters
        ):
            continue
        match_score = _rescue_finder_match_score(upost, selected_filters)
        location_label = " ".join((upost.location or "").split()) or "Location not listed"
        detail_url = reverse("user:user_adoption_post_detail", args=[upost.id])
        user_adoption_items.append({
            "post": upost,
            "post_id": upost.id,
            "dog_name": upost.dog_name,
            "breed_label": upost.display_breed or "Unknown Breed",
            "age_label": upost.display_age_group or "Age not listed",
            "size_label": upost.display_size_group or "Size not listed",
            "gender_label": upost.get_gender_display() if upost.gender else "Gender not listed",
            "coat_label": upost.display_coat_length or "Coat not listed",
            "color_label": upost.display_colors or "Color not listed",
            "location_label": location_label,
            "description": upost.description or "",
            "owner_username": upost.owner.username,
            "owner_full_name": upost.owner.get_full_name(),
            "main_image_url": _first_prefetched_image_url(upost.images.all()),
            "lightbox_image_json": json.dumps(_prefetched_image_urls(upost.images.all())),
            "match_score": match_score,
            "created_at": upost.created_at,
            "detail_url": detail_url,
            "share_url": _finder_share_url_user_adoption(request, upost.id),
            "is_vaccinated": upost.is_vaccinated,
            "is_registered": upost.is_registered,
            "sort_deadline_ts": float("inf"),
        })

    user_adopt_count = len(user_adoption_items)
    phase_counts["adopt"] += user_adopt_count
    phase_counts["all"] += user_adopt_count

    unified_entries_all = _finder_unified_entries(
        selected_purpose, claim_items, adopt_items, user_adoption_items
    )
    recommended_posts = []
    if active_filter_count:
        best_item = None
        best_score = -1
        for entry_kind, entry_item in unified_entries_all:
            if entry_kind != "staff":
                continue
            sc = entry_item.get("match_score", 0)
            if sc > best_score:
                best_score = sc
                best_item = entry_item
        if best_item is not None and best_score > 0:
            recommended_posts = [best_item]

    unified_paginator = Paginator(unified_entries_all, RESCUE_FINDER_PAGE_SIZE)
    unified_page_obj = unified_paginator.get_page(request.GET.get("page", 1))
    page_pairs = list(unified_page_obj.object_list)
    finder_unified_rows = [{"kind": k, "item": item} for k, item in page_pairs]
    hl_kind, hl_id = _parse_finder_highlight(request.GET.get("highlight"))
    for row in finder_unified_rows:
        item = row["item"]
        is_hl = False
        if hl_kind and hl_id:
            if row["kind"] == "staff" and hl_kind == "staff" and item["post"].id == hl_id:
                is_hl = True
            elif row["kind"] == "user" and hl_kind == "user" and item["post_id"] == hl_id:
                is_hl = True
        item["is_share_highlight"] = is_hl
    posts = [item for k, item in page_pairs if k == "staff"]
    claim_posts = [
        item for k, item in page_pairs if k == "staff" and item["phase"] == "claim"
    ]
    adopt_posts = [
        item for k, item in page_pairs if k == "staff" and item["phase"] == "adopt"
    ]
    user_adoption_posts = [item for k, item in page_pairs if k == "user"]

    purpose_options = [
        {
            "value": "all",
            "label": purpose_choice_map.get("all", "All"),
            "count": phase_counts["all"],
            "icon_key": "all",
        },
        {
            "value": "claim",
            "label": purpose_choice_map.get("claim", "Redeem"),
            "count": phase_counts["claim"],
            "icon_key": "claim",
        },
        {
            "value": "adopt",
            "label": purpose_choice_map.get("adopt", "Adopt"),
            "count": phase_counts["adopt"],
            "icon_key": "adopt",
        },
    ]
    current_purpose_option = next(
        (option for option in purpose_options if option["value"] == selected_purpose),
        purpose_options[0],
    )

    highlight_redirect = _finder_maybe_redirect_for_highlight(
        request,
        claim_items,
        adopt_items,
        user_adoption_items,
        selected_purpose,
    )

    context = {
        "listing_mode": listing_mode,
        "page_title": "Find a Dog",
        "page_description": "Browse active dogs and post a dog for adoption or as missing.",
        "purpose_choices": list(finder_form.fields["purpose"].choices),
        "purpose_options": purpose_options,
        "current_purpose": selected_purpose,
        "current_purpose_label": current_purpose_option["label"],
        "current_purpose_count": current_purpose_option["count"],
        "purpose_counts": phase_counts,
        "filter_sections": _build_rescue_finder_filter_sections(
            finder_form,
            selected_filters,
        ),
        "active_filter_chips": active_filter_chips,
        "active_filter_count": active_filter_count,
        "finder_unified_rows": finder_unified_rows,
        "unified_page_obj": unified_page_obj,
        "finder_pagination_items": _build_pagination_tokens(unified_page_obj),
        "recommended_posts": recommended_posts,
        "claim_posts": claim_posts,
        "adopt_posts": adopt_posts,
        "posts": posts,
        "user_adoption_posts": user_adoption_posts,
        "pagination_query": _pagination_query_without_page(request.GET),
        "clear_filters_url": (
            f"{reverse('user:redeem_list' if listing_mode == 'claim' else 'user:adopt_list')}"
            f"?{urlencode({'purpose': 'all'})}"
        ),
        "request_links": [
            {
                "url": reverse("user:my_redemptions"),
                "label": "Redemptions",
                "icon_class": "bi bi-shield-check",
            },
            {
                "url": reverse("user:adopt_status"),
                "label": "Adoption requests",
                "icon_class": "bi bi-house-heart",
            },
            {
                "url": reverse("user:user_adoption_requests"),
                "label": "Incoming",
                "icon_class": "bi bi-inbox",
            },
            {
                "url": reverse("user:adoption_history"),
                "label": "History",
                "icon_class": "bi bi-clock-history",
            },
            {
                "url": reverse("user:my_post_approvals"),
                "label": "Approvals",
                "icon_class": "bi bi-patch-check",
            },
        ],
    }
    return context, highlight_redirect


def _build_home_featured_rescue_sections(request, *, appointment_dates=None):
    raw_open_posts = list(
        _base_public_post_queryset()
        .filter(status__in=["rescued", "under_care"])
        [:HOME_FEATURED_CANDIDATE_LIMIT]
    )
    Post.attach_active_appointment_dates(raw_open_posts, appointment_dates)
    section_items = {"claim": [], "adopt": []}
    featured_post_ids = [p.id for p in raw_open_posts]
    viewer_staff_request_map = _viewer_staff_post_request_map(request.user, featured_post_ids)

    for post in raw_open_posts:
        phase_payload = _post_phase_payload(post)
        phase = phase_payload["phase"]
        if phase not in section_items or len(section_items[phase]) >= HOME_FEATURED_CAROUSEL_LIMIT:
            continue
        if _is_post_time_expired(post, phase_payload):
            continue

        card_item = _build_rescue_finder_card_item(
            request,
            post,
            phase_payload,
            0,
            viewer_request_map=viewer_staff_request_map,
        )
        card_item.update({
            "home_action_url": f'{card_item["action_url"]}?return_to=home',
            "barangay_label": card_item["location_label"],
            "carousel_phase": phase,
        })
        section_items[phase].append(card_item)

        if all(len(items) >= HOME_FEATURED_CAROUSEL_LIMIT for items in section_items.values()):
            break

    claim_queue = list(section_items["claim"])
    adopt_queue = list(section_items["adopt"])
    unified_items = []
    while len(unified_items) < HOME_FEATURED_UNIFIED_CAROUSEL_LIMIT and (claim_queue or adopt_queue):
        if claim_queue:
            unified_items.append(claim_queue.pop(0))
        if len(unified_items) >= HOME_FEATURED_UNIFIED_CAROUSEL_LIMIT:
            break
        if adopt_queue:
            unified_items.append(adopt_queue.pop(0))

    input_ids = [
        f"home-carousel-browse-{index}"
        for index in range(1, len(unified_items) + 1)
    ]
    for index, item in enumerate(unified_items):
        item["input_id"] = input_ids[index]
        item["previous_input_id"] = input_ids[index - 1] if input_ids else ""
        item["next_input_id"] = input_ids[(index + 1) % len(input_ids)] if input_ids else ""

    sections = [
        {
            "key": "browse",
            "title": "Find dogs waiting for you",
            "eyebrow": "Browse dogs",
            "description": "Meet rescues open for owner redemption or ready to adopt—swipe through and take the next step.",
            "browse_url": reverse("user:adopt_list"),
            "browse_url_redeem": reverse("user:redeem_list"),
            "empty_message": "No dogs are in the redemption or adoption windows right now. Check back soon.",
            "items": unified_items,
        },
    ]

    return sections


def _home_spotlight_remaining_seconds(post, phase_payload):
    return max(int(post.time_left().total_seconds()), 0)


def _home_spotlight_sort_key(item):
    post, phase_payload = item
    return (
        _home_spotlight_remaining_seconds(post, phase_payload),
        post.created_at.timestamp() if post.created_at else 0,
        post.id,
    )


def _home_spotlight_has_urgent_remaining_time(item):
    return _home_spotlight_remaining_seconds(*item) <= HOME_SPOTLIGHT_URGENCY_THRESHOLD_SECONDS


def _home_spotlight_random_fill(candidate_pairs, limit):
    shuffled_pairs = list(candidate_pairs)
    random.shuffle(shuffled_pairs)
    return shuffled_pairs[:limit]


def _home_spotlight_pick_auto_pairs(candidate_pairs, limit):
    if not candidate_pairs or limit <= 0:
        return []

    urgent_pairs = [item for item in candidate_pairs if _home_spotlight_has_urgent_remaining_time(item)]
    if urgent_pairs:
        urgent_pairs.sort(key=_home_spotlight_sort_key)
        selected_pairs = urgent_pairs[:limit]
        if len(selected_pairs) >= limit:
            return selected_pairs

        selected_ids = {post.id for post, _ in selected_pairs}
        remaining_pairs = [item for item in candidate_pairs if item[0].id not in selected_ids]
        selected_pairs.extend(_home_spotlight_random_fill(remaining_pairs, limit - len(selected_pairs)))
        return selected_pairs

    return _home_spotlight_random_fill(candidate_pairs, limit)


def _build_home_spotlight_card(
    request,
    post,
    phase_payload,
    *,
    is_auto_highlighted=False,
    viewer_request_map=None,
):
    phase = phase_payload["phase"]
    card_item = _build_rescue_finder_card_item(
        request,
        post,
        phase_payload,
        0,
        viewer_request_map=viewer_request_map,
    )
    countdown_deadline = (
        post.claim_deadline()
        if phase == "claim"
        else post.adoption_deadline()
    )
    countdown_deadline_local = (
        timezone.localtime(countdown_deadline)
        if countdown_deadline and timezone.is_aware(countdown_deadline)
        else countdown_deadline
    )
    pinned_at_local = (
        timezone.localtime(post.pinned_at)
        if post.pinned_at and timezone.is_aware(post.pinned_at)
        else post.pinned_at
    )

    if phase == "claim":
        spotlight_copy = (
            "Auto-highlighted because it has the least time left before the redemption window closes."
            if is_auto_highlighted
            else "Still within the owner redemption window."
        )
    else:
        spotlight_copy = (
            "Auto-highlighted because it has the least time left before adoption closes."
            if is_auto_highlighted
            else "Ready for a new family to adopt."
        )

    show_spotlight_primary_cta = False
    primary_cta_label = ""
    primary_cta_url = ""
    primary_requires_auth = True
    if phase == "claim":
        if card_item["show_claim_cta"]:
            show_spotlight_primary_cta = True
            primary_cta_label = "Redeem Dog"
            primary_cta_url = f'{card_item["action_url"]}?return_to=home'
        elif card_item["show_reserve_adoption_cta"]:
            show_spotlight_primary_cta = True
            primary_cta_label = "Reserve Adoption"
            primary_cta_url = f'{card_item["reserve_adoption_url"]}?return_to=home'
    elif phase == "adopt" and card_item["show_adopt_cta"]:
        show_spotlight_primary_cta = True
        primary_cta_label = "Adopt Dog"
        primary_cta_url = f'{card_item["action_url"]}?return_to=home'

    return {
        "post": post,
        "title": card_item["title"] or f"Rescue Dog #{post.id}",
        "detail_url": reverse("user:post_detail", args=[post.id]),
        "main_image_url": card_item["main_image_url"],
        "share_url": card_item["share_url"],
        "image_alt": f'{card_item["title"] or "Pinned rescue"} dog photo',
        "phase": phase,
        "phase_title": card_item["phase_title"],
        "location_label": card_item["location_label"],
        "breed_label": card_item["breed_label"],
        "age_label": card_item["age_label"],
        "size_label": card_item["size_label"],
        "gender_label": card_item["gender_label"],
        "coat_label": card_item["coat_label"],
        "color_label": card_item["color_label"],
        "time_left_badge": card_item["time_left_badge"],
        "countdown_date_heading": card_item["countdown_date_heading"],
        "countdown_date_label": (
            countdown_deadline_local.strftime("%b %d, %Y %I:%M %p")
            if countdown_deadline_local
            else "Date pending"
        ),
        "support_title": (
            "Auto-highlighted by Bayawan Vet"
            if is_auto_highlighted
            else "Pinned by Bayawan Vet"
        ),
        "spotlight_copy": spotlight_copy,
        "show_spotlight_primary_cta": show_spotlight_primary_cta,
        "primary_cta_label": primary_cta_label,
        "primary_cta_url": primary_cta_url,
        "primary_requires_auth": primary_requires_auth,
        "viewer_has_claim_request": card_item["viewer_has_claim_request"],
        "viewer_has_adopt_request": card_item["viewer_has_adopt_request"],
        "show_claim_cta": card_item["show_claim_cta"],
        "show_reserve_adoption_cta": card_item["show_reserve_adoption_cta"],
        "show_adopt_cta": card_item["show_adopt_cta"],
        "pinned_on_label": (
            "Auto-selected from soonest deadline"
            if is_auto_highlighted
            else (
                pinned_at_local.strftime("%b %d, %Y")
                if pinned_at_local
                else _format_datetime_label(post.created_at)
            )
        ),
        "is_auto_highlighted": is_auto_highlighted,
    }


def _build_home_pinned_rescue_spotlights(request, *, appointment_dates=None):
    pinned_posts = list(
        _base_public_post_queryset()
        .filter(is_pinned=True, status__in=["rescued", "under_care"])
        .order_by("-pinned_at", "-created_at")[:HOME_SPOTLIGHT_DISPLAY_LIMIT]
    )
    pinned_viewer_map = _viewer_staff_post_request_map(
        request.user,
        [p.id for p in pinned_posts],
    )
    spotlight_items = []
    if pinned_posts:
        Post.attach_active_appointment_dates(pinned_posts, appointment_dates)
        for post in pinned_posts:
            phase_payload = _post_phase_payload(post)
            phase = phase_payload["phase"]
            if phase not in {"claim", "adopt"}:
                continue
            if _is_post_time_expired(post, phase_payload):
                continue
            spotlight_items.append(
                _build_home_spotlight_card(
                    request,
                    post,
                    phase_payload,
                    viewer_request_map=pinned_viewer_map,
                )
            )
    remaining_slots = HOME_SPOTLIGHT_DISPLAY_LIMIT - len(spotlight_items)
    if remaining_slots > 0:
        fallback_candidates = list(
            _base_public_post_queryset()
            .filter(is_pinned=False, status__in=["rescued", "under_care"])
            [:HOME_SPOTLIGHT_FALLBACK_CANDIDATE_LIMIT]
        )
        Post.attach_active_appointment_dates(fallback_candidates, appointment_dates)
        fallback_viewer_map = _viewer_staff_post_request_map(
            request.user,
            [p.id for p in fallback_candidates],
        )
        candidate_pairs = []
        for post in fallback_candidates:
            phase_payload = _post_phase_payload(post)
            if phase_payload["phase"] not in {"claim", "adopt"}:
                continue
            if _is_post_time_expired(post, phase_payload):
                continue
            candidate_pairs.append((post, phase_payload))

        if candidate_pairs:
            for post, phase_payload in _home_spotlight_pick_auto_pairs(candidate_pairs, remaining_slots):
                spotlight_items.append(
                    _build_home_spotlight_card(
                        request,
                        post,
                        phase_payload,
                        is_auto_highlighted=True,
                        viewer_request_map=fallback_viewer_map,
                    )
                )

    spotlight_count = len(spotlight_items)
    has_manual_pins = any(not item["is_auto_highlighted"] for item in spotlight_items)
    has_auto_spotlights = any(item["is_auto_highlighted"] for item in spotlight_items)
    if has_manual_pins and has_auto_spotlights:
        spotlight_mode = "mixed"
    elif has_manual_pins:
        spotlight_mode = "manual"
    else:
        spotlight_mode = "auto"

    if spotlight_mode == "manual":
        spotlight_title = "Pinned Dogs"
        spotlight_eyebrow = "Pinned by Bayawan Vet"
        spotlight_count_label = f"{spotlight_count} pinned"
    elif spotlight_mode == "auto":
        spotlight_title = "Highlighted Dogs"
        spotlight_eyebrow = "Auto-highlighted by Bayawan Vet"
        spotlight_count_label = f"{spotlight_count} highlighted"
    else:
        spotlight_title = "Pinned Dogs"
        spotlight_eyebrow = "Pinned first, auto-filled by Bayawan Vet"
        spotlight_count_label = f"{spotlight_count} spotlighted"

    return {
        "pinned_admin_spotlights": spotlight_items,
        "pinned_admin_spotlights_mode": spotlight_mode,
        "pinned_admin_spotlights_title": spotlight_title,
        "pinned_admin_spotlights_eyebrow": spotlight_eyebrow,
        "pinned_admin_spotlights_count_label": spotlight_count_label,
    }


def _create_user_adoption_images(request, post):
    main_image = request.FILES.get("adoption-main_image") or request.FILES.get("main_image")
    if main_image:
        UserAdoptionImage.objects.create(post=post, image=main_image)
    extra_images = request.FILES.getlist("extra_images")
    if not extra_images:
        extra_images = request.FILES.getlist("adoption-extra_images")
    for img in extra_images:
        UserAdoptionImage.objects.create(post=post, image=img)


def _save_missing_dog_photos(request, post):
    """Store uploaded photos: first is the post's main image; the rest go to MissingDogPhoto."""
    photos = request.FILES.getlist("missing-image")
    if not photos:
        return
    if post.image != photos[0]:
        post.image = photos[0]
        post.save(update_fields=["image"])
    for extra in photos[1:]:
        MissingDogPhoto.objects.create(post=post, image=extra)


def _build_user_adoption_post_form(*args, **kwargs):
    """Return the adoption-post form with a stable prefix for shared pages."""
    return UserAdoptionPostForm(*args, prefix="adoption", **kwargs)


def _build_missing_dog_post_form(*args, **kwargs):
    """Return the missing-dog form with a stable prefix for shared pages."""
    return MissingDogPostForm(*args, prefix="missing", **kwargs)


def _handle_user_post_creation_submission(request, selected_type):
    """Create a user adoption or missing-dog post from the submitted form."""
    adoption_form = _build_user_adoption_post_form()
    missing_form = _build_missing_dog_post_form()

    if selected_type == "missing":
        missing_form = _build_missing_dog_post_form(request.POST, request.FILES)
        if missing_form.is_valid():
            post = missing_form.save(commit=False)
            post.owner = request.user
            post.save()
            _save_missing_dog_photos(request, post)
            bump_user_home_feed_namespace()
            invalidate_user_notification_content()
            messages.success(request, "Missing dog post created successfully.")
            return True, adoption_form, missing_form
        messages.error(request, "Missing dog post was not saved. Check the required fields and try again.")
        return False, adoption_form, missing_form

    adoption_form = _build_user_adoption_post_form(request.POST, request.FILES)
    if adoption_form.is_valid():
        post = adoption_form.save(commit=False)
        post.owner = request.user
        post.save()
        _create_user_adoption_images(request, post)
        bump_user_home_feed_namespace()
        invalidate_user_notification_content()
        messages.success(request, "Adoption post created successfully.")
        return True, adoption_form, missing_form

    messages.error(request, "Adoption post was not saved. Check the required fields and try again.")
    return False, adoption_form, missing_form


def _normalize_user_post_type(raw_value):
    """Return a supported user post type or an empty string."""
    post_type = (raw_value or "").strip().lower()
    return post_type if post_type in {"adoption", "missing"} else ""


def _build_public_listing_url(listing_mode, *, open_post_panel=False, selected_type=""):
    """Build a claim/adopt listing URL with optional in-page posting state."""
    route_name = _public_listing_route_name(listing_mode)
    query = {}
    normalized_type = _normalize_user_post_type(selected_type)
    if open_post_panel:
        query["post_dog"] = "1"
    if normalized_type:
        query["type"] = normalized_type
    base_url = reverse(route_name)
    return f"{base_url}?{urlencode(query)}" if query else base_url


def _render_public_post_listing_page(request, listing_mode):
    """Render the shared public listing page and optional in-page dog posting flow."""
    selected_type = _normalize_user_post_type(
        request.POST.get("post_type") if request.method == "POST" else request.GET.get("type")
    )
    show_post_panel = bool(selected_type) or request.GET.get("post_dog") == "1"
    adoption_form = None
    missing_form = None

    if request.method == "POST" and request.POST.get("finder_create_post") == "1":
        show_post_panel = True
        if not request.user.is_authenticated:
            messages.error(request, "Please log in to create a post.")
            return redirect(
                _build_home_auth_modal_url(
                    request,
                    "login",
                    _build_public_listing_url(
                        listing_mode,
                        open_post_panel=True,
                        selected_type=selected_type,
                    ),
                )
            )

        if not selected_type:
            adoption_form = _build_user_adoption_post_form()
            missing_form = _build_missing_dog_post_form()
            messages.error(request, "Choose whether this post is for adoption or for a missing dog.")
        else:
            created, adoption_form, missing_form = _handle_user_post_creation_submission(
                request,
                selected_type,
            )
            if created:
                return redirect(_build_public_listing_url(listing_mode))
    elif request.user.is_authenticated:
        adoption_form = _build_user_adoption_post_form()
        missing_form = _build_missing_dog_post_form()

    listing_context, finder_highlight_redirect = _build_public_post_listing(request, listing_mode)
    if finder_highlight_redirect:
        return redirect(finder_highlight_redirect)
    context = listing_context
    context.update({
        "selected_type": selected_type,
        "adoption_form": adoption_form,
        "missing_form": missing_form,
        "show_post_panel": request.user.is_authenticated and show_post_panel,
        "finder_post_entry_url": _build_public_listing_url(
            listing_mode,
            open_post_panel=True,
            selected_type=selected_type,
        ),
        "finder_post_adoption_url": _build_public_listing_url(
            listing_mode,
            open_post_panel=True,
            selected_type="adoption",
        ),
        "finder_post_missing_url": _build_public_listing_url(
            listing_mode,
            open_post_panel=True,
            selected_type="missing",
        ),
    })
    context.update(_finder_highlight_open_graph(request))
    return render(request, "adopt/adopt_list.html", context)


def _get_available_appointment_dates():
    return GlobalAppointmentDate.objects.filter(
        is_active=True,
        appointment_date__gte=timezone.localdate(),
    ).order_by("appointment_date")


def _confirm_return_to(request):
    return ((request.GET.get("return_to") or request.POST.get("return_to") or "").strip().lower())


def _render_confirm_page(request, template_name, post, available_dates, request_type=None):
    """Render a reusable confirmation page for claim/adoption requests."""
    return_to = _confirm_return_to(request)
    cancel_url = (
        reverse("user:user_home")
        if return_to == "home"
        else reverse(_public_listing_route_name(request_type)) if request_type else reverse("user:user_home")
    )
    status_url = reverse(_request_history_route_name(request_type)) if request_type else reverse("user:user_home")
    return render(request, template_name, {
        "post": post,
        "available_dates": available_dates,
        "cancel_url": cancel_url,
        "status_url": status_url,
        "return_to": return_to if return_to == "home" else "",
    })


def _request_history_route_name(request_type):
    return "user:my_redemptions" if request_type == "claim" else "user:adopt_status"


def _public_listing_route_name(request_type):
    return "user:redeem_list" if request_type == "claim" else "user:adopt_list"


def _request_status_summary(items):
    return {
        "total": len(items),
        "pending": sum(1 for item in items if item.status == "pending"),
        "accepted": sum(1 for item in items if item.status == "accepted"),
        "rejected": sum(1 for item in items if item.status == "rejected"),
    }


def _request_status_summary_from_qs(queryset, accepted_status="accepted", rejected_status="rejected"):
    return queryset.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status="pending")),
        accepted=Count("id", filter=Q(status=accepted_status)),
        rejected=Count("id", filter=Q(status=rejected_status)),
    )


def _user_post_submission_review_bucket(status):
    """Map user adoption / missing post status to summary buckets (admin review)."""
    if status == "pending_review":
        return "pending"
    if status == "declined":
        return "rejected"
    return "accepted"


def _collect_user_post_submissions(user):
    """Rows for posts the user created that go through staff approval (adopt + missing)."""
    entries = []
    profile_url = reverse("user:edit_profile")
    adoption_qs = (
        UserAdoptionPost.objects.filter(owner=user)
        .only("id", "dog_name", "location", "status", "created_at")
        .order_by("-created_at")
    )
    for post in adoption_qs:
        bucket = _user_post_submission_review_bucket(post.status)
        entries.append({
            "kind": "adoption",
            "kind_label": "Adoption post",
            "title": post.dog_name,
            "location": post.location or "",
            "status": post.status,
            "status_label": post.get_status_display(),
            "bucket": bucket,
            "created_at": post.created_at,
            "detail_url": reverse("user:user_adoption_post_detail", args=[post.id]),
        })
    missing_qs = (
        MissingDogPost.objects.filter(owner=user)
        .only("id", "dog_name", "location", "status", "created_at")
        .order_by("-created_at")
    )
    for post in missing_qs:
        bucket = _user_post_submission_review_bucket(post.status)
        entries.append({
            "kind": "missing",
            "kind_label": "Missing dog post",
            "title": post.dog_name,
            "location": post.location or "",
            "status": post.status,
            "status_label": post.get_status_display(),
            "bucket": bucket,
            "created_at": post.created_at,
            "detail_url": f"{profile_url}#profile-post-missing-{post.id}",
        })
    entries.sort(key=lambda row: row["created_at"], reverse=True)
    return entries


def _user_post_submissions_summary(entries):
    return {
        "total": len(entries),
        "pending": sum(1 for row in entries if row["bucket"] == "pending"),
        "accepted": sum(1 for row in entries if row["bucket"] == "accepted"),
        "rejected": sum(1 for row in entries if row["bucket"] == "rejected"),
    }


def _create_post_request_with_images(request, post, request_type, appointment_date):
    valid_id = request.FILES.get("valid_id")

    req = PostRequest.objects.create(
        user=request.user,
        post=post,
        request_type=request_type,
        status="pending",
        appointment_date=appointment_date,
        valid_id=valid_id or None,
    )
    for img in request.FILES.getlist("images"):
        ClaimImage.objects.create(claim=req, image=img)
    return req


def _resolve_request_message(message_or_callable, post):
    return message_or_callable(post) if callable(message_or_callable) else message_or_callable


def _handle_confirm_request(
    request,
    post_id,
    request_type,
    template_name,
    is_open_fn,
    not_open_message,
    duplicate_message,
    success_message,
):
    """Handle request confirmation flows for claim and adoption actions."""
    post = get_object_or_404(
        Post.with_pending_request_state(
            Post.objects.filter(is_history=False)
            .select_related("user", "user__profile")
            .prefetch_related(
                Prefetch(
                    "images",
                    queryset=PostImage.objects.only("id", "post_id", "image").order_by("id"),
                )
            )
        ),
        id=post_id,
    )
    not_open_message = _resolve_request_message(not_open_message, post)
    duplicate_message = _resolve_request_message(duplicate_message, post)
    success_message = _resolve_request_message(success_message, post)
    available_dates = _get_available_appointment_dates()
    history_url = _request_history_route_name(request_type)
    listing_url = _public_listing_route_name(request_type)

    if post.status in ["reunited", "adopted"]:
        messages.warning(request, "This dog is no longer available.")
        return redirect(listing_url)

    if not is_open_fn(post):
        messages.warning(request, not_open_message)
        return redirect(listing_url)

    other_type = "adopt" if request_type == "claim" else "claim"
    if PostRequest.objects.filter(
        user=request.user,
        post=post,
        request_type=other_type,
    ).exists():
        if request_type == "claim":
            messages.warning(
                request,
                "You already reserved adoption for this dog. You cannot submit a redemption request for the same post.",
            )
            return redirect(reverse("user:my_redemptions"))
        messages.warning(
            request,
            "You already submitted a redemption for this dog. You cannot submit an adoption request for the same post.",
        )
        return redirect(reverse("user:adopt_status"))

    if PostRequest.objects.filter(
        user=request.user,
        post=post,
        request_type=request_type,
    ).exists():
        messages.info(request, duplicate_message)
        return redirect(history_url)

    if request.method == "POST":
        appointment_date_raw = request.POST.get("appointment_date")
        appointment_date = parse_date(appointment_date_raw) if appointment_date_raw else None

        if not appointment_date:
            messages.error(request, "Please select an appointment date.")
            return _render_confirm_page(request, template_name, post, available_dates, request_type)

        if not available_dates.filter(appointment_date=appointment_date).exists():
            messages.error(request, "Selected appointment date is not available.")
            return _render_confirm_page(request, template_name, post, available_dates, request_type)

        _create_post_request_with_images(request, post, request_type, appointment_date)
        cache.delete(ADMIN_POST_HISTORY_CACHE_KEY)
        bump_user_home_feed_namespace()
        messages.success(request, success_message)
        return redirect(history_url)

    return _render_confirm_page(request, template_name, post, available_dates, request_type)


def _user_post_requests(user, request_type):
    return (
        PostRequest.objects.filter(
            user=user,
            request_type=request_type,
        )
        .select_related("post", "post__user", "post__user__profile")
        .prefetch_related(
            Prefetch(
                "post__images",
                queryset=PostImage.objects.only("id", "post_id", "image").order_by("id"),
            ),
            Prefetch(
                "images",
                queryset=ClaimImage.objects.only("id", "claim_id", "image").order_by("id"),
            ),
        )
        .order_by("-created_at")
    )


FEED_CACHE_TTL_SECONDS = 90
FEED_CACHE_VERSION = "v6"
FEED_POSTS_PER_PAGE = 12
FEED_ADMIN_CANDIDATE_LIMIT = 700
FEED_ANNOUNCEMENT_CANDIDATE_LIMIT = 300
FEED_USER_CANDIDATE_LIMIT = 400
FEED_MISSING_CANDIDATE_LIMIT = 300
# Keep full candidate windows so pagination can continue for larger feeds.
FEED_ADMIN_SAMPLE_LIMIT = FEED_ADMIN_CANDIDATE_LIMIT
FEED_ANNOUNCEMENT_SAMPLE_LIMIT = FEED_ANNOUNCEMENT_CANDIDATE_LIMIT
FEED_USER_SAMPLE_LIMIT = FEED_USER_CANDIDATE_LIMIT
FEED_MISSING_SAMPLE_LIMIT = FEED_MISSING_CANDIDATE_LIMIT
SEARCH_RESULTS_PER_PAGE = 12
SEARCH_CANDIDATE_LIMIT = 240
ADOPTION_HISTORY_PER_PAGE = 12
SEARCH_CACHE_TTL_SECONDS = 90
SEARCH_MAX_QUERY_LENGTH = 80
PUBLIC_ANNOUNCEMENT_PAGE_SIZE = 12
PUBLIC_ANNOUNCEMENT_SIDEBAR_LIMIT = 6


def _normalized_feed_query(raw_query):
    return " ".join((raw_query or "").strip().split())


def _normalized_search_query(raw_query):
    return _normalized_feed_query(raw_query)[:SEARCH_MAX_QUERY_LENGTH]


def _parse_positive_int(raw_value, default, max_value):
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, max_value))


def _pagination_query_without_page(querydict):
    params = querydict.copy()
    params.pop("page", None)
    return params.urlencode()


def _build_pagination_tokens(page_obj, *, edge_count=1, sibling_count=1):
    """Return a compact page sequence with ellipsis markers."""
    if not page_obj:
        return []

    total_pages = page_obj.paginator.num_pages
    if total_pages <= 1:
        return []

    current_page = page_obj.number
    pages = set()

    for page_number in range(1, min(total_pages, edge_count) + 1):
        pages.add(page_number)
    for page_number in range(max(1, total_pages - edge_count + 1), total_pages + 1):
        pages.add(page_number)
    for page_number in range(
        max(1, current_page - sibling_count),
        min(total_pages, current_page + sibling_count) + 1,
    ):
        pages.add(page_number)

    tokens = []
    previous_page = None
    for page_number in sorted(pages):
        if previous_page is not None and page_number - previous_page > 1:
            tokens.append({
                "type": "ellipsis",
                "key": f"ellipsis-{previous_page}-{page_number}",
            })
        tokens.append({
            "type": "page",
            "number": page_number,
            "is_current": page_number == current_page,
        })
        previous_page = page_number
    return tokens


def _feed_cache_key(prefix, query, feed_token="", viewer_id=None):
    namespace = get_user_home_feed_namespace()
    query_hash = hashlib.md5(query.encode("utf-8")).hexdigest() if query else "all"
    token_hash = hashlib.md5(feed_token.encode("utf-8")).hexdigest() if feed_token else "default"
    viewer_key = str(viewer_id) if viewer_id else "anon"
    return f"user_home:{prefix}:{FEED_CACHE_VERSION}:{namespace}:{query_hash}:{token_hash}:{viewer_key}"


def _normalized_feed_token(raw_token):
    return (raw_token or "").strip()[:64]


def _fresh_feed_token():
    return secrets.token_hex(8)


def _resolve_home_feed_token(request, raw_token=""):
    explicit_token = _normalized_feed_token(raw_token)
    session_token = _normalized_feed_token(
        request.session.get(HOME_FEED_SESSION_TOKEN_KEY)
    )
    if explicit_token:
        if explicit_token != session_token:
            request.session[HOME_FEED_SESSION_TOKEN_KEY] = explicit_token
        return explicit_token
    if session_token:
        return session_token
    generated_token = _fresh_feed_token()
    request.session[HOME_FEED_SESSION_TOKEN_KEY] = generated_token
    return generated_token


def _redirect_to_user_home_with_fresh_feed():
    return redirect(f"{reverse('user:user_home')}?feed_token={_fresh_feed_token()}")


def _feed_rng(seed_key):
    seed_hash = hashlib.md5(seed_key.encode("utf-8")).hexdigest()
    return random.Random(int(seed_hash, 16))


def _sample_recent_ids_with_cache(cache_key, base_qs, candidate_limit, sample_limit):
    cached_ids = cache.get(cache_key)
    if cached_ids is not None:
        return cached_ids

    candidate_ids = list(
        base_qs.order_by("-created_at").values_list("id", flat=True)[:candidate_limit]
    )
    rng = _feed_rng(cache_key)
    if len(candidate_ids) > sample_limit:
        sampled_ids = rng.sample(candidate_ids, sample_limit)
    else:
        sampled_ids = list(candidate_ids)

    rng.shuffle(sampled_ids)
    cache.set(cache_key, sampled_ids, FEED_CACHE_TTL_SECONDS)
    return sampled_ids


def _sample_ids_with_cache(cache_key, candidate_ids, sample_limit):
    cached_ids = cache.get(cache_key)
    if cached_ids is not None:
        return cached_ids

    rng = _feed_rng(cache_key)
    if len(candidate_ids) > sample_limit:
        sampled_ids = rng.sample(candidate_ids, sample_limit)
    else:
        sampled_ids = list(candidate_ids)

    rng.shuffle(sampled_ids)
    cache.set(cache_key, sampled_ids, FEED_CACHE_TTL_SECONDS)
    return sampled_ids


def _active_admin_posts_queryset(query=""):
    accepted_post_requests = PostRequest.objects.filter(
        post_id=OuterRef("pk"),
        status="accepted",
        request_type__in=["claim", "adopt"],
    )
    admin_qs = Post.with_pending_request_state(
        Post.objects.filter(is_history=False).exclude(status__in=["reunited", "adopted"])
        .annotate(
            has_accepted_request=Exists(accepted_post_requests),
        )
    ).filter(has_accepted_request=False)
    if query:
        admin_qs = admin_qs.filter(
            Q(user__username__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(caption__icontains=query)
            | Q(location__icontains=query)
            | Q(status__icontains=query)
        )
    return admin_qs.order_by("-created_at", "-id")


def _active_admin_posts(query="", candidate_limit=None):
    admin_qs = _active_admin_posts_queryset(query)
    if candidate_limit is not None:
        admin_qs = admin_qs[:candidate_limit]
    posts = list(admin_qs)
    Post.attach_active_appointment_dates(posts)
    return [
        post
        for post in posts
        if post.current_phase() in {"claim", "adopt"}
    ]


def _active_admin_candidate_ids_with_cache(query):
    cache_key = _feed_cache_key("active_admin_candidate_ids", query)
    cached_ids = cache.get(cache_key)
    if cached_ids is not None:
        return cached_ids

    active_ids = [
        post.id
        for post in _active_admin_posts(
            query,
            candidate_limit=FEED_ADMIN_CANDIDATE_LIMIT,
        )
    ]
    cache.set(cache_key, active_ids, FEED_CACHE_TTL_SECONDS)
    return active_ids


def _build_random_home_rows(query, feed_token="", dogs_only=False, viewer_id=None):
    feed_scope = "dogs_only" if dogs_only else "mixed"
    mixed_cache_key = _feed_cache_key(
        f"{feed_scope}_rows",
        query,
        feed_token,
        viewer_id=viewer_id,
    )
    cached_rows = cache.get(mixed_cache_key)
    if cached_rows is not None:
        return cached_rows

    active_admin_candidate_ids = _active_admin_candidate_ids_with_cache(query)
    announcement_qs = DogAnnouncement.objects.all()
    user_qs = UserAdoptionPost.objects.filter(status="available")
    missing_qs = MissingDogPost.objects.filter(status="missing")
    if viewer_id:
        user_qs = user_qs.exclude(owner_id=viewer_id)
        missing_qs = missing_qs.exclude(owner_id=viewer_id)

    if query:
        announcement_qs = announcement_qs.filter(
            Q(title__icontains=query)
            | Q(content__icontains=query)
            | Q(category__icontains=query)
        )
        user_qs = user_qs.filter(
            Q(dog_name__icontains=query)
            | Q(description__icontains=query)
            | Q(location__icontains=query)
            | Q(breed__icontains=query)
            | Q(breed_other__icontains=query)
            | Q(age_group__icontains=query)
            | Q(size_group__icontains=query)
            | Q(gender__icontains=query)
            | Q(coat_length__icontains=query)
            | Q(color_other__icontains=query)
        )
        missing_qs = missing_qs.filter(
            Q(dog_name__icontains=query)
            | Q(description__icontains=query)
            | Q(location__icontains=query)
        )

    admin_ids = _sample_ids_with_cache(
        _feed_cache_key(f"{feed_scope}_admin_ids", query, viewer_id=viewer_id),
        active_admin_candidate_ids,
        sample_limit=FEED_ADMIN_SAMPLE_LIMIT,
    )
    announcement_ids = []
    if not dogs_only:
        announcement_ids = _sample_recent_ids_with_cache(
            _feed_cache_key(f"{feed_scope}_announcement_ids", query, viewer_id=viewer_id),
            announcement_qs,
            candidate_limit=FEED_ANNOUNCEMENT_CANDIDATE_LIMIT,
            sample_limit=FEED_ANNOUNCEMENT_SAMPLE_LIMIT,
        )
    user_ids = _sample_recent_ids_with_cache(
        _feed_cache_key(f"{feed_scope}_user_ids", query, viewer_id=viewer_id),
        user_qs,
        candidate_limit=FEED_USER_CANDIDATE_LIMIT,
        sample_limit=FEED_USER_SAMPLE_LIMIT,
    )
    missing_ids = _sample_recent_ids_with_cache(
        _feed_cache_key(f"{feed_scope}_missing_ids", query, viewer_id=viewer_id),
        missing_qs,
        candidate_limit=FEED_MISSING_CANDIDATE_LIMIT,
        sample_limit=FEED_MISSING_SAMPLE_LIMIT,
    )

    mixed_rows = [{"id": post_id, "feed_type": "admin"} for post_id in admin_ids]
    mixed_rows.extend({"id": ann_id, "feed_type": "announcement"} for ann_id in announcement_ids)
    mixed_rows.extend({"id": user_id, "feed_type": "user"} for user_id in user_ids)
    mixed_rows.extend({"id": missing_id, "feed_type": "missing"} for missing_id in missing_ids)
    # Seeded shuffling keeps pagination stable for one browsing session without DB-level random ordering.
    _feed_rng(mixed_cache_key).shuffle(mixed_rows)
    cache.set(mixed_cache_key, mixed_rows, FEED_CACHE_TTL_SECONDS)
    return mixed_rows


def _build_search_rows_cache_key(query, dogs_only, viewer_id=None):
    prefix = "search_dogs_only" if dogs_only else "search_mixed"
    return _feed_cache_key(f"{prefix}:keyword_only", query, viewer_id=viewer_id)


def _build_search_home_rows(query, dogs_only=False, viewer_id=None):
    has_filters = bool(query)
    if not has_filters:
        return []

    cache_key = _build_search_rows_cache_key(query, dogs_only, viewer_id=viewer_id)
    cached_rows = cache.get(cache_key)
    if cached_rows is not None:
        return cached_rows

    admin_posts = _active_admin_posts(
        query,
        candidate_limit=SEARCH_CANDIDATE_LIMIT,
    )
    announcement_qs = DogAnnouncement.objects.all()
    user_qs = UserAdoptionPost.objects.filter(status="available")
    missing_qs = MissingDogPost.objects.filter(status="missing")
    if viewer_id:
        user_qs = user_qs.exclude(owner_id=viewer_id)
        missing_qs = missing_qs.exclude(owner_id=viewer_id)

    if query:
        announcement_filters = (
            Q(title__icontains=query)
            | Q(content__icontains=query)
            | Q(category__icontains=query)
            | Q(created_by__username__icontains=query)
            | Q(created_by__first_name__icontains=query)
            | Q(created_by__last_name__icontains=query)
        )
        user_filters = (
            Q(dog_name__icontains=query)
            | Q(description__icontains=query)
            | Q(location__icontains=query)
            | Q(breed__icontains=query)
            | Q(breed_other__icontains=query)
            | Q(age_group__icontains=query)
            | Q(size_group__icontains=query)
            | Q(gender__icontains=query)
            | Q(coat_length__icontains=query)
            | Q(color_other__icontains=query)
            | Q(owner__username__icontains=query)
            | Q(owner__first_name__icontains=query)
            | Q(owner__last_name__icontains=query)
        )
        missing_filters = (
            Q(dog_name__icontains=query)
            | Q(description__icontains=query)
            | Q(location__icontains=query)
            | Q(owner__username__icontains=query)
            | Q(owner__first_name__icontains=query)
            | Q(owner__last_name__icontains=query)
        )

        announcement_qs = announcement_qs.filter(announcement_filters)
        user_qs = user_qs.filter(user_filters)
        missing_qs = missing_qs.filter(missing_filters)

    admin_rows = [
        {"id": post.id, "created_at": post.created_at}
        for post in admin_posts
    ]
    announcement_rows = []
    if not dogs_only:
        announcement_rows = list(
            announcement_qs.order_by("-created_at").values("id", "created_at")[:SEARCH_CANDIDATE_LIMIT]
        )
    user_rows = list(
        user_qs.order_by("-created_at").values("id", "created_at")[:SEARCH_CANDIDATE_LIMIT]
    )
    missing_rows = list(
        missing_qs.order_by("-created_at").values("id", "created_at")[:SEARCH_CANDIDATE_LIMIT]
    )

    rows = [{"id": row["id"], "feed_type": "admin", "created_at": row["created_at"]} for row in admin_rows]
    rows.extend(
        {"id": row["id"], "feed_type": "announcement", "created_at": row["created_at"]}
        for row in announcement_rows
    )
    rows.extend(
        {"id": row["id"], "feed_type": "user", "created_at": row["created_at"]}
        for row in user_rows
    )
    rows.extend(
        {"id": row["id"], "feed_type": "missing", "created_at": row["created_at"]}
        for row in missing_rows
    )
    rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
    cache.set(cache_key, rows, SEARCH_CACHE_TTL_SECONDS)
    return rows


def _hydrate_home_feed_items(request, feed_rows, *, appointment_dates=None):
    if not feed_rows:
        return []

    ids_by_type = {
        "admin": [row["id"] for row in feed_rows if row["feed_type"] == "admin"],
        "announcement": [row["id"] for row in feed_rows if row["feed_type"] == "announcement"],
        "user": [row["id"] for row in feed_rows if row["feed_type"] == "user"],
        "missing": [row["id"] for row in feed_rows if row["feed_type"] == "missing"],
    }

    user_request_counts = {}
    if ids_by_type["user"]:
        user_request_counts = dict(
            UserAdoptionRequest.objects.filter(post_id__in=ids_by_type["user"])
            .values("post_id")
            .annotate(total=Count("id"))
            .values_list("post_id", "total")
        )

    admin_map = {
        post.id: post
        for post in Post.with_pending_request_state(
            Post.objects.select_related(
                "user", "user__profile"
            ).only(
                "id", "caption", "breed", "breed_other", "age_group", "size_group", "gender",
                "coat_length", "colors", "color_other", "location", "status", "rescued_date",
                "created_at", "claim_days",
                "user__id", "user__username", "user__first_name", "user__last_name",
                "user__profile__profile_image",
            )
        ).prefetch_related(
            Prefetch(
                "images",
                queryset=PostImage.objects.only("id", "post_id", "image").order_by("id"),
                to_attr="prefetched_images",
            )
        ).filter(id__in=ids_by_type["admin"])
    }
    announcement_map = {
        post.id: post
        for post in DogAnnouncement.objects.select_related(
            "created_by", "created_by__profile"
        ).only(
            "id", "title", "content", "category", "created_at", "background_image",
            "created_by__id", "created_by__username", "created_by__first_name",
            "created_by__last_name", "created_by__profile__profile_image",
        ).prefetch_related(
            Prefetch(
                "images",
                queryset=DogAnnouncementImage.objects.only("id", "announcement_id", "image").order_by("id"),
                to_attr="prefetched_images",
            )
        ).filter(id__in=ids_by_type["announcement"])
    }
    user_map = {
        post.id: post
        for post in UserAdoptionPost.objects.select_related(
            "owner", "owner__profile"
        ).only(
            "id",
            "dog_name",
            "breed",
            "breed_other",
            "age_group",
            "size_group",
            "gender",
            "coat_length",
            "colors",
            "color_other",
            "age",
            "description",
            "location",
            "status",
            "created_at",
            "owner__id",
            "owner__username",
            "owner__first_name",
            "owner__last_name",
            "owner__profile__profile_image",
        ).prefetch_related(
            Prefetch(
                "images",
                queryset=UserAdoptionImage.objects.only("id", "post_id", "image").order_by("id"),
                to_attr="prefetched_images",
            )
        ).filter(id__in=ids_by_type["user"])
    }
    missing_map = {
        post.id: post
        for post in MissingDogPost.objects.select_related(
            "owner", "owner__profile"
        ).only(
            "id",
            "owner_id",
            "dog_name",
            "age",
            "description",
            "image",
            "date_lost",
            "time_lost",
            "location",
            "contact_phone_number",
            "contact_facebook_url",
            "status",
            "created_at",
            "owner__id",
            "owner__username",
            "owner__first_name",
            "owner__last_name",
            "owner__profile__profile_image",
        ).filter(id__in=ids_by_type["missing"])
    }

    if admin_map:
        Post.attach_active_appointment_dates(admin_map.values(), appointment_dates)
    viewer_staff_request_map = _viewer_staff_post_request_map(
        request.user, ids_by_type["admin"]
    )
    viewer_user_adoption_post_ids = set()
    if getattr(request.user, "is_authenticated", False) and ids_by_type["user"]:
        viewer_user_adoption_post_ids = set(
            UserAdoptionRequest.objects.filter(
                requester=request.user, post_id__in=ids_by_type["user"]
            ).values_list("post_id", flat=True)
        )

    combined_posts = []
    default_admin_avatar_url = static("images/officialseal.webp")
    default_profile_avatar_url = static("images/default-user-image.jpg")
    current_url_name = getattr(getattr(request, "resolver_match", None), "url_name", "")
    profile_back_label = "Back to Search" if current_url_name == "home_search" else "Back to Feed"
    profile_return_url = request.get_full_path()
    for row in feed_rows:
        post_type = row["feed_type"]
        post_id = row["id"]

        if post_type == "admin":
            p = admin_map.get(post_id)
            if not p:
                continue
            gallery_images = list(getattr(p, "prefetched_images", []))
            main_image = gallery_images[0] if gallery_images else None

            phase_payload = _post_phase_payload(p)
            phase = phase_payload["phase"]
            if _is_post_time_expired(p, phase_payload):
                continue
            is_open_for_adoption = phase in ["claim", "adopt"]

            deadline = None
            if phase == "claim":
                deadline = p.claim_deadline()
            elif phase == "adopt":
                deadline = p.adoption_deadline()

            vf = viewer_staff_request_map.get(
                p.id, {"claim": False, "adopt": False}
            )
            cta = _staff_post_public_cta_flags(phase, request.user, vf)

            combined_posts.append({
                "post": p,
                "post_type": "admin",
                "author_avatar_url": _profile_image_url_or_default(
                    p.user, default_admin_avatar_url
                ),
                "days_left": phase_payload["days_left"],
                "hours_left": phase_payload["hours_left"],
                "minutes_left": phase_payload["minutes_left"],
                "is_open_for_adoption": is_open_for_adoption,
                "phase": phase,
                "is_pending_review": phase_payload["is_pending_review"],
                "show_countdown": phase in {"claim", "adopt"} and bool(deadline),
                "pending_review_until": phase_payload["pending_review_until"],
                "pending_review_until_label": phase_payload["pending_review_until_label"],
                "pending_state_label": "",
                "pending_state_detail": "",
                "posted_label": _format_posted_label(p.created_at),
                "deadline_iso": deadline.isoformat() if deadline else "",
                "image_count": len(gallery_images),
                "gallery_images": gallery_images,
                "main_image": main_image,
                "share_url": _finder_share_url_staff(request, p, phase_payload),
                "viewer_has_claim_request": vf["claim"],
                "viewer_has_adopt_request": vf["adopt"],
                **cta,
            })
            continue

        if post_type == "announcement":
            p = announcement_map.get(post_id)
            if not p:
                continue
            announcement_images = list(getattr(p, "prefetched_images", []))
            first_image_url = _first_prefetched_image_url(announcement_images)
            main_image_url = first_image_url or _safe_media_url(p.background_image)

            combined_posts.append({
                "post": p,
                "post_type": "announcement",
                "author_avatar_url": _profile_image_url_or_default(
                    p.created_by, default_admin_avatar_url
                ),
                "content_display": _clean_announcement_text_for_display(p.content),
                "posted_label": _format_posted_label(p.created_at),
                "main_image_url": main_image_url,
                "image_count": len(announcement_images),
                "gallery_images": announcement_images,
                "has_media": bool(p.background_image or announcement_images),
                "share_url": _announcement_feed_share_url(request, p.id),
            })
            continue

        if post_type == "user":
            p = user_map.get(post_id)
            if not p:
                continue
            post_images = list(getattr(p, "prefetched_images", []))
            main_image = post_images[0] if post_images else None
            profile_url = _build_profile_destination_url(
                request,
                p.owner_id,
                next_url=profile_return_url,
                back_label=profile_back_label,
            )

            has_user_adoption_request = p.id in viewer_user_adoption_post_ids
            show_user_adoption_request_cta = (
                not getattr(request.user, "is_authenticated", False)
                or not has_user_adoption_request
            )

            combined_posts.append({
                "post": p,
                "post_type": "user",
                "days_left": 0,
                "hours_left": 0,
                "minutes_left": 0,
                "is_open_for_adoption": False,
                "phase": "closed",
                "posted_label": _format_posted_label(p.created_at),
                "image_count": len(post_images),
                "gallery_images": post_images,
                "main_image": main_image,
                "request_count": int(user_request_counts.get(p.id, 0)),
                "author_name": p.owner.get_full_name() or p.owner.username,
                "author_avatar_url": _profile_image_url_or_default(
                    p.owner,
                    default_profile_avatar_url,
                ),
                "author_profile_url": profile_url,
                "owner_request_url": f"{reverse('user:edit_profile')}#post-requests-{p.id}",
                "share_url": _finder_share_url_user_adoption(request, p.id),
                "viewer_has_user_adoption_request": has_user_adoption_request,
                "show_user_adoption_request_cta": show_user_adoption_request_cta,
                "post_id": p.id,
                "dog_name": p.dog_name,
                "breed_label": p.display_breed or "Unknown Breed",
                "age_label": p.display_age_group or "Age not listed",
                "size_label": p.display_size_group or "Size not listed",
                "gender_label": p.get_gender_display() if p.gender else "Gender not listed",
                "coat_label": p.display_coat_length or "Coat not listed",
                "color_label": p.display_colors or "Color not listed",
                "location_label": " ".join((p.location or "").split()) or "Location not listed",
                "main_image_url": _first_prefetched_image_url(post_images),
                "is_vaccinated": p.is_vaccinated,
                "is_registered": p.is_registered,
            })
            continue

        p = missing_map.get(post_id)
        if not p:
            continue
        profile_url = _build_profile_destination_url(
            request,
            p.owner_id,
            next_url=profile_return_url,
            back_label=profile_back_label,
        )
        combined_posts.append({
            "post": p,
            "post_type": "missing",
            "days_left": 0,
            "hours_left": 0,
            "minutes_left": 0,
            "is_open_for_adoption": False,
            "phase": "closed",
            "posted_label": _format_posted_label(p.created_at),
            "image_count": 1 if p.image else 0,
            "main_image": None,
            "author_name": p.owner.get_full_name() or p.owner.username,
            "author_avatar_url": _profile_image_url_or_default(
                p.owner,
                default_profile_avatar_url,
            ),
            "author_profile_url": profile_url,
            "share_url": _missing_dog_public_share_url(request, p.id),
        })

    return combined_posts


def _is_valid_capture_reason(reason):
    return reason in DogCaptureRequest.REASON_LABELS


def _group_capture_requests_by_status(requests):
    return {
        "accepted_requests": [req for req in requests if req.status == "accepted"],
        "pending_requests": [req for req in requests if req.status == "pending"],
        "captured_requests": [req for req in requests if req.status == "captured"],
        "declined_requests": [req for req in requests if req.status == "declined"],
    }


# Shared onboarding and profile endpoints
def barangay_list_api(request):
    """Return active barangay names for signup and request autocomplete."""
    query = " ".join((request.GET.get("q") or "").split()).strip()
    limit = _parse_positive_int(
        request.GET.get("limit"),
        BARANGAY_API_DEFAULT_LIMIT,
        BARANGAY_API_MAX_LIMIT,
    )
    barangay_qs = Barangay.objects.filter(is_active=True)
    if query:
        barangay_qs = barangay_qs.filter(name__icontains=query)
    barangays = list(barangay_qs.values_list("name", flat=True)[:limit])
    response = JsonResponse({"barangays": barangays})
    response["Cache-Control"] = "private, max-age=300"
    return response


def signup_view(request):
    """Create a public account manually, or finish a Google sign-in immediately."""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect(get_staff_landing_url(request.user))
        return redirect("user:user_home")

    next_url = _get_safe_next_url(
        request,
        request.POST.get("next") if request.method == "POST" else request.GET.get("next"),
    )

    if request.method == "POST":
        google_credential = (request.POST.get("google_credential") or request.POST.get("credential") or "").strip()
        if google_credential:
            signup_form_data = _build_signup_form_data(
                username=_normalize_signup_username(request.POST.get("username")),
                first_name=(request.POST.get("first_name") or "").strip(),
                last_name=(request.POST.get("last_name") or "").strip(),
                raw_barangay=request.POST.get("address"),
            )
            try:
                social_signup_data = _verify_google_signup_credential(google_credential)
            except ValidationError as exc:
                return _render_signup_error(request, signup_form_data, " ".join(exc.messages))
            return _complete_google_login(request, social_signup_data, next_url=next_url)

        _clear_signup_session_state(request, delete_temp_faces=True)
        _clear_social_signup_session(request)

        username = _normalize_signup_username(request.POST.get("username"))
        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        raw_barangay = request.POST.get("address")
        barangay = _resolve_barangay_name(request.POST.get("address"))
        signup_form_data = _build_signup_form_data(
            username=username,
            first_name=first_name,
            last_name=last_name,
            raw_barangay=raw_barangay,
        )

        try:
            _validate_signup_username(username)
        except ValidationError as exc:
            return _render_signup_error(request, signup_form_data, " ".join(exc.messages))

        if password != confirm_password:
            return _render_signup_error(request, signup_form_data, "Passwords do not match.")

        try:
            temp_user = User(
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            validate_password(password, user=temp_user)
        except ValidationError as exc:
            return _render_signup_error(request, signup_form_data, " ".join(exc.messages))

        if not barangay:
            return _render_signup_error(
                request,
                signup_form_data,
                "Please select a valid barangay from the suggestions.",
            )

        if not first_name or not last_name:
            return _render_signup_error(
                request,
                signup_form_data,
                "First name and last name are required.",
            )

        try:
            user = _create_manual_user_account(
                username=username,
                password=password,
                first_name=first_name,
                last_name=last_name,
                barangay=barangay,
            )
        except IntegrityError:
            return _render_signup_error(
                request,
                signup_form_data,
                "Username already exists. Please choose a different one and sign up again.",
            )

        login(request, user)
        messages.success(request, "Account created. You are now logged in.")
        if next_url:
            response = redirect(next_url)
        else:
            response = redirect("user:user_home")
        response.delete_cookie("admin_sessionid")
        return response

    return _render_signup_page(request, next_url=next_url)


def verify_email(request, uidb64, token):
    """Activate a public user account after the email verification link is opened."""
    next_url = _get_safe_next_url(request, request.GET.get("next"))

    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.select_related("profile").get(pk=user_id, is_staff=False)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        messages.error(request, "This verification link is invalid or has expired.")
        return redirect("user:signup")

    profile, _ = Profile.objects.get_or_create(
        user=user,
        defaults={
            "address": "",
            "age": 18,
            "consent_given": True,
            "email_verified": True,
        },
    )

    fields_to_update = []
    if not profile.email_verified:
        profile.email_verified = True
        fields_to_update.append("email_verified")
    if fields_to_update:
        profile.save(update_fields=fields_to_update)

    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])

    messages.success(request, "Email verified. You can now log in.")
    login_url = reverse("user:login")
    if next_url:
        login_url = f"{login_url}?{urlencode({'next': next_url})}"
    return redirect(login_url)

@user_only
def edit_profile(request):
    """Let the signed-in user update profile details and profile photo."""
    user = request.user
    profile, _ = Profile.objects.get_or_create(
        user=user,
        defaults={"address": "", "age": 18, "consent_given": True}
    )

    if request.method == "POST":
        edit_action = request.POST.get("edit_action", "details")

        if edit_action == "photo":
            if request.FILES.get("profile_image"):
                profile.profile_image = request.FILES["profile_image"]
                profile.save(update_fields=["profile_image"])
                invalidate_cached_profile_avatar(user.id)
                messages.success(request, "Profile photo updated successfully")
            else:
                messages.error(request, "Please choose a profile photo first.")
            return redirect("user:edit_profile")

        user.first_name = request.POST.get("first_name", "").strip()
        user.last_name = request.POST.get("last_name", "").strip()

        profile.address = request.POST.get("address", "").strip()
        profile.age = request.POST.get("age") or profile.age
        profile.phone_number = request.POST.get("phone_number", "").strip()
        profile.facebook_url = request.POST.get("facebook_url", "").strip()

        user.save()
        profile.save()

        messages.success(request, "Profile updated successfully")
        return redirect("user:edit_profile")

    return render(request, "edit_profile.html", _build_profile_dashboard_context(user))


def _render_profile_preview(request, profile_user, *, back_url="", back_label="Back"):
    """Render the shared user profile dashboard in read-only preview mode."""
    context = _build_profile_dashboard_context(profile_user)
    context.update({
        "preview_mode": True,
        "preview_back_url": back_url,
        "preview_back_label": back_label,
    })
    return render(request, "edit_profile.html", context)


@login_required
def admin_view_user_profile(request, user_id):
    """Let staff preview a user profile using the same profile template."""
    if not request.user.is_staff:
        return redirect("user:login")
    profile_user = get_object_or_404(User, pk=user_id, is_staff=False)
    return _render_profile_preview(request, profile_user)


@login_required
def view_user_profile(request, user_id):
    """Render a read-only profile preview for any non-staff user."""
    if request.user.is_staff:
        return redirect("user:admin_view_user_profile", user_id=user_id)
    if request.user.id == user_id:
        return redirect("user:edit_profile")

    profile_user = get_object_or_404(User, pk=user_id, is_staff=False)
    back_url = _safe_preview_back_url(request, request.GET.get("next", ""))
    back_label = (request.GET.get("label") or "Back").strip()[:48] or "Back"
    return _render_profile_preview(
        request,
        profile_user,
        back_url=back_url,
        back_label=back_label,
    )


@user_only
def view_requester_profile(request, user_id):
    """Let a post owner preview a requester profile without edit access."""
    profile_user = get_object_or_404(
        User.objects.filter(
            is_staff=False,
            adoption_requests__post__owner=request.user,
        ).distinct(),
        pk=user_id,
    )
    return _render_profile_preview(
        request,
        profile_user,
        back_url=reverse("user:user_adoption_requests"),
        back_label="Back to Requests",
    )
# =============================================================================
# Navigation 1/5: Home
# Covers the public feed, search, user-created posts, and related post actions.
# =============================================================================

def _build_user_home_context(
    request,
    *,
    selected_type="adoption",
    adoption_form=None,
    missing_form=None,
    open_create_modal=False,
):
    should_render_create_modal = request.user.is_authenticated and not request.user.is_staff
    if should_render_create_modal:
        adoption_form = adoption_form or _build_user_adoption_post_form()
        missing_form = missing_form or _build_missing_dog_post_form()
    else:
        adoption_form = adoption_form or None
        missing_form = missing_form or None
    query = _normalized_feed_query(request.GET.get("q"))
    feed_token = _resolve_home_feed_token(request, request.GET.get("feed_token"))
    page_number = request.GET.get("page", 1)
    # Keep home feed content focused on dog posts. Announcements live on their own page.
    show_dogs_only = True
    mixed_rows = _build_random_home_rows(
        query,
        feed_token=feed_token,
        dogs_only=show_dogs_only,
        viewer_id=getattr(request.user, "id", None),
    )

    paginator = Paginator(mixed_rows, FEED_POSTS_PER_PAGE)
    page_obj = paginator.get_page(page_number)
    feed_rows = list(page_obj.object_list)
    appointment_dates = Post.active_appointment_dates()
    combined_posts = _hydrate_home_feed_items(
        request, feed_rows, appointment_dates=appointment_dates
    )
    pagination_params = request.GET.copy()
    pagination_params["feed_token"] = feed_token
    pagination_params.pop("page", None)

    home_missing_posts = list(
        MissingDogPost.objects
        .filter(status="missing")
        .select_related("owner", "owner__profile")
        .order_by("-created_at")[:10]
    )

    return {
        "posts": combined_posts,
        **_build_home_pinned_rescue_spotlights(
            request, appointment_dates=appointment_dates
        ),
        "featured_dog_sections": _build_home_featured_rescue_sections(
            request, appointment_dates=appointment_dates
        ),
        "home_missing_posts": home_missing_posts,
        "vaccination_reminder_summary": (
            build_user_vaccination_reminder_summary(request.user)
            if request.user.is_authenticated and not request.user.is_staff
            else {"items": [], "expired_count": 0, "due_soon_count": 0, "profile_url": ""}
        ),
        "page_obj": page_obj,
        "query": query,
        "feed_token": feed_token,
        "pagination_query": pagination_params.urlencode(),
        "selected_type": selected_type,
        "adoption_form": adoption_form,
        "missing_form": missing_form,
        "open_create_modal": open_create_modal,
        "search_mode": False,
        "empty_message": "No feed items available yet.",
    }


def _render_home_with_auth_modal(request, auth_modal, **extra_context):
    """Render the home feed while forcing a login or signup modal state."""
    context = _build_user_home_context(request)
    context.update({
        "auth_modal": auth_modal,
        **_auth_ui_context(),
        **extra_context,
    })
    return render(request, "home/user_home.html", context)


def user_home(request):
    """Render the mixed public feed and handle quick post creation from home."""
    # Redirect staff to admin dashboard
    if request.user.is_authenticated and request.user.is_staff:
        return redirect(get_staff_landing_url(request.user))

    if not request.user.is_authenticated and _has_pending_signup_face_progress(request):
        _clear_signup_face_progress(request)

    auth_modal = ""
    auth_next = ""
    if not request.user.is_authenticated:
        auth_modal_candidate = (request.GET.get("auth_modal") or "").strip().lower()
        if auth_modal_candidate in {"login", "signup"}:
            auth_modal = auth_modal_candidate
            auth_next = _get_safe_next_url(request, request.GET.get("next"))

    selected_type = request.GET.get("type", "adoption")
    if request.user.is_authenticated:
        adoption_form = _build_user_adoption_post_form()
        missing_form = _build_missing_dog_post_form()
    else:
        adoption_form = None
        missing_form = None
    open_create_modal = False

    if request.method == "POST" and request.POST.get("home_create_post") == "1":
        if not request.user.is_authenticated:
            messages.error(request, "Please log in to create a post.")
            return redirect("user:login")

        selected_type = request.POST.get("post_type", "adoption")
        open_create_modal = True
        created, adoption_form, missing_form = _handle_user_post_creation_submission(
            request,
            selected_type,
        )
        if created:
            return _redirect_to_user_home_with_fresh_feed()

    context = _build_user_home_context(
        request,
        selected_type=selected_type,
        adoption_form=adoption_form,
        missing_form=missing_form,
        open_create_modal=open_create_modal,
    )
    context.update({
        "auth_modal": auth_modal,
        "auth_next": auth_next,
        **_auth_ui_context(),
    })
    return render(request, "home/user_home.html", context)


def home_search(request):
    """Search the public home feed across staff and user-created posts."""
    if request.user.is_authenticated and request.user.is_staff:
        return redirect(get_staff_landing_url(request.user))

    query = _normalized_search_query(request.GET.get("q"))
    search_performed = bool(query)
    # Search should mirror the home feed and exclude announcement cards.
    show_dogs_only = True
    search_rows = _build_search_home_rows(
        query=query,
        dogs_only=show_dogs_only,
        viewer_id=getattr(request.user, "id", None),
    )

    paginator = Paginator(search_rows, SEARCH_RESULTS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    appointment_dates = Post.active_appointment_dates()
    posts = _hydrate_home_feed_items(
        request, list(page_obj.object_list), appointment_dates=appointment_dates
    )
    result_count = len(search_rows)

    if search_performed:
        empty_message = "No results found. Try another keyword."
    else:
        empty_message = "Enter a keyword to begin searching."

    context = {
        "posts": posts,
        "page_obj": page_obj,
        "pagination_query": _pagination_query_without_page(request.GET),
        "query": query,
        "result_count": result_count,
        "search_performed": search_performed,
        "search_mode": True,
        "empty_message": empty_message,
    }
    return render(request, "home/search_results.html", context)

@user_only
def create_post(request):
    """Render the standalone create-post page for signed-in users."""
    selected_type = request.GET.get("type", "adoption")
    if request.method == "POST":
        selected_type = request.POST.get("post_type", "adoption")

    adoption_form = _build_user_adoption_post_form()
    missing_form = _build_missing_dog_post_form()

    if request.method == "POST":
        created, adoption_form, missing_form = _handle_user_post_creation_submission(
            request,
            selected_type,
        )
        if created:
            return _redirect_to_user_home_with_fresh_feed()

    return render(request, "home/post_create.html", {
        "selected_type": selected_type,
        "adoption_form": adoption_form,
        "missing_form": missing_form,
    })


def user_adoption_post_detail(request, post_id):
    """Render a detail page for a user adoption post with OG meta tags for sharing."""
    post = get_object_or_404(
        UserAdoptionPost.objects.select_related("owner", "owner__profile").prefetch_related(
            Prefetch(
                "images",
                queryset=UserAdoptionImage.objects.only("id", "post_id", "image").order_by("id"),
            )
        ),
        id=post_id,
    )
    first_image = next(iter(post.images.all()), None)
    og_image_url = ""
    if first_image:
        og_image_url = request.build_absolute_uri(first_image.image.url)

    description = (post.description or "").strip()
    if len(description) > 200:
        description = f"{description[:197].rstrip()}..."
    if not description:
        description = f"{post.dog_name} is available for adoption in {post.location or 'Bayawan'}."

    return render(request, "adopt/user_adoption_post_detail.html", {
        "post": post,
        "og_image_url": og_image_url,
        "og_description": description,
        "first_image_url": _first_prefetched_image_url(post.images.all()),
    })


@user_only
def adopt_user_post(request, post_id):
    """Submit an adoption request for a user-created adoption post."""
    post = get_object_or_404(
        UserAdoptionPost.objects.select_related("owner", "owner__profile"),
        id=post_id,
    )
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if post.owner == request.user:
        message = "You cannot request adoption for your own post."
        if is_ajax:
            return JsonResponse({"ok": False, "message": message}, status=400)
        messages.info(request, message)
        return redirect('user:user_home')

    if post.status != "available":
        message = "This dog is no longer available."
        if is_ajax:
            return JsonResponse({"ok": False, "message": message}, status=400)
        messages.warning(request, message)
        return redirect("user:user_home")

    if request.method == "POST":
        valid_id = request.FILES.get("valid_id")

        req, created = UserAdoptionRequest.objects.get_or_create(
            post=post,
            requester=request.user,
            defaults={
                "valid_id": valid_id or None,
            }
        )

        if created:
            invalidate_user_notification_payload(post.owner_id)
            message = "Adoption request submitted successfully."
            if is_ajax:
                return JsonResponse({"ok": True, "created": True, "message": message})
            messages.success(request, message)
        else:
            message = "You already submitted an adoption request for this post."
            if is_ajax:
                return JsonResponse({"ok": True, "created": False, "message": message})
            messages.info(request, message)
        return redirect('user:user_home')

    return render(request, "adopt/adopt_user_confirm.html", {
        "post": post,
    })


@user_only
def user_adoption_requests(request):
    """List requests received on adoption posts owned by the current user."""
    requests_qs = UserAdoptionRequest.objects.filter(
        post__owner=request.user
    ).select_related("post", "requester", "requester__profile").order_by("-created_at")

    page_obj = Paginator(requests_qs, 20).get_page(request.GET.get("page", 1))
    return render(request, "adopt/user_post_requests.html", {
        "requests": page_obj,
        "page_obj": page_obj,
    })


@user_only
def user_adoption_request_action(request, req_id, action):
    """Accept or decline an incoming request on a user-created adoption post."""
    req = get_object_or_404(
        UserAdoptionRequest.objects.select_related("post", "post__owner", "requester", "requester__profile"),
        id=req_id,
        post__owner=request.user
    )

    if action == "accept":
        req.status = "approved"
        req.save(update_fields=["status"])
        UserAdoptionRequest.objects.filter(
            post=req.post
        ).exclude(id=req.id).update(status="rejected")
        req.post.status = "adopted"
        req.post.save(update_fields=["status"])
        bump_user_home_feed_namespace()
        invalidate_user_notification_payload(request.user.id)
        messages.success(request, "Adoption request accepted.")
    elif action == "decline":
        req.status = "rejected"
        req.save(update_fields=["status"])
        invalidate_user_notification_payload(request.user.id)
        messages.info(request, "Adoption request declined.")

    next_url = _safe_preview_back_url(request, request.GET.get("next", ""))
    if next_url:
        return redirect(next_url)
    return redirect("user:user_adoption_requests")


@require_POST
@user_only
def delete_user_adoption_post(request, post_id):
    """Delete one of the current user's adoption posts."""
    post = get_object_or_404(UserAdoptionPost, id=post_id, owner=request.user)
    dog_name = post.dog_name
    post.delete()
    bump_user_home_feed_namespace()
    messages.success(request, f'Adoption post "{dog_name}" deleted.')
    return redirect("user:edit_profile")


@require_POST
@user_only
def delete_missing_dog_post(request, post_id):
    """Delete one of the current user's missing-dog posts."""
    post = get_object_or_404(MissingDogPost, id=post_id, owner=request.user)
    dog_name = post.dog_name
    post.delete()
    bump_user_home_feed_namespace()
    messages.success(request, f'Missing dog post "{dog_name}" deleted.')
    return redirect("user:edit_profile")

def post_detail(request, post_id):
    """Render a post detail page used by shared or linked home posts."""
    post = get_object_or_404(
        Post.with_pending_request_state(
            Post.objects.filter(is_history=False)
            .select_related("user", "user__profile")
            .prefetch_related(
                Prefetch(
                    "images",
                    queryset=PostImage.objects.only("id", "post_id", "image").order_by("id"),
                )
            )
        ),
        id=post_id,
    )
    Post.objects.filter(id=post.id).update(view_count=F("view_count") + 1)
    post.view_count = int(getattr(post, "view_count", 0) or 0) + 1
    phase_payload = _post_phase_payload(post)
    if _is_post_time_expired(post, phase_payload):
        messages.info(request, "This listing is no longer available for public viewing.")
        return redirect("user:user_home")
    card_item = _build_rescue_finder_card_item(request, post, phase_payload, 0)
    back_url = _safe_preview_back_url(request, request.GET.get("next", "")) or reverse("user:user_home")
    back_label = (request.GET.get("label") or "Back to feed").strip()[:48] or "Back to feed"
    summary = " ".join(strip_tags(post.caption or "").split())
    if summary in {"", card_item["title"], card_item["breed_label"]}:
        summary = ""

    og_image_url = ""
    if card_item["main_image_url"]:
        og_image_url = request.build_absolute_uri(card_item["main_image_url"])

    detail = {
        **card_item,
        "theme": phase_payload["phase"] if phase_payload["phase"] in {"claim", "adopt"} else "closed",
        "summary": summary,
        "og_image_url": og_image_url,
        "facts": [
            {"label": "Breed", "value": card_item["breed_label"]},
            {"label": "Location", "value": card_item["location_label"]},
            {"label": "Age", "value": card_item["age_label"]},
            {"label": "Size", "value": card_item["size_label"]},
            {"label": "Gender", "value": card_item["gender_label"]},
            {"label": "Coat", "value": card_item["coat_label"]},
            {"label": "Color", "value": card_item["color_label"]},
            {
                "label": card_item["countdown_date_heading"],
                "value": card_item["countdown_date_label"],
            },
        ],
    }
    return render(request, 'home/post_detail.html', {
        'post': post,
        'detail': detail,
        'back_url': back_url,
        'back_label': back_label,
    })


# =============================================================================
# Navigation 2/5: Request
# Covers dog-capture request submission, editing, and deletion.
# =============================================================================

def request_dog_capture(request):
    """Create and list online dog-surrender requests for the current user."""
    if request.method == 'POST':
        access_response = _require_public_member_or_auth_modal(
            request,
            next_url=reverse("user:dog_capture_request"),
        )
        if access_response is not None:
            return access_response
        submission_response = _handle_dog_capture_request_submission(request)
        if submission_response is not None:
            return submission_response

    return render(
        request,
        'user_request/request.html',
        _build_dog_capture_request_page_context(request),
    )


def _dog_capture_request_redirect():
    return redirect('user:dog_capture_request')


def _build_uploaded_capture_images(request):
    uploaded_images = list(request.FILES.getlist('images'))
    legacy_image = request.FILES.get('image')
    if legacy_image:
        uploaded_images.append(legacy_image)

    captured_images = [
        payload
        for payload in request.POST.getlist('captured_image')
        if payload and ';base64,' in payload
    ]
    if not captured_images:
        captured_image = request.POST.get('captured_image')
        if captured_image and ';base64,' in captured_image:
            captured_images = [captured_image]

    if captured_images:
        timestamp = int(timezone.now().timestamp())
        for index, captured_image in enumerate(captured_images, start=1):
            try:
                header, imgstr = captured_image.split(';base64,', 1)
                if 'image/jpeg' in header or 'image/jpg' in header:
                    extension = 'jpg'
                elif 'image/webp' in header:
                    extension = 'webp'
                else:
                    extension = 'png'
                filename = f"capture_{request.user.id}_{timestamp}_{index}.{extension}"
                uploaded_images.append(
                    ContentFile(base64.b64decode(imgstr), name=filename)
                )
            except (ValueError, binascii.Error):
                messages.error(request, "One of the captured photos could not be processed. Please try again.")
                return None

    return uploaded_images


def _get_or_create_request_profile(user):
    try:
        return user.profile
    except Profile.DoesNotExist:
        return Profile.objects.create(
            user=user,
            address="",
            age=18,
            consent_given=True,
        )


class _DogCaptureStatusPaginator(Paginator):
    """Paginator that uses a precomputed total so we avoid a duplicate COUNT() query."""

    def __init__(self, object_list, per_page, *, total_count, orphans=0, allow_empty_first_page=True):
        self._fixed_total_count = int(total_count)
        super().__init__(object_list, per_page, orphans, allow_empty_first_page)

    @cached_property
    def count(self):
        return self._fixed_total_count


def _paginate_dog_capture_status(request, rows_per_page, status_key, page_param, *, total_count=None):
    qs = (
        DogCaptureRequest.objects.filter(
            requested_by=request.user,
            status=status_key,
        )
        .prefetch_related("images", "landmark_images")
        .order_by("-created_at")
    )
    if total_count is None:
        paginator = Paginator(qs, rows_per_page)
    else:
        paginator = _DogCaptureStatusPaginator(qs, rows_per_page, total_count=total_count)
    page_obj = paginator.get_page(request.GET.get(page_param, 1))
    return page_obj, list(page_obj.object_list)


def _build_dog_capture_request_page_context(request):
    rows_per_page = 5
    valid_tabs = {"scheduled", "pending", "declined", "captured"}
    active_status_tab = (request.GET.get("status_tab") or "scheduled").strip().lower()
    if active_status_tab not in valid_tabs:
        active_status_tab = "scheduled"

    if not request.user.is_authenticated:
        empty_page_obj = Paginator([], rows_per_page).get_page(1)
        return {
            **DOG_SURRENDER_FORM_CONTEXT,
            'requests': False,
            'accepted_requests': [],
            'pending_requests': [],
            'declined_requests': [],
            'captured_requests': [],
            'accepted_page_obj': empty_page_obj,
            'pending_page_obj': empty_page_obj,
            'declined_page_obj': empty_page_obj,
            'captured_page_obj': empty_page_obj,
            'accepted_total': 0,
            'pending_total': 0,
            'declined_total': 0,
            'captured_total': 0,
            'active_status_tab': active_status_tab,
            'default_manual_city': DEFAULT_REQUEST_CITY,
            'manual_barangays': BAYAWAN_BARANGAYS,
        }

    status_totals = {
        row["status"]: row["total"]
        for row in DogCaptureRequest.objects.filter(
            requested_by=request.user
        ).values("status").annotate(total=Count("id"))
    }
    accepted_page_obj, accepted_requests = _paginate_dog_capture_status(
        request,
        rows_per_page,
        "accepted",
        "scheduled_page",
        total_count=status_totals.get("accepted", 0),
    )
    pending_page_obj, pending_requests = _paginate_dog_capture_status(
        request,
        rows_per_page,
        "pending",
        "pending_page",
        total_count=status_totals.get("pending", 0),
    )
    declined_page_obj, declined_requests = _paginate_dog_capture_status(
        request,
        rows_per_page,
        "declined",
        "declined_page",
        total_count=status_totals.get("declined", 0),
    )
    captured_page_obj, captured_requests = _paginate_dog_capture_status(
        request,
        rows_per_page,
        "captured",
        "captured_page",
        total_count=status_totals.get("captured", 0),
    )

    return {
        **DOG_SURRENDER_FORM_CONTEXT,
        'requests': bool(status_totals),
        'accepted_requests': accepted_requests,
        'pending_requests': pending_requests,
        'declined_requests': declined_requests,
        'captured_requests': captured_requests,
        'accepted_page_obj': accepted_page_obj,
        'pending_page_obj': pending_page_obj,
        'declined_page_obj': declined_page_obj,
        'captured_page_obj': captured_page_obj,
        'accepted_total': status_totals.get("accepted", 0),
        'pending_total': status_totals.get("pending", 0),
        'declined_total': status_totals.get("declined", 0),
        'captured_total': status_totals.get("captured", 0),
        'active_status_tab': active_status_tab,
        'default_manual_city': DEFAULT_REQUEST_CITY,
        'manual_barangays': BAYAWAN_BARANGAYS,
    }


_SURRENDER_APPEARANCE_ERRORS = {
    "colors_required": "Please select at least one coat color.",
    "color_other": 'Please enter the other color description when "Other" is selected.',
    "gender_required": "Please select dog gender.",
}
_SURRENDER_BREED_AGE_ERRORS = {
    "dog_age_years_invalid": "Dog age (years) must be a whole number.",
    "dog_age_years_range": "Dog age (years) must be between 0 and 30.",
    "breed_other_required": 'Please describe the breed when "Other" is selected.',
}


def _parse_surrender_dog_appearance(post_data):
    """Normalize gender and color fields (same vocabulary as admin dog posts)."""
    valid_colors = {c[0] for c in Post.COLOR_CHOICES}
    raw_colors = post_data.getlist("colors")
    colors = list(dict.fromkeys(c for c in raw_colors if c in valid_colors))
    if not colors:
        return False, "colors_required"

    color_other = " ".join((post_data.get("color_other") or "").split()).strip()
    if Post.COLOR_OTHER in colors and not color_other:
        return False, "color_other"
    if Post.COLOR_OTHER not in colors:
        color_other = ""

    gender = (post_data.get("gender") or "").strip()
    valid_genders = {c[0] for c in Post.GENDER_CHOICES}
    if not gender or gender not in valid_genders:
        return False, "gender_required"

    return True, (gender, colors, color_other)


def _parse_surrender_dog_breed_age(post_data):
    """Optional breed / age fields (same breed vocabulary as admin dog posts)."""
    valid_breeds = {c[0] for c in Post.BREED_CHOICES}
    dog_breed = (post_data.get("dog_breed") or "").strip()
    if dog_breed not in valid_breeds:
        dog_breed = ""
    dog_breed_other = " ".join((post_data.get("dog_breed_other") or "").split()).strip()
    if dog_breed != Post.BREED_OTHER:
        dog_breed_other = ""
    elif not dog_breed_other:
        return False, "breed_other_required"

    dog_age_group = (post_data.get("dog_age_group") or "").strip()
    valid_age_groups = {c[0] for c in Post.AGE_GROUP_CHOICES}
    if dog_age_group not in valid_age_groups:
        dog_age_group = ""

    raw_years = (post_data.get("dog_age_years") or "").strip()
    dog_age_years = None
    if raw_years:
        try:
            y = int(raw_years)
        except ValueError:
            return False, "dog_age_years_invalid"
        if y < 0 or y > 30:
            return False, "dog_age_years_range"
        dog_age_years = y

    return True, (dog_breed, dog_breed_other, dog_age_group, dog_age_years)


def _handle_dog_capture_request_submission(request):
    uploaded_images = _build_uploaded_capture_images(request)
    if uploaded_images is None:
        return _dog_capture_request_redirect()

    uploaded_images = [
        f
        for f in uploaded_images
        if f and getattr(f, "size", 0) > 0
    ]
    if len(uploaded_images) < DOG_SURRENDER_MIN_DOG_PHOTOS:
        messages.error(request, SURRENDER_DOG_PHOTOS_REQUIREMENT_TEXT)
        return _dog_capture_request_redirect()

    phone_number = _normalize_ph_phone_number(request.POST.get('phone_number'))
    request_type = DOG_SURRENDER_REQUEST_TYPE
    if not phone_number:
        messages.error(
            request,
            "Please enter a valid Philippine mobile number, such as 0917 123 4567 or +63 917 123 4567.",
        )
        return _dog_capture_request_redirect()

    profile = _get_or_create_request_profile(request.user)
    profile.phone_number = phone_number
    profile.save(update_fields=["phone_number"])

    appearance_ok, appearance = _parse_surrender_dog_appearance(request.POST)
    if not appearance_ok:
        messages.error(request, _SURRENDER_APPEARANCE_ERRORS[appearance])
        return _dog_capture_request_redirect()
    gender, colors, color_other = appearance

    breed_age_ok, breed_age = _parse_surrender_dog_breed_age(request.POST)
    if not breed_age_ok:
        messages.error(request, _SURRENDER_BREED_AGE_ERRORS[breed_age])
        return _dog_capture_request_redirect()
    dog_breed, dog_breed_other, dog_age_group, dog_age_years = breed_age

    reason = (request.POST.get('reason') or 'stray').strip()
    if not _is_valid_capture_reason(reason):
        reason = 'stray'
    description = (request.POST.get('description') or '').strip()
    latitude_raw = (request.POST.get('latitude') or '').strip()
    longitude_raw = (request.POST.get('longitude') or '').strip()
    gps_accuracy_raw = (request.POST.get('gps_accuracy') or '').strip()
    gps_accuracy_meters = _parse_gps_accuracy_meters(gps_accuracy_raw)
    submission_type = DOG_ONLINE_SUBMISSION_TYPE

    location_mode = (request.POST.get('location_mode') or 'exact').strip().lower()
    if location_mode not in {'exact', 'manual'}:
        location_mode = 'exact'

    barangay = _clean_barangay(request.POST.get('barangay'))
    city = _clean_barangay(request.POST.get('city')) or DEFAULT_REQUEST_CITY
    manual_full_address = " ".join(
        (request.POST.get('manual_full_address') or '').split()
    ).strip()
    location_landmark_images = list(request.FILES.getlist('location_landmark_image'))

    if submission_type == 'online' and location_mode == 'manual':
        resolved_barangay = _resolve_barangay_name(barangay)
        if not resolved_barangay:
            messages.error(request, "Please choose a valid barangay from the list.")
            return _dog_capture_request_redirect()
        barangay = resolved_barangay
        latitude_value = None
        longitude_value = None
    elif submission_type == 'online':
        if not latitude_raw or not longitude_raw:
            messages.error(request, 'Please use "Locate My Location" first, or switch to manual barangay selection.')
            return _dog_capture_request_redirect()
        try:
            latitude_val = float(latitude_raw)
            longitude_val = float(longitude_raw)
        except ValueError:
            messages.error(request, "Latitude and longitude must be valid numbers.")
            return _dog_capture_request_redirect()

        if not (-90 <= latitude_val <= 90 and -180 <= longitude_val <= 180):
            messages.error(request, "Coordinates are out of valid range.")
            return _dog_capture_request_redirect()

        if gps_accuracy_meters is None:
            messages.error(
                request,
                'We could not verify the precision of your browser location. Please tap "Locate My Location" again or switch to manual barangay selection.',
            )
            return _dog_capture_request_redirect()

        if gps_accuracy_meters > DOG_CAPTURE_MAX_ACCEPTABLE_GPS_ACCURACY_METERS:
            messages.error(
                request,
                f'Your browser location is too coarse ({round(gps_accuracy_meters)} meters). Please turn on precise location/GPS, then tap "Locate My Location" again, or switch to manual barangay selection.',
            )
            return _dog_capture_request_redirect()

        latitude_value = f"{latitude_val:.6f}"
        longitude_value = f"{longitude_val:.6f}"
        manual_full_address = ""
        location_landmark_images = []
        if not barangay:
            profile_barangay = _clean_barangay(profile.address)
            barangay = _resolve_barangay_name(profile_barangay) or profile_barangay
    else:
        barangay = None
        city = None
        manual_full_address = ""
        location_landmark_images = []
        latitude_value = None
        longitude_value = None

    new_req = DogCaptureRequest.objects.create(
        requested_by=request.user,
        request_type=request_type,
        submission_type=submission_type or None,
        preferred_appointment_date=None,
        reason=reason,
        description=description or None,
        gender=gender,
        colors=colors,
        color_other=color_other,
        dog_breed=dog_breed,
        dog_breed_other=dog_breed_other,
        dog_age_group=dog_age_group,
        dog_age_years=dog_age_years,
        latitude=latitude_value,
        longitude=longitude_value,
        barangay=(_resolve_barangay_name(barangay) or barangay) if barangay else None,
        city=city or None,
        manual_full_address=manual_full_address or None,
        location_landmark_image=location_landmark_images[0] if location_landmark_images else None,
        image=None
    )

    if location_mode == 'manual':
        for landmark_file in location_landmark_images[1:]:
            DogCaptureRequestLandmarkImage.objects.create(
                request=new_req,
                image=landmark_file,
            )

    first_saved_image = None
    for image_file in uploaded_images:
        saved_image = DogCaptureRequestImage.objects.create(
            request=new_req,
            image=image_file,
        )
        if first_saved_image is None:
            first_saved_image = saved_image.image

    if first_saved_image:
        new_req.image = first_saved_image
        new_req.save(update_fields=['image'])

    AdminNotification.objects.create(
        title=f"New {new_req.get_request_type_display().lower()}",
        message=f"{request.user.username} submitted a {new_req.get_request_type_display().lower()}.",
        url="/vetadmin/dog-capture/requests/",
    )
    cache.delete(ADMIN_NOTIFICATIONS_CACHE_KEY)
    messages.success(request, "Request submitted successfully.")
    return None


def _parse_removable_landmark_ids(raw_ids):
    remove_landmark_ids = set()
    for raw_id in raw_ids:
        try:
            remove_landmark_ids.add(int(raw_id))
        except (TypeError, ValueError):
            continue
    return remove_landmark_ids


def _resolve_capture_location_mode(request, latitude_raw, longitude_raw):
    location_mode = (
        request.POST.get('location_mode')
        or request.POST.get('edit_location_mode')
        or ''
    ).strip().lower()
    if location_mode not in {'exact', 'manual'}:
        location_mode = 'exact' if (latitude_raw or longitude_raw) else 'manual'
    return location_mode


def _clear_request_landmark_images(req):
    if req.location_landmark_image:
        req.location_landmark_image.delete(save=False)
    req.location_landmark_image = None
    for landmark in req.landmark_images.all():
        landmark.image.delete(save=False)
    req.landmark_images.all().delete()


def _replace_request_landmark_images(req, location_landmark_images):
    for landmark in req.landmark_images.all():
        landmark.image.delete(save=False)
    req.landmark_images.all().delete()
    if req.location_landmark_image:
        req.location_landmark_image.delete(save=False)
    req.location_landmark_image = location_landmark_images[0]
    for landmark_file in location_landmark_images[1:]:
        DogCaptureRequestLandmarkImage.objects.create(
            request=req,
            image=landmark_file,
        )


@user_only
@require_POST
def edit_dog_capture_request(request, req_id):
    """Edit a pending online dog-surrender request submitted by the current user."""
    req = get_object_or_404(
        DogCaptureRequest,
        id=req_id,
        requested_by=request.user,
    )

    # User can only update requests that are still waiting for admin action.
    if req.status != 'pending':
        messages.warning(request, "Only pending requests can be edited.")
        return redirect('user:dog_capture_request')

    reason = (request.POST.get('reason') or req.reason or 'stray').strip()
    if not _is_valid_capture_reason(reason):
        reason = 'stray'
    description = (request.POST.get('description') or '').strip()
    appearance_ok, appearance = _parse_surrender_dog_appearance(request.POST)
    if not appearance_ok:
        messages.error(request, _SURRENDER_APPEARANCE_ERRORS[appearance])
        return redirect('user:dog_capture_request')
    gender, colors, color_other = appearance
    breed_age_ok, breed_age = _parse_surrender_dog_breed_age(request.POST)
    if not breed_age_ok:
        messages.error(request, _SURRENDER_BREED_AGE_ERRORS[breed_age])
        return redirect('user:dog_capture_request')
    dog_breed, dog_breed_other, dog_age_group, dog_age_years = breed_age
    request_type = DOG_SURRENDER_REQUEST_TYPE
    barangay = _clean_barangay(request.POST.get('barangay'))
    city = _clean_barangay(request.POST.get('city')) or DEFAULT_REQUEST_CITY
    manual_full_address = " ".join(
        (request.POST.get('manual_full_address') or '').split()
    ).strip()
    location_landmark_images = list(request.FILES.getlist('location_landmark_image'))
    remove_primary_landmark = (request.POST.get('remove_primary_landmark') or '').strip() == '1'
    raw_remove_landmark_ids = request.POST.getlist('remove_landmark_image_ids')
    latitude_raw = (request.POST.get('latitude') or '').strip()
    longitude_raw = (request.POST.get('longitude') or '').strip()
    remove_landmark_ids = _parse_removable_landmark_ids(raw_remove_landmark_ids)
    location_mode = _resolve_capture_location_mode(request, latitude_raw, longitude_raw)
    submission_type = DOG_ONLINE_SUBMISSION_TYPE

    # Exact mode stores GPS coordinates; manual mode stores full manual address.
    if submission_type == 'online' and location_mode == 'exact':
        if not latitude_raw or not longitude_raw:
            messages.error(request, "Please provide both latitude and longitude.")
            return redirect('user:dog_capture_request')

        try:
            latitude_val = float(latitude_raw)
            longitude_val = float(longitude_raw)
        except ValueError:
            messages.error(request, "Latitude and longitude must be valid numbers.")
            return redirect('user:dog_capture_request')

        if not (-90 <= latitude_val <= 90 and -180 <= longitude_val <= 180):
            messages.error(request, "Coordinates are out of valid range.")
            return redirect('user:dog_capture_request')

        req.latitude = f"{latitude_val:.6f}"
        req.longitude = f"{longitude_val:.6f}"
        req.manual_full_address = None
        _clear_request_landmark_images(req)
    elif submission_type == 'online':
        resolved_barangay = _resolve_barangay_name(barangay)
        if not resolved_barangay:
            messages.error(request, "Please choose a valid barangay from the list.")
            return redirect('user:dog_capture_request')
        req.latitude = None
        req.longitude = None
        req.manual_full_address = manual_full_address or None
        barangay = resolved_barangay

        if remove_primary_landmark and req.location_landmark_image:
            req.location_landmark_image.delete(save=False)
            req.location_landmark_image = None

        if remove_landmark_ids:
            landmarks_to_remove = req.landmark_images.filter(id__in=remove_landmark_ids)
            for landmark in landmarks_to_remove:
                landmark.image.delete(save=False)
            landmarks_to_remove.delete()

        if location_landmark_images:
            _replace_request_landmark_images(req, location_landmark_images)
    else:
        req.latitude = None
        req.longitude = None
        req.manual_full_address = None
        req.barangay = None
        req.city = None
        _clear_request_landmark_images(req)
        city = None
        barangay = None

    req.request_type = request_type
    req.submission_type = submission_type or None
    req.preferred_appointment_date = None
    req.reason = reason
    req.description = description or None
    req.gender = gender
    req.colors = colors
    req.color_other = color_other
    req.dog_breed = dog_breed
    req.dog_breed_other = dog_breed_other
    req.dog_age_group = dog_age_group
    req.dog_age_years = dog_age_years
    req.barangay = (_resolve_barangay_name(barangay) or barangay) if barangay else None
    req.city = city or None
    req.save(
        update_fields=[
            'request_type',
            'submission_type',
            'preferred_appointment_date',
            'reason',
            'description',
            'gender',
            'colors',
            'color_other',
            'dog_breed',
            'dog_breed_other',
            'dog_age_group',
            'dog_age_years',
            'barangay',
            'city',
            'latitude',
            'longitude',
            'manual_full_address',
            'location_landmark_image',
        ]
    )

    messages.success(request, "Request updated successfully.")
    return redirect('user:dog_capture_request')


@user_only
@require_POST
def delete_dog_capture_request(request, req_id):
    """Delete a pending dog-capture request owned by the current user."""
    req = get_object_or_404(
        DogCaptureRequest,
        id=req_id,
        requested_by=request.user,
    )

    # Prevent deleting requests that are already scheduled/processed by admin.
    if req.status != 'pending':
        messages.warning(request, "Only pending requests can be deleted.")
        return redirect('user:dog_capture_request')

    req.delete()
    messages.success(request, "Request deleted successfully.")
    return redirect('user:dog_capture_request')


# =============================================================================
# Navigation 3/5: Claim
# Covers claim browsing, claim history, and claim confirmation.
# =============================================================================

@user_only
def claim(request):
    """Render the claim dashboard shell."""
    return render(request, 'claim/claim.html')

# =============================================================================
# Navigation 5/5: Adopt
# Covers adoption browsing, adoption status, and adoption confirmation.
# =============================================================================

def adopt_list(request):
    """Browse dogs that are available for adoption."""
    return _render_public_post_listing_page(request, "adopt")

@user_only
def adopt_status(request):
    """Show the current user's adoption request history and statuses."""
    source_type = request.GET.get("source", "all")
    if source_type not in {"all", "staff", "user"}:
        source_type = "all"
    status_filter = request.GET.get("status", "pending")
    if status_filter not in {"total", "pending", "accepted", "rejected"}:
        status_filter = "pending"

    staff_requests_base_qs = _user_post_requests(request.user, "adopt")
    user_requests_base_qs = UserAdoptionRequest.objects.filter(
        requester=request.user,
    ).select_related("post", "post__owner", "post__owner__profile").order_by("-created_at")

    staff_summary = _request_status_summary_from_qs(
        staff_requests_base_qs,
        accepted_status="accepted",
        rejected_status="rejected",
    )
    user_summary = _request_status_summary_from_qs(
        user_requests_base_qs,
        accepted_status="approved",
        rejected_status="rejected",
    )

    show_staff_requests = source_type in {"all", "staff"}
    show_user_requests = source_type in {"all", "user"}
    items_per_page = 8 if source_type == "all" else 16

    if source_type == "staff":
        summary = staff_summary
    elif source_type == "user":
        summary = user_summary
    else:
        summary = {
            "total": staff_summary["total"] + user_summary["total"],
            "pending": staff_summary["pending"] + user_summary["pending"],
            "accepted": staff_summary["accepted"] + user_summary["accepted"],
            "rejected": staff_summary["rejected"] + user_summary["rejected"],
        }

    staff_requests_qs = staff_requests_base_qs
    user_requests_qs = user_requests_base_qs
    if status_filter != "total":
        if status_filter == "accepted":
            staff_requests_qs = staff_requests_qs.filter(status="accepted")
            user_requests_qs = user_requests_qs.filter(status="approved")
        else:
            staff_requests_qs = staff_requests_qs.filter(status=status_filter)
            user_requests_qs = user_requests_qs.filter(status=status_filter)

    staff_page_obj = None
    staff_requests = []
    if show_staff_requests:
        staff_page = request.GET.get("staff_page", 1)
        staff_page_obj = Paginator(staff_requests_qs, items_per_page).get_page(staff_page)
        staff_requests = list(staff_page_obj.object_list)

    user_page_obj = None
    user_requests = []
    if show_user_requests:
        user_page = request.GET.get("user_page", 1)
        user_page_obj = Paginator(user_requests_qs, items_per_page).get_page(user_page)
        user_requests = list(user_page_obj.object_list)

    return render(request, 'adopt/adopt.html', {
        'summary': summary,
        'browse_url': reverse("user:redeem_list"),
        'current_source': source_type,
        'current_status': status_filter,
        'show_staff_requests': show_staff_requests,
        'show_user_requests': show_user_requests,
        'staff_requests': staff_requests,
        'staff_page_obj': staff_page_obj,
        'user_requests': user_requests,
        'user_page_obj': user_page_obj,
        'staff_summary': staff_summary,
        'user_summary': user_summary,
    })


@user_only
def my_post_approvals(request):
    """List the current user's adoption and missing-dog posts and staff approval status."""
    status_filter = request.GET.get("status", "pending")
    if status_filter not in {"total", "pending", "accepted", "rejected"}:
        status_filter = "pending"

    all_entries = _collect_user_post_submissions(request.user)
    summary = _user_post_submissions_summary(all_entries)
    if status_filter == "total":
        filtered = all_entries
    else:
        filtered = [row for row in all_entries if row["bucket"] == status_filter]

    page_obj = Paginator(filtered, 10).get_page(request.GET.get("page", 1))
    return render(request, "adopt/my_post_approvals.html", {
        "submissions": list(page_obj.object_list),
        "summary": summary,
        "current_status": status_filter,
        "page_obj": page_obj,
        "browse_url": reverse("user:adopt_list"),
    })


def adopt_confirm(request, post_id):
    """Confirm and submit an adoption request for a staff-managed post."""
    access_response = _require_public_member_or_auth_modal(
        request,
        next_url=request.get_full_path(),
    )
    if access_response is not None:
        return access_response
    return _handle_confirm_request(
        request=request,
        post_id=post_id,
        request_type="adopt",
        template_name="adopt/adopt_confirm.html",
        is_open_fn=lambda post: post.current_phase() in {"claim", "adopt"},
        not_open_message=lambda post: (
            "Adoption is not available for this post anymore."
            if post.current_phase() == "closed"
            else "Adoption is not open for this post yet."
        ),
        duplicate_message=lambda post: (
            "You already reserved adoption for this dog."
            if post.current_phase() == "claim"
            else "You already submitted an adoption request."
        ),
        success_message=lambda post: (
            "Adoption reserved. If no owner redemption is approved, admin review opens after the redemption window closes."
            if post.current_phase() == "claim"
            else "Adoption request submitted. The post stays visible while admin verification runs for 1 day."
        ),
    )
# =============================================================================
# Navigation 4/5: Announcement
# Covers announcement browsing, details, reactions, comments, and sharing.
# =============================================================================


def _announcement_card_prefetch():
    return Prefetch(
        "images",
        queryset=DogAnnouncementImage.objects.only(
            "id",
            "announcement_id",
            "image",
            "created_at",
        ).order_by("created_at", "id"),
        to_attr="prefetched_images",
    )


def _announcement_feed_queryset():
    return (
        DogAnnouncement.objects.select_related("created_by", "created_by__profile")
        .prefetch_related(_announcement_card_prefetch())
        .order_by("-created_at")
    )


def _decorate_announcement_posts(posts, request):
    default_admin_avatar_url = static("images/officialseal.webp")
    for post in posts:
        post.admin_profile_image_url = _profile_image_url_or_default(
            post.created_by, default_admin_avatar_url
        )
        post.content_display = _clean_announcement_text_for_display(post.content)
        post.share_url = _announcement_feed_share_url(request, post.id)
    return posts


def announcement_list(request):
    """Render the public announcement feed grouped by display bucket."""
    board_redirect = _announcement_maybe_redirect_for_highlight(request)
    if board_redirect:
        return redirect(board_redirect)

    bucket_counts = {
        row["display_bucket"]: row["total"]
        for row in DogAnnouncement.objects.values("display_bucket").annotate(
            total=Count("id")
        )
    }
    pinned_announcements = list(
        _announcement_feed_queryset().filter(
            display_bucket=DogAnnouncement.BUCKET_PINNED
        )[:PUBLIC_ANNOUNCEMENT_SIDEBAR_LIMIT]
    )
    regular_qs = _announcement_feed_queryset().exclude(
        display_bucket=DogAnnouncement.BUCKET_PINNED
    )
    regular_page_obj = Paginator(
        regular_qs,
        PUBLIC_ANNOUNCEMENT_PAGE_SIZE,
    ).get_page(request.GET.get("page", 1))
    regular_announcements = list(regular_page_obj.object_list)

    _decorate_announcement_posts(pinned_announcements, request)
    _decorate_announcement_posts(regular_announcements, request)

    total_announcements = sum(bucket_counts.values())
    pinned_count = bucket_counts.get(DogAnnouncement.BUCKET_PINNED, 0)
    regular_total = max(total_announcements - pinned_count, 0)
    pagination_query = _pagination_query_without_page(request.GET)

    tab = (request.GET.get("tab") or "").strip().lower()
    announcement_initial_tab = "pinned" if tab == "pinned" else "regular"

    announcement_show_staff_pin = False
    if request.user.is_authenticated and request.user.is_staff and request.user.is_active:
        announcement_show_staff_pin = is_route_allowed(
            get_admin_access(request.user),
            "announcement_update_bucket",
        )

    board_context = {
        'pinned_announcements': pinned_announcements,
        'regular_announcements': regular_announcements,
        'pinned_count': pinned_count,
        'regular_total': regular_total,
        'regular_page_obj': regular_page_obj,
        'announcement_pagination_query': pagination_query,
        'announcement_show_staff_pin': announcement_show_staff_pin,
        'announcement_initial_tab': announcement_initial_tab,
        'announcement_dog_info_page': False,
    }
    board_context.update(_announcement_highlight_open_graph(request))
    return render(request, 'announcement/announcement.html', board_context)


def announcement_dog_info(request):
    """Static dog safety / infographic content linked from the announcements board."""
    bucket_counts = {
        row["display_bucket"]: row["total"]
        for row in DogAnnouncement.objects.values("display_bucket").annotate(
            total=Count("id")
        )
    }
    pinned_count = bucket_counts.get(DogAnnouncement.BUCKET_PINNED, 0)
    total_announcements = sum(bucket_counts.values())
    regular_total = max(total_announcements - pinned_count, 0)
    return render(
        request,
        "announcement/announcement_dog_info.html",
        {
            "pinned_count": pinned_count,
            "regular_total": regular_total,
            "announcement_dog_info_page": True,
        },
    )


@require_POST
def announcement_public_toggle_pin(request, post_id):
    """Let vet staff pin/unpin from the public announcements board (same access as admin bucket update)."""
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "auth_required": True}, status=401)
    if not request.user.is_staff or not request.user.is_active:
        return JsonResponse({"ok": False, "error": "Forbidden"}, status=403)
    access = get_admin_access(request.user)
    if not is_route_allowed(access, "announcement_update_bucket"):
        return JsonResponse({"ok": False, "error": "Forbidden"}, status=403)

    post = get_object_or_404(DogAnnouncement.objects.only("id", "display_bucket"), id=post_id)
    if post.display_bucket == DogAnnouncement.BUCKET_PINNED:
        post.display_bucket = DogAnnouncement.BUCKET_ORDINARY
    else:
        post.display_bucket = DogAnnouncement.BUCKET_PINNED
    post.save(update_fields=["display_bucket"])
    return JsonResponse({
        "ok": True,
        "bucket": post.display_bucket,
        "is_pinned": post.display_bucket == DogAnnouncement.BUCKET_PINNED,
    })


def announcement_detail(request, post_id):
    """Render a detailed announcement view with share data."""
    post = get_object_or_404(
        DogAnnouncement.objects.select_related("created_by", "created_by__profile").prefetch_related(
            Prefetch(
                "images",
                queryset=DogAnnouncementImage.objects.only(
                    "id",
                    "announcement_id",
                    "image",
                    "created_at",
                ).order_by("created_at", "id"),
                to_attr="prefetched_images",
            ),
        ),
        id=post_id,
    )
    post.admin_profile_image_url = _profile_image_url_or_default(
        post.created_by, static("images/officialseal.webp")
    )
    post.content_display = _clean_announcement_text_for_display(post.content)

    og_image_url = ""
    if post.background_image:
        og_image_url = request.build_absolute_uri(post.background_image.url)
    elif getattr(post, "prefetched_images", None):
        og_image_url = request.build_absolute_uri(post.prefetched_images[0].image.url)

    plain_description = strip_tags(post.content or "").strip()
    if len(plain_description) > 200:
        plain_description = f"{plain_description[:197].rstrip()}..."
    if not plain_description:
        plain_description = "Announcement from Bayawan Vet."

    return render(request, 'announcement/announcement_detail.html', {
        'post': post,
        'og_image_url': og_image_url,
        'og_description': plain_description,
        'share_url': _announcement_feed_share_url(request, post.id),
    })


def announcement_share_preview(request, post_id):
    """Legacy share path: redirect to the announcements board with highlight=<id>."""
    return redirect(f"{reverse('user:announcement_list')}?{urlencode({'highlight': str(post_id)})}")


@user_only
def announcement_comment(request, post_id):
    """Create a comment on an announcement and return to the previous page."""
    if request.method == "POST":
        AnnouncementComment.objects.create(
            announcement_id=post_id,
            user=request.user,
            comment=request.POST.get("comment")
        )
    next_url = (request.POST.get("next") or "").strip()
    if not next_url or not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = reverse('user:announcement_list')
    return redirect(next_url)

# Navigation 3/5: Redeem continued
@user_only
def my_redemptions(request):
    """Show the current user's submitted redemption requests and their statuses."""
    status_filter = request.GET.get("status", "pending")
    if status_filter not in {"total", "pending", "accepted", "rejected"}:
        status_filter = "pending"

    claims_base_qs = _user_post_requests(request.user, "claim")
    summary = _request_status_summary_from_qs(
        claims_base_qs,
        accepted_status="accepted",
        rejected_status="rejected",
    )

    claims_qs = claims_base_qs if status_filter == "total" else claims_base_qs.filter(status=status_filter)
    page_obj = Paginator(claims_qs, 10).get_page(request.GET.get("page", 1))
    claims = list(page_obj.object_list)

    return render(request, 'claim/claim.html', {
        'claims': claims,
        'summary': summary,
        'current_status': status_filter,
        'page_obj': page_obj,
        'browse_url': reverse("user:redeem_list"),
    })


def redeem_list(request):
    """Browse dogs that are still available for owner redemption."""
    return _render_public_post_listing_page(request, "claim")


def redeem_confirm(request, post_id):
    """Confirm and submit a redemption request for a staff-managed post."""
    access_response = _require_public_member_or_auth_modal(
        request,
        next_url=request.get_full_path(),
    )
    if access_response is not None:
        return access_response
    return _handle_confirm_request(
        request=request,
        post_id=post_id,
        request_type="claim",
        template_name="claim/claim_confirm.html",
        is_open_fn=lambda post: post.is_open_for_claim(),
        not_open_message="Redemption period has ended for this post.",
        duplicate_message="You already submitted a redemption for this dog.",
        success_message="Redemption submitted. The post stays visible while admin verification runs for 1 day.",
    )


def user_adoption_history(request):
    """Render a community-wide history of successful user-to-user adoptions."""
    history_qs = (
        UserAdoptionRequest.objects.filter(status="approved")
        .select_related(
            "post",
            "post__owner",
            "post__owner__profile",
            "requester",
            "requester__profile",
        )
        .prefetch_related(
            Prefetch(
                "post__images",
                queryset=UserAdoptionImage.objects.only("id", "post_id", "image").order_by("id"),
            )
        )
        .order_by("-created_at")
    )
    page_obj = Paginator(history_qs, ADOPTION_HISTORY_PER_PAGE).get_page(request.GET.get("page", 1))
    context = {
        "page_obj": page_obj,
        "page_title": "Adoption History",
        "active_nav": "adopt",
    }
    return render(request, "adopt/adoption_history.html", context)


def missing_dogs_list(request):
    """Browse approved missing-dog posts with name/barangay/breed/urgency filters."""
    # select_related('owner') + prefetch extra photos (modal gallery) without N+1.
    qs = (
        MissingDogPost.objects.filter(status__in=['missing', 'found'])
        .select_related("owner", "owner__profile")
        .prefetch_related('photos')
    )

    dog_name_q = request.GET.get('dog_name', '').strip()
    if dog_name_q:
        qs = qs.filter(dog_name__icontains=dog_name_q)

    barangay_q = request.GET.get('barangay', '').strip() or request.GET.get('location', '').strip()
    if barangay_q:
        qs = qs.filter(location__icontains=barangay_q)

    breed = request.GET.get('breed', 'all').strip().lower()
    breed_choices = list(Post.BREED_CHOICES)
    allowed_breeds = {'all', *[value for value, _label in breed_choices]}
    if breed not in allowed_breeds:
        breed = 'all'
    if breed != 'all':
        # Match exact breed choice value OR fall back to text search for breed_other / description
        qs = qs.filter(
            Q(breed__iexact=breed) |
            Q(breed_other__icontains=breed) |
            Q(description__icontains=breed)
        )

    urgency = request.GET.get('urgency', 'all').strip().lower()
    if urgency not in {'all', 'urgent'}:
        urgency = 'all'
    if urgency == 'urgent':
        # Pure-SQL equivalent of the prior Python loop: a post is urgent when its
        # (date_lost, time_lost) combined timestamp is within the last 48h. Pushing
        # this into the DB avoids materialising every candidate row in Python
        # (previously an O(N) loop + extra id__in round-trip).
        cutoff_local = timezone.localtime(timezone.now() - timedelta(hours=48))
        cutoff_date = cutoff_local.date()
        cutoff_time = cutoff_local.time()
        qs = qs.filter(
            Q(date_lost__gt=cutoff_date) |
            Q(date_lost=cutoff_date, time_lost__gte=cutoff_time)
        )

    sort = request.GET.get('sort', 'newest')
    if sort == 'oldest':
        qs = qs.order_by('date_lost', 'time_lost')
    else:
        sort = 'newest'
        qs = qs.order_by('-date_lost', '-time_lost')

    paginator = Paginator(qs, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'posts': page_obj.object_list,
        'dog_name_q': dog_name_q,
        'barangay_q': barangay_q,
        'barangay_choices': BAYAWAN_BARANGAYS,
        'breed': breed,
        'breed_choices': breed_choices,
        'urgency': urgency,
        'sort': sort,
        'total': paginator.count,
    }
    context.update(_missing_dog_highlight_open_graph(request))
    return render(request, 'missing/missing_dogs.html', context)


def missing_dog_public_detail(request, post_id):
    """Public URL for one missing-dog post — used when share links are opened in Facebook, etc."""
    post = get_object_or_404(
        MissingDogPost.objects.select_related("owner")
        .prefetch_related(
            Prefetch(
                "photos",
                queryset=MissingDogPhoto.objects.only("id", "post_id", "image").order_by("id"),
            )
        ),
        pk=post_id,
        status__in=["missing", "found"],
    )
    context = {
        "post": post,
        "page_title": f"{(post.dog_name or 'Dog').strip() or 'Dog'} — Missing · Bayawan Vet",
    }
    context.update(_missing_dog_og_context_for_post(request, post))
    return render(request, "missing/missing_dog_public.html", context)


# ── Sighting: submit form (login required) ────────────────────────────────────

@require_http_methods(['GET', 'POST'])
def report_sighting(request, post_id):
    """Show and handle the Report Sighting form for a missing dog post."""
    post = get_object_or_404(MissingDogPost, pk=post_id, status__in=['missing', 'found'])

    if not request.user.is_authenticated:
        # Open the shared auth modal on home page instead of the broken standalone login page
        return redirect(_build_home_auth_modal_url(request, "login", request.get_full_path()))

    if request.method == 'POST':
        form = DogSightingForm(request.POST, request.FILES)
        if form.is_valid():
            sighting = form.save(commit=False)
            sighting.post = post
            sighting.reporter = request.user
            sighting.save()
            messages.success(request, f'Your sighting for {post.dog_name} has been submitted. The owner will review it.')
            return redirect(reverse('user:missing_dogs_list'))
    else:
        from django.utils.timezone import localdate, localtime
        now = timezone.now()
        form = DogSightingForm(initial={
            'sighted_on': localdate(now),
            'sighted_at': localtime(now).strftime('%H:%M'),
        })

    return render(request, 'missing/report_sighting.html', {
        'form': form,
        'post': post,
    })


# ── Sighting: owner dashboard ─────────────────────────────────────────────────

@login_required
def my_sighting_inbox(request):
    """Paginated list of all sightings for posts owned by the current user."""
    sightings = (
        DogSighting.objects
        .filter(post__owner=request.user)
        .select_related('post', 'reporter', 'reporter__profile')
        .order_by('-created_at')
    )

    status_filter = request.GET.get('status', 'all')
    if status_filter in ('pending', 'verified', 'rejected'):
        sightings = sightings.filter(status=status_filter)

    page_obj = Paginator(sightings, 15).get_page(request.GET.get('page'))
    return render(request, 'missing/sighting_inbox.html', {
        'page_obj': page_obj,
        'sightings': page_obj.object_list,
        'status_filter': status_filter,
    })


# ── Sighting: owner action (verify / reject / ignore) ────────────────────────

@login_required
@require_POST
def sighting_action(request, sighting_id):
    """Owner verifies, rejects, or resets a sighting; keeps reporter counter in sync."""
    from .models import Profile as UserProfile
    from django.db.models import F

    sighting = get_object_or_404(
        DogSighting,
        pk=sighting_id,
        post__owner=request.user,
    )
    action     = request.POST.get('action', '')
    old_status = sighting.status

    if action == 'verify':
        sighting.status = 'verified'
        sighting.save(update_fields=['status'])
        # Increment reporter's counter only when transitioning into verified
        if old_status != 'verified':
            UserProfile.objects.filter(user=sighting.reporter).update(
                verified_sightings=F('verified_sightings') + 1
            )
        messages.success(request, 'Sighting marked as verified.')

    elif action == 'reject':
        sighting.status = 'rejected'
        sighting.save(update_fields=['status'])
        # Roll back counter if we're un-verifying; guard against going below 0
        if old_status == 'verified':
            UserProfile.objects.filter(
                user=sighting.reporter,
                verified_sightings__gt=0,
            ).update(verified_sightings=F('verified_sightings') - 1)
        messages.success(request, 'Sighting rejected.')

    elif action == 'ignore':
        sighting.status = 'pending'
        sighting.save(update_fields=['status'])
        # Roll back counter if we're un-verifying; guard against going below 0
        if old_status == 'verified':
            UserProfile.objects.filter(
                user=sighting.reporter,
                verified_sightings__gt=0,
            ).update(verified_sightings=F('verified_sightings') - 1)
        messages.success(request, 'Sighting reset to pending.')

    else:
        messages.error(request, 'Unknown action.')

    next_url = request.POST.get('next') or reverse('user:sighting_inbox')
    return redirect(next_url)


# ── Sighting: AJAX count for a post ──────────────────────────────────────────

def sighting_count_api(request, post_id):
    """Return JSON with verified sighting count for a missing dog post."""
    post = get_object_or_404(MissingDogPost, pk=post_id)
    count = DogSighting.objects.filter(post=post, status='verified').count()
    return JsonResponse({'post_id': post_id, 'verified_count': count})
