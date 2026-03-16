from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.db.models import Count, DateTimeField, Exists, OuterRef, Prefetch, Q
from django.db import IntegrityError
from django.db.models.expressions import RawSQL
import os
import json
import base64
import binascii
import hashlib
import random
import secrets
import shutil
from django.http import JsonResponse
from django.core.files.base import ContentFile
from django.conf import settings
from django.core.cache import cache
from datetime import timedelta
from functools import wraps
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.templatetags.static import static
from django.utils.html import strip_tags
from urllib.parse import urlencode

# Shared models from the admin app
from dogadoption_admin.models import (
    AdminNotification,
    AnnouncementComment,
    AnnouncementReaction,
    Barangay,
    Citation,
    Dog,
    DogAnnouncement,
    DogAnnouncementImage,
    DogImage,
    GlobalAppointmentDate,
    Post,
    PostRequest,
)
from dogadoption_admin.context_processors import ADMIN_NOTIFICATIONS_CACHE_KEY

# Models from the user app
from .models import Profile, DogCaptureRequest, DogCaptureRequestImage, DogCaptureRequestLandmarkImage, FaceImage, ClaimImage
from .models import UserAdoptionPost, UserAdoptionImage, UserAdoptionRequest, MissingDogPost

# Forms and notification helpers
from .forms import MissingDogPostForm, UserAdoptionPostForm
from .notification_utils import (
    USER_NOTIFICATIONS_SEEN_SESSION_KEY,
    bump_user_home_feed_namespace,
    get_user_home_feed_namespace,
    invalidate_user_notification_content,
    invalidate_user_notification_payload,
)

# Administrative and user models above are shared across multiple public flows.
# The view module is grouped below by shared helpers and user navigation links.

# =============================================================================
# Shared imports, constants, and helper utilities
# =============================================================================

ACTIVE_BARANGAY_LOOKUP_CACHE_KEY = "user_active_barangay_lookup"
ACTIVE_BARANGAY_LOOKUP_CACHE_TTL_SECONDS = 300
DEFAULT_REQUEST_CITY = "Bayawan City"
PHILIPPINES_COUNTRY_CODE = "+63"


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


def _build_registered_dog_payloads(dogs):
    """Convert registered dog rows into template-friendly profile cards."""
    rows = []
    for dog in dogs:
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
        })
    return rows


def _build_profile_dashboard_context(profile_user):
    """Build the profile page context used by user and admin preview modes."""
    profile, _ = Profile.objects.get_or_create(
        user=profile_user,
        defaults={
            "address": "",
            "age": 18,
            "consent_given": True
        }
    )

    recent_post_limit = 6
    default_profile_avatar_url = static("images/default-user-image.jpg")
    adoption_posts = list(
        UserAdoptionPost.objects.filter(owner=profile_user)
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
        .only("id", "dog_name", "location", "status", "created_at")
        .order_by("-created_at")[:recent_post_limit]
    )
    missing_posts = list(
        MissingDogPost.objects.filter(owner=profile_user)
        .only("id", "dog_name", "location", "status", "created_at", "image")
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
            "location": post.location,
            "status_key": post.status,
            "status_label": post.get_status_display(),
            "posted_label": _format_posted_label(post.created_at),
            "created_at": post.created_at,
            "image_url": _first_prefetched_image_url(post.images.all()),
            "request_count": len(request_items),
            "pending_request_count": sum(
                1 for item in request_items if item["status_key"] == "pending"
            ),
            "requests": request_items,
            "request_panel_id": request_panel_id,
        })

    for post in missing_posts:
        profile_posts.append({
            "id": post.id,
            "post_type": "missing",
            "post_type_label": "Missing",
            "title": post.dog_name,
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
    profile_posts = profile_posts[:recent_post_limit]

    staff_adopt_requests = list(
        PostRequest.objects.filter(
            user=profile_user,
            request_type="adopt",
            status="accepted",
        )
        .select_related("post")
        .prefetch_related("post__images")
        .order_by("-created_at")[:recent_post_limit]
    )
    user_adopt_requests = list(
        UserAdoptionRequest.objects.filter(
            requester=profile_user,
            status="approved",
        )
        .select_related("post", "post__owner")
        .prefetch_related("post__images")
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
    adopted_posts = adopted_posts[:recent_post_limit]

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
    incoming_requests_total = UserAdoptionRequest.objects.filter(post__owner=profile_user).count()
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
    registered_dogs_total = Dog.objects.filter(owner_user=profile_user).count()
    registered_dogs = _build_registered_dog_payloads(registered_dogs_qs)

    user_citations = (
        Citation.objects.filter(owner=profile_user)
        .select_related("penalty", "penalty__section")
        .prefetch_related("penalties", "penalties__section")
        .order_by("-date_issued", "-id")
    )
    user_violation_count = 0
    user_violation_records = []
    for citation in user_citations:
        penalties = list(citation.penalties.all())
        if not penalties and citation.penalty_id:
            penalties = [citation.penalty]

        # Count citation tickets, not individual penalties, for the profile total.
        user_violation_count += 1
        violation_labels = [
            f"Sec. {penalty.section.number} #{penalty.number} - {penalty.title}"
            for penalty in penalties
        ]
        total_amount = sum((penalty.amount for penalty in penalties), 0)

        user_violation_records.append(
            {
                "citation_id": citation.id,
                "date_issued": citation.date_issued,
                "violations": violation_labels,
                "violation_count": len(penalties),
                "total_amount": total_amount,
                "remarks": (citation.remarks or "").strip(),
            }
        )

    return {
        "profile_user": profile_user,
        "profile": profile,
        "profile_posts": profile_posts,
        "profile_posts_limit": recent_post_limit,
        "adopted_posts": adopted_posts,
        "adopted_posts_limit": recent_post_limit,
        "incoming_requests": incoming_requests,
        "incoming_requests_limit": incoming_requests_limit,
        "incoming_requests_total": incoming_requests_total,
        "registered_dogs": registered_dogs,
        "registered_dogs_limit": registered_dogs_limit,
        "registered_dogs_total": registered_dogs_total,
        "user_violation_count": user_violation_count,
        "user_violation_records": user_violation_records,
    }

# =============================================================================
# Shared authentication, onboarding, and profile utilities
# =============================================================================

def user_only(view_func):
    """Allow only authenticated non-staff users to access a view."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('user:login')
        if request.user.is_staff:
            return redirect('dogadoption_admin:post_list')  # admin goes to admin dashboard
        return view_func(request, *args, **kwargs)

    return wrapper


def login_view(request):
    """Authenticate a user and redirect staff accounts to the admin app."""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("dogadoption_admin:post_list")
        return redirect("user:user_home")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if user.is_staff:
                login(request, user)
                response = redirect("dogadoption_admin:post_list")
                response.set_cookie("admin_sessionid", request.session.session_key)
                return response

            login(request, user)
            response = redirect("user:user_home")
            response.delete_cookie("admin_sessionid")
            return response

        return _render_home_with_auth_modal(
            request,
            "login",
            login_error="Invalid username or password",
            login_form_data={"username": username or ""},
        )

    return _render_home_with_auth_modal(request, "login")


def logout_view(request):
    """Log out the current session and clear any admin session cookie."""
    logout(request)
    response = redirect("user:login")
    response.delete_cookie("admin_sessionid")
    return response


@require_POST
@user_only
def mark_notifications_seen(request):
    """Mark the latest user notifications as seen for the current session."""
    request.session[USER_NOTIFICATIONS_SEEN_SESSION_KEY] = timezone.now().isoformat()
    request.session.modified = True
    return JsonResponse({"ok": True, "unread_count": 0})


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


def _normalize_dog_request_type(value):
    request_type = (value or "").strip().lower()
    return request_type if request_type in {"capture", "surrender"} else "capture"


def _normalize_dog_request_submission_type(value):
    submission_type = (value or "").strip().lower()
    return submission_type if submission_type in {"walk_in", "online"} else ""


def _derive_dog_request_submission_type(
    request_type,
    raw_submission_type,
    *,
    appointment_date_raw="",
    latitude_raw="",
    longitude_raw="",
    barangay="",
):
    submission_type = _normalize_dog_request_submission_type(raw_submission_type)
    if submission_type:
        return submission_type

    if (appointment_date_raw or "").strip():
        return "walk_in"

    if (latitude_raw or "").strip() or (longitude_raw or "").strip() or _clean_barangay(barangay):
        return "online"

    return ""


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


def _split_time_left(diff):
    total_seconds = max(int(diff.total_seconds()), 0)
    days = total_seconds // 86400
    remainder = total_seconds % 86400
    hours = remainder // 3600
    remainder = remainder % 3600
    minutes = remainder // 60
    return days, hours, minutes


def _post_phase_payload(post):
    phase = post.current_phase() if hasattr(post, "current_phase") else "closed"
    days = hours = minutes = 0
    if phase in {"claim", "adopt"}:
        days, hours, minutes = _split_time_left(post.time_left())
    return phase, days, hours, minutes


def _base_public_post_queryset():
    return Post.objects.select_related(
        "user", "user__profile"
    ).prefetch_related("images").order_by("-created_at")


def _base_user_adoption_post_queryset():
    return UserAdoptionPost.objects.select_related(
        "owner", "owner__profile"
    ).prefetch_related("images").order_by("-created_at")


def _filter_public_posts(posts_qs, listing_mode, filter_type):
    now = timezone.now()
    post_table = Post._meta.db_table
    active_statuses = ["rescued", "under_care"]

    claim_deadline_expr = RawSQL(
        f"DATE_ADD({post_table}.created_at, INTERVAL {post_table}.claim_days DAY)",
        [],
        output_field=DateTimeField(),
    )
    adopt_deadline_expr = RawSQL(
        f"DATE_ADD(DATE_ADD({post_table}.created_at, INTERVAL {post_table}.claim_days DAY), INTERVAL %s DAY)",
        [Post.ADOPTION_DAYS],
        output_field=DateTimeField(),
    )

    if listing_mode == "claim":
        allowed_filters = {"all", "ready_claim", "reunited"}
        if filter_type not in allowed_filters:
            filter_type = "all"

        if filter_type in {"all", "ready_claim"}:
            posts_qs = posts_qs.annotate(claim_deadline_db=claim_deadline_expr)

        if filter_type == "ready_claim":
            posts_qs = posts_qs.filter(
                status__in=active_statuses,
                claim_deadline_db__gte=now,
            )
        elif filter_type == "reunited":
            posts_qs = posts_qs.filter(status="reunited")
        else:
            posts_qs = posts_qs.filter(
                Q(status="reunited")
                | (
                    Q(status__in=active_statuses)
                    & Q(claim_deadline_db__gte=now)
                )
            )
        return posts_qs, filter_type

    allowed_filters = {"all", "ready_adopt", "adopted"}
    if filter_type not in allowed_filters:
        filter_type = "all"

    if filter_type in {"all", "ready_adopt"}:
        posts_qs = posts_qs.annotate(
            claim_deadline_db=claim_deadline_expr,
            adopt_deadline_db=adopt_deadline_expr,
        )

    if filter_type == "ready_adopt":
        posts_qs = posts_qs.filter(
            status__in=active_statuses,
            claim_deadline_db__lt=now,
            adopt_deadline_db__gte=now,
        )
    elif filter_type == "adopted":
        posts_qs = posts_qs.filter(status="adopted")
    else:
        posts_qs = posts_qs.filter(
            Q(status="adopted")
            | (
                Q(status__in=active_statuses)
                & Q(claim_deadline_db__lt=now)
                & Q(adopt_deadline_db__gte=now)
            )
        )

    return posts_qs, filter_type


def _filter_user_adoption_posts(posts_qs, filter_type):
    allowed_filters = {"all", "ready_adopt", "adopted"}
    if filter_type not in allowed_filters:
        filter_type = "all"

    if filter_type == "ready_adopt":
        posts_qs = posts_qs.filter(status="available")
    elif filter_type == "adopted":
        posts_qs = posts_qs.filter(status="adopted")

    return posts_qs, filter_type


def _build_public_post_listing(request, listing_mode):
    """Build listing data for the public claim/adopt browse screens."""
    filter_type = request.GET.get("filter", "all")
    request_type = "claim" if listing_mode == "claim" else "adopt"
    nav_tabs = [
        {"key": "all", "label": "All"},
        {"key": "ready_claim", "label": "Ready to Claim"},
        {"key": "reunited", "label": "Reclaimed"},
    ] if listing_mode == "claim" else [
        {"key": "all", "label": "All"},
        {"key": "ready_adopt", "label": "Ready to Adopt"},
        {"key": "adopted", "label": "Adopted"},
    ]
    page_title = "Dogs for Claim" if listing_mode == "claim" else "Dogs for Adoption"

    if listing_mode == "claim":
        page_number = request.GET.get("page", 1)
        posts_qs, filter_type = _filter_public_posts(
            _base_public_post_queryset(),
            listing_mode,
            filter_type,
        )
        page_obj = Paginator(posts_qs, 12).get_page(page_number)
        post_items = []
        for post in page_obj.object_list:
            phase, days, hours, minutes = _post_phase_payload(post)
            post_items.append({
                "post": post,
                "phase": phase,
                "days_left": days,
                "hours_left": hours,
                "minutes_left": minutes,
                "main_image_url": _first_prefetched_image_url(post.images.all()),
            })

        return {
            "posts": post_items,
            "current_filter": filter_type,
            "page_obj": page_obj,
            "listing_mode": listing_mode,
            "nav_tabs": nav_tabs,
            "page_title": page_title,
            "status_page_url": reverse(_request_history_route_name(request_type)),
            "status_page_label": "My Claim Requests",
            "pending_request_count": PostRequest.objects.filter(
                user=request.user,
                request_type=request_type,
                status="pending",
            ).count(),
        }

    source_type = request.GET.get("source", "all")
    source_tabs = [
        {"key": "all", "label": "All Posts"},
        {"key": "staff", "label": "Staff Posts"},
        {"key": "user", "label": "User Posts"},
    ]
    if source_type not in {tab["key"] for tab in source_tabs}:
        source_type = "all"

    show_staff_posts = source_type in {"all", "staff"}
    show_user_posts = source_type in {"all", "user"}
    items_per_page = 6 if source_type == "all" else 12

    staff_page_obj = None
    staff_items = []
    if show_staff_posts:
        staff_page_number = request.GET.get("staff_page", 1)
        staff_qs, filter_type = _filter_public_posts(
            _base_public_post_queryset(),
            listing_mode,
            filter_type,
        )
        staff_page_obj = Paginator(staff_qs, items_per_page).get_page(staff_page_number)
        for post in staff_page_obj.object_list:
            phase, days, hours, minutes = _post_phase_payload(post)
            staff_items.append({
                "post": post,
                "phase": phase,
                "days_left": days,
                "hours_left": hours,
                "minutes_left": minutes,
                "main_image_url": _first_prefetched_image_url(post.images.all()),
                "source_type": "staff",
            })
    else:
        _, filter_type = _filter_user_adoption_posts(
            _base_user_adoption_post_queryset(),
            filter_type,
        )

    user_page_obj = None
    user_items = []
    if show_user_posts:
        user_page_number = request.GET.get("user_page", 1)
        user_qs, filter_type = _filter_user_adoption_posts(
            _base_user_adoption_post_queryset(),
            filter_type,
        )
        user_page_obj = Paginator(user_qs, items_per_page).get_page(user_page_number)
        for post in user_page_obj.object_list:
            user_items.append({
                "post": post,
                "main_image_url": _first_prefetched_image_url(post.images.all()),
                "owner_name": post.owner.get_full_name() or post.owner.username,
                "owner_profile_url": _build_profile_destination_url(
                    request,
                    post.owner_id,
                    next_url=request.get_full_path(),
                    back_label="Back to Adoption List",
                ),
                "source_type": "user",
            })

    pending_request_count = (
        PostRequest.objects.filter(
            user=request.user,
            request_type=request_type,
            status="pending",
        ).count()
        + UserAdoptionRequest.objects.filter(
            requester=request.user,
            status="pending",
        ).count()
    )

    return {
        "posts": staff_items if source_type != "user" else user_items,
        "current_filter": filter_type,
        "listing_mode": listing_mode,
        "nav_tabs": nav_tabs,
        "page_title": page_title,
        "status_page_url": reverse(_request_history_route_name(request_type)),
        "status_page_label": "My Adoption Requests",
        "pending_request_count": pending_request_count,
        "current_source": source_type,
        "source_tabs": source_tabs,
        "show_staff_posts": show_staff_posts,
        "show_user_posts": show_user_posts,
        "staff_posts": staff_items,
        "staff_page_obj": staff_page_obj,
        "user_posts": user_items,
        "user_page_obj": user_page_obj,
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


def _get_available_appointment_dates():
    return GlobalAppointmentDate.objects.filter(
        is_active=True,
        appointment_date__gte=timezone.localdate(),
    ).order_by("appointment_date")


def _render_confirm_page(request, template_name, post, available_dates, request_type=None):
    """Render a reusable confirmation page for claim/adoption requests."""
    cancel_url = reverse(_public_listing_route_name(request_type)) if request_type else reverse("user:user_home")
    status_url = reverse(_request_history_route_name(request_type)) if request_type else reverse("user:user_home")
    return render(request, template_name, {
        "post": post,
        "available_dates": available_dates,
        "cancel_url": cancel_url,
        "status_url": status_url,
    })


def _request_history_route_name(request_type):
    return "user:my_claims" if request_type == "claim" else "user:adopt_status"


def _public_listing_route_name(request_type):
    return "user:claim_list" if request_type == "claim" else "user:adopt_list"


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


def _create_post_request_with_images(request, post, request_type, appointment_date):
    req = PostRequest.objects.create(
        user=request.user,
        post=post,
        request_type=request_type,
        status="pending",
        appointment_date=appointment_date,
    )
    for img in request.FILES.getlist("images"):
        ClaimImage.objects.create(claim=req, image=img)
    return req


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
    post = get_object_or_404(Post, id=post_id)
    available_dates = _get_available_appointment_dates()
    history_url = _request_history_route_name(request_type)
    listing_url = _public_listing_route_name(request_type)

    if post.status in ["reunited", "adopted"]:
        messages.warning(request, "This dog is no longer available.")
        return redirect(listing_url)

    if not is_open_fn(post):
        messages.warning(request, not_open_message)
        return redirect(listing_url)

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
        messages.success(request, success_message)
        return redirect(history_url)

    return _render_confirm_page(request, template_name, post, available_dates, request_type)


def _user_post_requests(user, request_type):
    return PostRequest.objects.filter(
        user=user,
        request_type=request_type,
    ).select_related("post").order_by("-created_at")


FEED_CACHE_TTL_SECONDS = 90
FEED_CACHE_VERSION = "v5"
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
SEARCH_CACHE_TTL_SECONDS = 90
SEARCH_MAX_QUERY_LENGTH = 80


def _normalized_feed_query(raw_query):
    return " ".join((raw_query or "").strip().split())


def _normalized_search_query(raw_query):
    return _normalized_feed_query(raw_query)[:SEARCH_MAX_QUERY_LENGTH]


def _pagination_query_without_page(querydict):
    params = querydict.copy()
    params.pop("page", None)
    return params.urlencode()


def _feed_cache_key(prefix, query, feed_token=""):
    namespace = get_user_home_feed_namespace()
    query_hash = hashlib.md5(query.encode("utf-8")).hexdigest() if query else "all"
    token_hash = hashlib.md5(feed_token.encode("utf-8")).hexdigest() if feed_token else "default"
    return f"user_home:{prefix}:{FEED_CACHE_VERSION}:{namespace}:{query_hash}:{token_hash}"


def _normalized_feed_token(raw_token):
    return (raw_token or "").strip()[:64]


def _fresh_feed_token():
    return secrets.token_hex(8)


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


def _active_admin_candidate_ids_with_cache(query):
    cache_key = _feed_cache_key("active_admin_candidate_ids", query)
    cached_ids = cache.get(cache_key)
    if cached_ids is not None:
        return cached_ids

    accepted_post_ids = PostRequest.objects.filter(
        status="accepted",
        request_type__in=["claim", "adopt"],
    ).values("post_id")

    admin_qs = Post.objects.exclude(status__in=["reunited", "adopted"]).exclude(id__in=accepted_post_ids)
    if query:
        admin_qs = admin_qs.filter(
            Q(caption__icontains=query)
            | Q(location__icontains=query)
            | Q(status__icontains=query)
        )

    admin_candidates = list(admin_qs.order_by("-created_at")[:FEED_ADMIN_CANDIDATE_LIMIT])
    active_ids = [
        post.id for post in admin_candidates if post.current_phase() in {"claim", "adopt"}
    ]
    cache.set(cache_key, active_ids, FEED_CACHE_TTL_SECONDS)
    return active_ids


def _build_random_home_rows(query, feed_token="", dogs_only=False):
    feed_scope = "dogs_only" if dogs_only else "mixed"
    mixed_cache_key = _feed_cache_key(f"{feed_scope}_rows", query, feed_token)
    cached_rows = cache.get(mixed_cache_key)
    if cached_rows is not None:
        return cached_rows

    active_admin_candidate_ids = _active_admin_candidate_ids_with_cache(query)
    announcement_qs = DogAnnouncement.objects.all()
    user_qs = UserAdoptionPost.objects.filter(status="available")
    missing_qs = MissingDogPost.objects.filter(status="missing")

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
        )
        missing_qs = missing_qs.filter(
            Q(dog_name__icontains=query)
            | Q(description__icontains=query)
            | Q(location__icontains=query)
        )

    admin_ids = _sample_ids_with_cache(
        _feed_cache_key(f"{feed_scope}_admin_ids", query),
        active_admin_candidate_ids,
        sample_limit=FEED_ADMIN_SAMPLE_LIMIT,
    )
    announcement_ids = []
    if not dogs_only:
        announcement_ids = _sample_recent_ids_with_cache(
            _feed_cache_key(f"{feed_scope}_announcement_ids", query),
            announcement_qs,
            candidate_limit=FEED_ANNOUNCEMENT_CANDIDATE_LIMIT,
            sample_limit=FEED_ANNOUNCEMENT_SAMPLE_LIMIT,
        )
    user_ids = _sample_recent_ids_with_cache(
        _feed_cache_key(f"{feed_scope}_user_ids", query),
        user_qs,
        candidate_limit=FEED_USER_CANDIDATE_LIMIT,
        sample_limit=FEED_USER_SAMPLE_LIMIT,
    )
    missing_ids = _sample_recent_ids_with_cache(
        _feed_cache_key(f"{feed_scope}_missing_ids", query),
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


def _build_search_rows_cache_key(query, dogs_only):
    prefix = "search_dogs_only" if dogs_only else "search_mixed"
    return _feed_cache_key(f"{prefix}:keyword_only", query)


def _build_search_home_rows(query, dogs_only=False):
    has_filters = bool(query)
    if not has_filters:
        return []

    cache_key = _build_search_rows_cache_key(query, dogs_only)
    cached_rows = cache.get(cache_key)
    if cached_rows is not None:
        return cached_rows

    accepted_post_ids = PostRequest.objects.filter(
        status="accepted",
        request_type__in=["claim", "adopt"],
    ).values("post_id")

    admin_qs = Post.objects.exclude(status__in=["reunited", "adopted"]).exclude(id__in=accepted_post_ids)
    announcement_qs = DogAnnouncement.objects.all()
    user_qs = UserAdoptionPost.objects.filter(status="available")
    missing_qs = MissingDogPost.objects.filter(status="missing")

    if query:
        admin_filters = (
            Q(caption__icontains=query)
            | Q(location__icontains=query)
            | Q(status__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
        )
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

        admin_qs = admin_qs.filter(admin_filters)
        announcement_qs = announcement_qs.filter(announcement_filters)
        user_qs = user_qs.filter(user_filters)
        missing_qs = missing_qs.filter(missing_filters)

    admin_rows = list(
        admin_qs.order_by("-created_at").values("id", "created_at")[:SEARCH_CANDIDATE_LIMIT]
    )
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


def _hydrate_home_feed_items(request, feed_rows):
    ids_by_type = {
        "admin": [row["id"] for row in feed_rows if row["feed_type"] == "admin"],
        "announcement": [row["id"] for row in feed_rows if row["feed_type"] == "announcement"],
        "user": [row["id"] for row in feed_rows if row["feed_type"] == "user"],
        "missing": [row["id"] for row in feed_rows if row["feed_type"] == "missing"],
    }

    admin_map = {
        post.id: post
        for post in Post.objects.select_related(
            "user", "user__profile"
        ).prefetch_related("images").filter(id__in=ids_by_type["admin"])
    }
    announcement_user_reaction_subquery = AnnouncementReaction.objects.filter(
        announcement_id=OuterRef("pk"),
        user_id=getattr(request.user, "id", None),
    )
    announcement_map = {
        post.id: post
        for post in DogAnnouncement.objects.select_related(
            "created_by", "created_by__profile"
        ).annotate(
            reaction_count=Count("reactions", distinct=True),
            user_reacted=Exists(announcement_user_reaction_subquery),
        ).prefetch_related("images").filter(id__in=ids_by_type["announcement"])
    }
    user_map = {
        post.id: post
        for post in UserAdoptionPost.objects.select_related(
            "owner", "owner__profile"
        ).annotate(
            request_count=Count("requests", distinct=True),
        ).prefetch_related("images").filter(id__in=ids_by_type["user"])
    }
    missing_map = {
        post.id: post
        for post in MissingDogPost.objects.select_related(
            "owner", "owner__profile"
        ).filter(id__in=ids_by_type["missing"])
    }

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
            image_queryset = p.images.all()
            image_count = len(image_queryset)
            main_image = next(iter(image_queryset), None)

            phase, days, hours, minutes = _post_phase_payload(p)
            is_open_for_adoption = phase in ["claim", "adopt"]

            deadline = None
            if phase == "claim":
                deadline = p.claim_deadline()
            elif phase == "adopt":
                deadline = p.adoption_deadline()

            combined_posts.append({
                "post": p,
                "post_type": "admin",
                "author_avatar_url": _profile_image_url_or_default(
                    p.user, default_admin_avatar_url
                ),
                "days_left": days,
                "hours_left": hours,
                "minutes_left": minutes,
                "is_open_for_adoption": is_open_for_adoption,
                "phase": phase,
                "posted_label": _format_posted_label(p.created_at),
                "deadline_iso": deadline.isoformat() if deadline else "",
                "image_count": image_count,
                "main_image": main_image,
            })
            continue

        if post_type == "announcement":
            p = announcement_map.get(post_id)
            if not p:
                continue
            announcement_images = p.images.all()
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
                "reaction_count": getattr(p, "reaction_count", 0),
                "user_reacted": bool(getattr(p, "user_reacted", False)),
                "share_url": request.build_absolute_uri(
                    reverse("user:announcement_share_preview", args=[p.id])
                ),
            })
            continue

        if post_type == "user":
            p = user_map.get(post_id)
            if not p:
                continue
            post_images = p.images.all()
            main_image = next(iter(post_images), None)
            profile_url = _build_profile_destination_url(
                request,
                p.owner_id,
                next_url=profile_return_url,
                back_label=profile_back_label,
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
                "main_image": main_image,
                "request_count": getattr(p, "request_count", 0),
                "author_name": p.owner.get_full_name() or p.owner.username,
                "author_avatar_url": _profile_image_url_or_default(
                    p.owner,
                    default_profile_avatar_url,
                ),
                "author_profile_url": profile_url,
                "owner_request_url": f"{reverse('user:edit_profile')}#post-requests-{p.id}",
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
    barangays = list(Barangay.objects.filter(is_active=True).values_list("name", flat=True))
    return JsonResponse({"barangays": barangays})


def signup_view(request):
    """Handle the first step of signup before face-auth enrollment."""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("dogadoption_admin:post_list")
        return redirect("user:user_home")

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        raw_barangay = request.POST.get("address")
        barangay = _resolve_barangay_name(request.POST.get("address"))
        signup_form_data = {
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "address": _clean_barangay(raw_barangay),
        }

        if not username:
            return _render_home_with_auth_modal(
                request,
                "signup",
                signup_error="Username is required.",
                signup_form_data=signup_form_data,
            )

        if User.objects.filter(username__iexact=username).exists():
            return _render_home_with_auth_modal(
                request,
                "signup",
                signup_error="Username already exists",
                signup_form_data=signup_form_data,
            )

        if password != confirm_password:
            return _render_home_with_auth_modal(
                request,
                "signup",
                signup_error="Passwords do not match.",
                signup_form_data=signup_form_data,
            )

        try:
            temp_user = User(username=username, first_name=request.POST.get("first_name"), last_name=request.POST.get("last_name"))
            validate_password(password, user=temp_user)
        except ValidationError as exc:
            return _render_home_with_auth_modal(
                request,
                "signup",
                signup_error=" ".join(exc.messages),
                signup_form_data=signup_form_data,
            )

        if not barangay:
            return _render_home_with_auth_modal(
                request,
                "signup",
                signup_error="Please select a valid barangay from the suggestions.",
                signup_form_data=signup_form_data,
            )

        # SAVE DATA TEMPORARILY (SESSION)
        request.session["signup_data"] = {
            "username": username,
            "password": password,
            "first_name": first_name,
            "last_name": last_name,
            "middle_initial": "",
            "address": barangay,
            "age": 18,
        }

        # GO TO FACE AUTH STEP
        return redirect("user:face_auth")

    return _render_home_with_auth_modal(request, "signup")

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


@csrf_exempt
def face_auth(request):
    """Render the face-auth capture step during signup."""
    if "signup_data" not in request.session:
        return redirect("user:signup")
    return render(request, "face_auth.html")

@csrf_exempt
def save_face(request):
    """Persist captured signup face images into temporary storage."""
    if request.method != "POST":
        return JsonResponse({"status": "error"}, status=400)

    if "signup_data" not in request.session:
        return JsonResponse({"status": "error", "message": "Signup step missing"}, status=400)

    data = json.loads(request.body.decode("utf-8"))
    images = data.get("images", [])

    if not images or len(images) < 3:
        return JsonResponse({"status": "error", "message": "At least 3 images required"}, status=400)

    temp_dir = os.path.join(settings.MEDIA_ROOT, "temp_faces")
    os.makedirs(temp_dir, exist_ok=True)
    saved_files = []

    for idx, img_data in enumerate(images):
        if ";base64," not in img_data:
            continue
        format, imgstr = img_data.split(";base64,")
        filename = f"{request.session['signup_data']['username']}_{idx}.png"
        filepath = os.path.join(temp_dir, filename)
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(imgstr))
        saved_files.append(f"temp_faces/{filename}")

    request.session["face_images_files"] = saved_files
    return JsonResponse({"status": "ok"})

def signup_complete(request):
    """Create the user account after signup and face-auth capture succeed."""
    if "signup_data" not in request.session or "face_images_files" not in request.session:
        return redirect("user:signup")

    data = request.session["signup_data"]
    images_files = request.session["face_images_files"]

    # Create user
    user = User.objects.create_user(
        username=data["username"],
        password=data["password"],
        first_name=data["first_name"],
        last_name=data["last_name"]
    )

    # Create profile
    profile = Profile.objects.create(
        user=user,
        middle_initial=data.get("middle_initial", ""),
        address=data.get("address", ""),
        age=data.get("age", 18),
        consent_given=True,
        profile_image=_ensure_default_profile_image_exists(),
    )

    # Move temp images into FaceImage model
    for path in images_files:
        full_path = os.path.join(settings.MEDIA_ROOT, path)
        with open(full_path, "rb") as f:
            FaceImage.objects.create(
                user=user,
                image=ContentFile(f.read(), name=os.path.basename(path))
            )
        # Remove temp file
        os.remove(full_path)

    # Clear session
    request.session.pop("signup_data", None)
    request.session.pop("face_images_files", None)

    messages.success(request, "Account created successfully. Please log in.")
    return redirect("user:login")

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
    adoption_form = adoption_form or UserAdoptionPostForm()
    missing_form = missing_form or MissingDogPostForm()
    query = _normalized_feed_query(request.GET.get("q"))
    feed_token = _normalized_feed_token(request.GET.get("feed_token")) or _fresh_feed_token()
    page_number = request.GET.get("page", 1)
    show_dogs_only = request.user.is_authenticated and not request.user.is_staff
    mixed_rows = _build_random_home_rows(query, feed_token=feed_token, dogs_only=show_dogs_only)

    paginator = Paginator(mixed_rows, FEED_POSTS_PER_PAGE)
    page_obj = paginator.get_page(page_number)
    feed_rows = list(page_obj.object_list)
    combined_posts = _hydrate_home_feed_items(request, feed_rows)
    pagination_params = request.GET.copy()
    pagination_params["feed_token"] = feed_token
    pagination_params.pop("page", None)

    return {
        "posts": combined_posts,
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
        **extra_context,
    })
    return render(request, "home/user_home.html", context)


def user_home(request):
    """Render the mixed public feed and handle quick post creation from home."""
    # Redirect staff to admin dashboard
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('dogadoption_admin:post_list')

    selected_type = request.GET.get("type", "adoption")
    adoption_form = _build_user_adoption_post_form()
    missing_form = _build_missing_dog_post_form()
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

    return render(request, "home/user_home.html", _build_user_home_context(
        request,
        selected_type=selected_type,
        adoption_form=adoption_form,
        missing_form=missing_form,
        open_create_modal=open_create_modal,
    ))


def home_search(request):
    """Search the public home feed across staff and user-created posts."""
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("dogadoption_admin:post_list")

    query = _normalized_search_query(request.GET.get("q"))
    search_performed = bool(query)
    show_dogs_only = request.user.is_authenticated and not request.user.is_staff
    search_rows = _build_search_home_rows(
        query=query,
        dogs_only=show_dogs_only,
    )

    paginator = Paginator(search_rows, SEARCH_RESULTS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    posts = _hydrate_home_feed_items(request, list(page_obj.object_list))
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


@user_only
def adopt_user_post(request, post_id):
    """Submit an adoption request for a user-created adoption post."""
    post = get_object_or_404(UserAdoptionPost, id=post_id)

    if post.owner == request.user:
        messages.info(request, "You cannot request adoption for your own post.")
        return redirect('user:user_home')

    if post.status != "available":
        messages.warning(request, "This dog is no longer available.")
        return redirect("user:user_home")

    if request.method == "POST":
        _, created = UserAdoptionRequest.objects.get_or_create(
            post=post,
            requester=request.user,
        )

        if created:
            invalidate_user_notification_payload(post.owner_id)
            messages.success(request, "Adoption request submitted successfully.")
        else:
            messages.info(request, "You already submitted an adoption request for this post.")
        return redirect('user:user_home')

    return render(request, "adopt/adopt_user_confirm.html", {
        "post": post,
    })


@user_only
def user_adoption_requests(request):
    """List requests received on adoption posts owned by the current user."""
    requests = UserAdoptionRequest.objects.filter(
        post__owner=request.user
    ).select_related("post", "requester", "requester__profile").order_by("-created_at")

    return render(request, "adopt/user_post_requests.html", {
        "requests": requests,
    })


@user_only
def user_adoption_request_action(request, req_id, action):
    """Accept or decline an incoming request on a user-created adoption post."""
    req = get_object_or_404(
        UserAdoptionRequest,
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

@user_only
def post_detail(request, post_id):
    """Render a post detail page used by shared or linked home posts."""
    post = get_object_or_404(Post, id=post_id)
    return render(request, 'home/post_detail.html', {'post': post})


# =============================================================================
# Navigation 2/5: Request
# Covers dog-capture request submission, editing, and deletion.
# =============================================================================

@user_only
def request_dog_capture(request):
    """Create and list dog-capture requests for the current user."""
    available_dates = _get_available_appointment_dates()
    if request.method == 'POST':
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

        # Step 2: contact details
        phone_number = _normalize_ph_phone_number(request.POST.get('phone_number'))
        request_type = _normalize_dog_request_type(request.POST.get('request_type'))
        appointment_date_raw = (request.POST.get('appointment_date') or '').strip()

        # Basic server-side validation to mirror frontend constraints.
        if not phone_number:
            messages.error(
                request,
                "Please enter a valid Philippine mobile number, such as 0917 123 4567 or +63 917 123 4567.",
            )
            return redirect('user:dog_capture_request')


        # Persist the latest contact number so staff can reach the requester quickly.
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            profile = Profile.objects.create(
                user=request.user,
                address="",
                age=18,
                consent_given=True,
            )

        profile_fields_to_update = []
        profile.phone_number = phone_number
        profile_fields_to_update.append("phone_number")
        if profile_fields_to_update:
            profile.save(update_fields=profile_fields_to_update)

        # Keep a valid capture reason internally while removing the visible selector in the UI.
        reason = (request.POST.get('reason') or 'stray').strip()
        if not _is_valid_capture_reason(reason):
            reason = 'stray'
        description = (request.POST.get('description') or '').strip()
        latitude_raw = (request.POST.get('latitude') or '').strip()
        longitude_raw = (request.POST.get('longitude') or '').strip()
        submission_type = _derive_dog_request_submission_type(
            request_type,
            request.POST.get('submission_type'),
            appointment_date_raw=appointment_date_raw,
            latitude_raw=latitude_raw,
            longitude_raw=longitude_raw,
            barangay=request.POST.get('barangay'),
        )

        if not submission_type:
            messages.error(request, "Please choose how you want to submit this request.")
            return redirect('user:dog_capture_request')

        preferred_appointment_date = None
        if submission_type == 'walk_in':
            preferred_appointment_date = parse_date(appointment_date_raw) if appointment_date_raw else None
            if not preferred_appointment_date:
                messages.error(request, "Please select an available appointment date for this walk-in request.")
                return redirect('user:dog_capture_request')
            if not available_dates.filter(appointment_date=preferred_appointment_date).exists():
                messages.error(request, "Selected appointment date is not available.")
                return redirect('user:dog_capture_request')

        location_mode = (request.POST.get('location_mode') or 'exact').strip().lower()
        if location_mode not in {'exact', 'manual'}:
            location_mode = 'exact'

        barangay = _clean_barangay(request.POST.get('barangay'))
        city = _clean_barangay(request.POST.get('city')) or DEFAULT_REQUEST_CITY
        manual_full_address = " ".join(
            (request.POST.get('manual_full_address') or '').split()
        ).strip()
        location_landmark_images = list(request.FILES.getlist('location_landmark_image'))

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
                    return redirect('user:dog_capture_request')

        if submission_type == 'online' and location_mode == 'manual':
            resolved_barangay = _resolve_barangay_name(barangay)
            if not resolved_barangay:
                messages.error(request, "Please choose a valid barangay from the list.")
                return redirect('user:dog_capture_request')
            barangay = resolved_barangay
            latitude_value = None
            longitude_value = None
        elif submission_type == 'online':
            if not latitude_raw or not longitude_raw:
                messages.error(request, "Please capture your exact GPS location first.")
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

            latitude_value = f"{latitude_val:.6f}"
            longitude_value = f"{longitude_val:.6f}"
            manual_full_address = ""
            location_landmark_images = []

            if not barangay:
                try:
                    profile_barangay = _clean_barangay(request.user.profile.address)
                except Profile.DoesNotExist:
                    profile_barangay = ""
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
            preferred_appointment_date=preferred_appointment_date,
            reason=reason,
            description=description or None,
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

    rows_per_page = 5
    valid_tabs = {"scheduled", "pending", "declined", "captured"}
    active_status_tab = (request.GET.get("status_tab") or "scheduled").strip().lower()
    if active_status_tab not in valid_tabs:
        active_status_tab = "scheduled"

    status_totals = {
        row["status"]: row["total"]
        for row in DogCaptureRequest.objects.filter(
            requested_by=request.user
        ).values("status").annotate(total=Count("id"))
    }

    def _paginate_status(status_key, page_param):
        page_obj = Paginator(
            DogCaptureRequest.objects.filter(
                requested_by=request.user,
                status=status_key,
            ).prefetch_related("images", "landmark_images").order_by("-created_at"),
            rows_per_page,
        ).get_page(request.GET.get(page_param, 1))
        return page_obj, list(page_obj.object_list)

    accepted_page_obj, accepted_requests = _paginate_status("accepted", "scheduled_page")
    pending_page_obj, pending_requests = _paginate_status("pending", "pending_page")
    declined_page_obj, declined_requests = _paginate_status("declined", "declined_page")
    captured_page_obj, captured_requests = _paginate_status("captured", "captured_page")

    # Pre-fill Step 2 contact fields from the user's profile for a smoother UX.
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        profile = None

    initial_phone_number = (
        _format_ph_phone_number(profile.phone_number)
        if profile and profile.phone_number
        else ""
    )
    return render(request, 'user_request/request.html', {
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
        'initial_phone_number': initial_phone_number,
        'default_manual_city': DEFAULT_REQUEST_CITY,
        'available_dates': available_dates,
    })




@user_only
@require_POST
def edit_dog_capture_request(request, req_id):
    """Edit a pending dog-capture request submitted by the current user."""
    req = get_object_or_404(
        DogCaptureRequest,
        id=req_id,
        requested_by=request.user,
    )

    # User can only update requests that are still waiting for admin action.
    if req.status != 'pending':
        messages.warning(request, "Only pending requests can be edited.")
        return redirect('user:dog_capture_request')

    available_dates = _get_available_appointment_dates()
    reason = (request.POST.get('reason') or req.reason or 'stray').strip()
    if not _is_valid_capture_reason(reason):
        reason = 'stray'
    description = (request.POST.get('description') or '').strip()
    request_type = _normalize_dog_request_type(request.POST.get('request_type') or req.request_type)
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
    remove_landmark_ids = set()
    for raw_id in raw_remove_landmark_ids:
        try:
            remove_landmark_ids.add(int(raw_id))
        except (TypeError, ValueError):
            continue
    # Support both the main request form field name and the edit-modal field name.
    location_mode = (
        request.POST.get('location_mode')
        or request.POST.get('edit_location_mode')
        or ''
    ).strip().lower()

    # Fallback keeps old submissions compatible when mode is not sent.
    if location_mode not in {'exact', 'manual'}:
        location_mode = 'exact' if (latitude_raw or longitude_raw) else 'manual'

    appointment_date_raw = (request.POST.get('appointment_date') or '').strip()
    submission_type = _derive_dog_request_submission_type(
        request_type,
        request.POST.get('submission_type') or req.submission_type,
        appointment_date_raw=appointment_date_raw,
        latitude_raw=latitude_raw,
        longitude_raw=longitude_raw,
        barangay=barangay,
    )

    if not submission_type:
        messages.error(request, "Please choose how you want to submit this request.")
        return redirect('user:dog_capture_request')

    preferred_appointment_date = None
    if submission_type == 'walk_in':
        preferred_appointment_date = parse_date(appointment_date_raw) if appointment_date_raw else None
        if not preferred_appointment_date:
            messages.error(request, "Please select an available appointment date for this walk-in request.")
            return redirect('user:dog_capture_request')
        if not available_dates.filter(appointment_date=preferred_appointment_date).exists():
            messages.error(request, "Selected appointment date is not available.")
            return redirect('user:dog_capture_request')

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
        if req.location_landmark_image:
            req.location_landmark_image.delete(save=False)
        req.location_landmark_image = None
        for landmark in req.landmark_images.all():
            landmark.image.delete(save=False)
        req.landmark_images.all().delete()
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
    else:
        req.latitude = None
        req.longitude = None
        req.manual_full_address = None
        req.barangay = None
        req.city = None
        if req.location_landmark_image:
            req.location_landmark_image.delete(save=False)
        req.location_landmark_image = None
        for landmark in req.landmark_images.all():
            landmark.image.delete(save=False)
        req.landmark_images.all().delete()
        city = None
        barangay = None

    req.request_type = request_type
    req.submission_type = submission_type or None
    req.preferred_appointment_date = preferred_appointment_date
    req.reason = reason
    req.description = description or None
    req.barangay = (_resolve_barangay_name(barangay) or barangay) if barangay else None
    req.city = city or None
    req.save(
        update_fields=[
            'request_type',
            'submission_type',
            'preferred_appointment_date',
            'reason',
            'description',
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

@user_only
def adopt_list(request):
    """Browse dogs that are available for adoption."""
    return render(request, "adopt/adopt_list.html", _build_public_post_listing(request, "adopt"))

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
    ).select_related("post", "post__owner").order_by("-created_at")

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
        'browse_url': reverse("user:adopt_list"),
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
def adopt_confirm(request, post_id):
    """Confirm and submit an adoption request for a staff-managed post."""
    return _handle_confirm_request(
        request=request,
        post_id=post_id,
        request_type="adopt",
        template_name="adopt/adopt_confirm.html",
        is_open_fn=lambda post: post.is_open_for_adoption(),
        not_open_message="Adoption is not open yet or has already closed.",
        duplicate_message="You already submitted an adoption request.",
        success_message="Adoption request submitted successfully! ðŸ¾",
    )
# =============================================================================
# Navigation 4/5: Announcement
# Covers announcement browsing, details, reactions, comments, and sharing.
# =============================================================================

@user_only
def announcement_list(request):
    """Render the public announcement feed grouped by display bucket."""
    user_reaction_subquery = AnnouncementReaction.objects.filter(
        announcement_id=OuterRef("pk"),
        user_id=request.user.id,
    )
    posts = (
        DogAnnouncement.objects.select_related("created_by", "created_by__profile").annotate(
            reaction_count=Count("reactions", distinct=True),
            user_reacted=Exists(user_reaction_subquery),
        ).prefetch_related(
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
        ).order_by("-created_at")
    )

    posts = list(posts)
    default_admin_avatar_url = static("images/officialseal.webp")
    pinned_announcements = []
    campaign_announcements = []
    regular_announcements = []

    for post in posts:
        post.admin_profile_image_url = _profile_image_url_or_default(
            post.created_by, default_admin_avatar_url
        )
        post.content_display = _clean_announcement_text_for_display(post.content)
        post.share_url = request.build_absolute_uri(
            reverse("user:announcement_share_preview", args=[post.id])
        )
        if post.display_bucket == DogAnnouncement.BUCKET_PINNED:
            pinned_announcements.append(post)
        elif post.display_bucket == DogAnnouncement.BUCKET_CAMPAIGN:
            campaign_announcements.append(post)
        else:
            regular_announcements.append(post)

    return render(request, 'announcement/announcement.html', {
        'pinned_announcements': pinned_announcements,
        'campaign_announcements': campaign_announcements,
        'regular_announcements': regular_announcements,
    })


@user_only
def announcement_detail(request, post_id):
    """Render a detailed announcement view with reactions and share data."""
    user_reaction_subquery = AnnouncementReaction.objects.filter(
        announcement_id=OuterRef("pk"),
        user_id=request.user.id,
    )
    post = get_object_or_404(
        DogAnnouncement.objects.select_related("created_by", "created_by__profile").annotate(
            reaction_count=Count("reactions", distinct=True),
            user_reacted=Exists(user_reaction_subquery),
        ).prefetch_related(
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
    return render(request, 'announcement/announcement_detail.html', {
        'post': post,
        'share_url': request.build_absolute_uri(
            reverse("user:announcement_share_preview", args=[post.id])
        ),
    })


@user_only
@require_POST
def announcement_react(request, post_id):
    """Toggle the current user's reaction on an announcement."""
    post = get_object_or_404(DogAnnouncement.objects.only("id"), id=post_id)

    existing_reaction = AnnouncementReaction.objects.filter(
        announcement_id=post.id,
        user_id=request.user.id,
    ).only("id").first()

    if existing_reaction:
        existing_reaction.delete()
        reacted = False
    else:
        try:
            AnnouncementReaction.objects.create(
                announcement_id=post.id,
                user_id=request.user.id,
            )
            reacted = True
        except IntegrityError:
            # Another request created the same reaction concurrently.
            reacted = True

    reaction_count = AnnouncementReaction.objects.filter(announcement_id=post.id).count()

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "ok": True,
            "reacted": reacted,
            "reaction_count": reaction_count,
        })

    next_url = (request.POST.get("next") or "").strip()
    if not next_url or not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse("user:announcement_list")
    return redirect(next_url)


def announcement_share_preview(request, post_id):
    """Render metadata-friendly announcement content for social sharing."""
    post = get_object_or_404(
        DogAnnouncement.objects.select_related("created_by").prefetch_related(
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

    primary_image_url = ""
    if post.background_image:
        primary_image_url = request.build_absolute_uri(post.background_image.url)
    elif getattr(post, "prefetched_images", None):
        primary_image_url = request.build_absolute_uri(post.prefetched_images[0].image.url)
    else:
        primary_image_url = request.build_absolute_uri(static("images/bayawan_logo.webp"))

    plain_caption = strip_tags(post.content or "").strip()
    if len(plain_caption) > 220:
        plain_caption = f"{plain_caption[:217].rstrip()}..."
    if not plain_caption:
        plain_caption = "Announcement update from Bayawan Vet."

    detail_url = request.build_absolute_uri(reverse("user:announcement_detail", args=[post.id]))
    share_url = request.build_absolute_uri(reverse("user:announcement_share_preview", args=[post.id]))

    return render(
        request,
        "announcement/announcement_share_preview.html",
        {
            "post": post,
            "primary_image_url": primary_image_url,
            "plain_caption": plain_caption,
            "detail_url": detail_url,
            "share_url": share_url,
        },
    )


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

# Navigation 3/5: Claim continued
@user_only
def my_claims(request):
    """Show the current user's submitted claim requests and their statuses."""
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
        'browse_url': reverse("user:claim_list"),
    })


@user_only
def claim_list(request):
    """Browse dogs that are still available to be claimed."""
    return render(request, "adopt/adopt_list.html", _build_public_post_listing(request, "claim"))


@user_only
def claim_confirm(request, post_id):
    """Confirm and submit a claim request for a staff-managed post."""
    return _handle_confirm_request(
        request=request,
        post_id=post_id,
        request_type="claim",
        template_name="claim/claim_confirm.html",
        is_open_fn=lambda post: post.is_open_for_claim(),
        not_open_message="Claim period has ended for this post.",
        duplicate_message="You already submitted a claim for this dog.",
        success_message="Claim submitted successfully! Admin will review it carefully ðŸ¾",
    )
