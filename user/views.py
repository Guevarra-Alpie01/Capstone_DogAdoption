from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.contrib.auth.models import User
from django.db.models import Count, DateTimeField, Exists, OuterRef, Prefetch, Q
from django.db import IntegrityError
from django.db.models.expressions import RawSQL
import os
import json
import base64
import hashlib
import random
from django.http import JsonResponse
from django.core.files.base import ContentFile
from django.conf import settings
from django.core.cache import cache
from datetime import timedelta
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.templatetags.static import static
from django.utils.html import strip_tags

#MODELS FROM ADMIN APP 
from dogadoption_admin.models import (
    AnnouncementComment,
    AnnouncementReaction,
    Barangay,
    DogAnnouncement,
    DogAnnouncementImage,
    GlobalAppointmentDate,
    Post,
    PostRequest,
)
from dogadoption_admin.context_processors import ADMIN_NOTIFICATIONS_CACHE_KEY

#MODELS FROM USER APP
from .models import Profile, DogCaptureRequest, DogCaptureRequestImage, DogCaptureRequestLandmarkImage, FaceImage, ClaimImage
from .models import UserAdoptionPost, UserAdoptionImage, UserAdoptionRequest, MissingDogPost

#FORMS.PY 
from .forms import MissingDogPostForm, UserAdoptionPostForm
# Decorator to allow only users


# USER-ONLY DECORATOR
def user_only(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('user:login')
        if request.user.is_staff:
            return redirect('dogadoption_admin:post_list')  # admin goes to admin dashboard
        return view_func(request, *args, **kwargs)
    return wrapper

# User Authentication through log in 
def login_view(request):
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
    logout(request)
    response = redirect("user:login")
    response.delete_cookie("admin_sessionid")
    return response



# Sign up for users
def _clean_barangay(value):
    return " ".join((value or "").split()).strip()


def _normalize_barangay(value):
    return "".join(ch.lower() for ch in _clean_barangay(value) if ch.isalnum())


def _resolve_barangay_name(value):
    normalized = _normalize_barangay(value)
    if not normalized:
        return ""
    for name in Barangay.objects.filter(is_active=True).values_list("name", flat=True):
        if _normalize_barangay(name) == normalized:
            return name
    return ""


def _profile_image_url_or_default(user, fallback_url):
    profile = getattr(user, "profile", None)
    image_field = getattr(profile, "profile_image", None)
    try:
        image_url = image_field.url if image_field else ""
    except Exception:
        image_url = ""
    return image_url or fallback_url


def _clean_announcement_text_for_display(raw_html):
    text = strip_tags(raw_html or "").replace("\xa0", " ")
    lines = text.splitlines()
    cleaned_lines = [line.lstrip() for line in lines]
    return "\n".join(cleaned_lines).strip()


def _format_posted_label(dt):
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


def _create_user_adoption_images(request, post):
    main_image = request.FILES.get("main_image")
    if main_image:
        UserAdoptionImage.objects.create(post=post, image=main_image)
    for img in request.FILES.getlist("extra_images"):
        UserAdoptionImage.objects.create(post=post, image=img)


def _handle_user_post_creation_submission(request, selected_type):
    adoption_form = UserAdoptionPostForm()
    missing_form = MissingDogPostForm()

    if selected_type == "missing":
        missing_form = MissingDogPostForm(request.POST, request.FILES)
        if missing_form.is_valid():
            post = missing_form.save(commit=False)
            post.owner = request.user
            post.save()
            messages.success(request, "Missing dog post created successfully.")
            return True, adoption_form, missing_form
        messages.error(request, "Missing dog post was not saved. Check the required fields and try again.")
        return False, adoption_form, missing_form

    adoption_form = UserAdoptionPostForm(request.POST, request.FILES)
    if adoption_form.is_valid():
        post = adoption_form.save(commit=False)
        post.owner = request.user
        post.save()
        _create_user_adoption_images(request, post)
        messages.success(request, "Adoption post created successfully.")
        return True, adoption_form, missing_form

    messages.error(request, "Adoption post was not saved. Check the required fields and try again.")
    return False, adoption_form, missing_form


def _get_available_appointment_dates():
    return GlobalAppointmentDate.objects.filter(
        is_active=True,
        appointment_date__gte=timezone.localdate(),
    ).order_by("appointment_date")


def _render_confirm_page(request, template_name, post, available_dates):
    return render(request, template_name, {
        "post": post,
        "available_dates": available_dates,
    })


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
    post = get_object_or_404(Post, id=post_id)
    available_dates = _get_available_appointment_dates()

    if post.status in ["reunited", "adopted"]:
        messages.warning(request, "This dog is no longer available.")
        return redirect("user:user_home")

    if not is_open_fn(post):
        messages.warning(request, not_open_message)
        return redirect("user:user_home")

    if PostRequest.objects.filter(
        user=request.user,
        post=post,
        request_type=request_type,
    ).exists():
        messages.info(request, duplicate_message)
        return redirect("user:user_home")

    if request.method == "POST":
        appointment_date_raw = request.POST.get("appointment_date")
        appointment_date = parse_date(appointment_date_raw) if appointment_date_raw else None

        if not appointment_date:
            messages.error(request, "Please select an appointment date.")
            return _render_confirm_page(request, template_name, post, available_dates)

        if not available_dates.filter(appointment_date=appointment_date).exists():
            messages.error(request, "Selected appointment date is not available.")
            return _render_confirm_page(request, template_name, post, available_dates)

        _create_post_request_with_images(request, post, request_type, appointment_date)
        messages.success(request, success_message)
        return redirect("user:user_home")

    return _render_confirm_page(request, template_name, post, available_dates)


def _user_post_requests(user, request_type):
    return PostRequest.objects.filter(
        user=user,
        request_type=request_type,
    ).select_related("post").order_by("-created_at")


FEED_CACHE_TTL_SECONDS = 90
FEED_POSTS_PER_PAGE = 12
FEED_ADMIN_CANDIDATE_LIMIT = 700
FEED_ANNOUNCEMENT_CANDIDATE_LIMIT = 300
FEED_USER_CANDIDATE_LIMIT = 400
FEED_MISSING_CANDIDATE_LIMIT = 300
FEED_ADMIN_SAMPLE_LIMIT = 240
FEED_ANNOUNCEMENT_SAMPLE_LIMIT = 70
FEED_USER_SAMPLE_LIMIT = 90
FEED_MISSING_SAMPLE_LIMIT = 70


def _normalized_feed_query(raw_query):
    return " ".join((raw_query or "").strip().split())


def _feed_cache_key(prefix, query, feed_token=""):
    query_hash = hashlib.md5(query.encode("utf-8")).hexdigest() if query else "all"
    token_hash = hashlib.md5(feed_token.encode("utf-8")).hexdigest() if feed_token else "default"
    return f"user_home:{prefix}:v3:{query_hash}:{token_hash}"


def _normalized_feed_token(raw_token):
    return (raw_token or "").strip()[:64]


def _fresh_feed_token():
    refresh_seed = f"{timezone.now().timestamp()}:{random.random()}"
    return hashlib.md5(refresh_seed.encode("utf-8")).hexdigest()[:16]


def _redirect_to_user_home_with_fresh_feed():
    return redirect(f"{reverse('user:user_home')}?feed_token={_fresh_feed_token()}")


def _sample_recent_ids_with_cache(cache_key, base_qs, candidate_limit, sample_limit):
    cached_ids = cache.get(cache_key)
    if cached_ids is not None:
        return cached_ids

    candidate_ids = list(
        base_qs.order_by("-created_at").values_list("id", flat=True)[:candidate_limit]
    )
    if len(candidate_ids) > sample_limit:
        sampled_ids = random.sample(candidate_ids, sample_limit)
    else:
        sampled_ids = candidate_ids

    random.shuffle(sampled_ids)
    cache.set(cache_key, sampled_ids, FEED_CACHE_TTL_SECONDS)
    return sampled_ids


def _sample_ids_with_cache(cache_key, candidate_ids, sample_limit):
    cached_ids = cache.get(cache_key)
    if cached_ids is not None:
        return cached_ids

    if len(candidate_ids) > sample_limit:
        sampled_ids = random.sample(candidate_ids, sample_limit)
    else:
        sampled_ids = candidate_ids

    random.shuffle(sampled_ids)
    cache.set(cache_key, sampled_ids, FEED_CACHE_TTL_SECONDS)
    return sampled_ids


def _build_random_home_rows(query, feed_token="", dogs_only=False):
    feed_scope = "dogs_only" if dogs_only else "mixed"
    mixed_cache_key = _feed_cache_key(f"{feed_scope}_rows", query, feed_token)
    cached_rows = cache.get(mixed_cache_key)
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
        admin_qs = admin_qs.filter(
            Q(caption__icontains=query)
            | Q(location__icontains=query)
            | Q(status__icontains=query)
        )
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

    admin_candidates = list(admin_qs.order_by("-created_at")[:FEED_ADMIN_CANDIDATE_LIMIT])
    active_admin_candidate_ids = [
        post.id for post in admin_candidates if post.current_phase() in {"claim", "adopt"}
    ]
    admin_ids = _sample_ids_with_cache(
        _feed_cache_key(f"{feed_scope}_admin_ids", query, feed_token),
        active_admin_candidate_ids,
        sample_limit=FEED_ADMIN_SAMPLE_LIMIT,
    )
    announcement_ids = []
    if not dogs_only:
        announcement_ids = _sample_recent_ids_with_cache(
            _feed_cache_key(f"{feed_scope}_announcement_ids", query, feed_token),
            announcement_qs,
            candidate_limit=FEED_ANNOUNCEMENT_CANDIDATE_LIMIT,
            sample_limit=FEED_ANNOUNCEMENT_SAMPLE_LIMIT,
        )
    user_ids = _sample_recent_ids_with_cache(
        _feed_cache_key(f"{feed_scope}_user_ids", query, feed_token),
        user_qs,
        candidate_limit=FEED_USER_CANDIDATE_LIMIT,
        sample_limit=FEED_USER_SAMPLE_LIMIT,
    )
    missing_ids = _sample_recent_ids_with_cache(
        _feed_cache_key(f"{feed_scope}_missing_ids", query, feed_token),
        missing_qs,
        candidate_limit=FEED_MISSING_CANDIDATE_LIMIT,
        sample_limit=FEED_MISSING_SAMPLE_LIMIT,
    )

    mixed_rows = [{"id": post_id, "feed_type": "admin"} for post_id in admin_ids]
    mixed_rows.extend({"id": ann_id, "feed_type": "announcement"} for ann_id in announcement_ids)
    mixed_rows.extend({"id": user_id, "feed_type": "user"} for user_id in user_ids)
    mixed_rows.extend({"id": missing_id, "feed_type": "missing"} for missing_id in missing_ids)
    random.shuffle(mixed_rows)
    cache.set(mixed_cache_key, mixed_rows, FEED_CACHE_TTL_SECONDS)
    return mixed_rows


def _is_valid_capture_reason(reason):
    return reason in DogCaptureRequest.REASON_LABELS


def _group_capture_requests_by_status(requests):
    return {
        "accepted_requests": [req for req in requests if req.status == "accepted"],
        "pending_requests": [req for req in requests if req.status == "pending"],
        "captured_requests": [req for req in requests if req.status == "captured"],
        "declined_requests": [req for req in requests if req.status == "declined"],
    }


def barangay_list_api(request):
    barangays = list(Barangay.objects.filter(is_active=True).values_list("name", flat=True))
    return JsonResponse({"barangays": barangays})


def signup_view(request):
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

#editing users profileS
@user_only
def edit_profile(request):
    user = request.user
    profile, created = Profile.objects.get_or_create(
        user=user,
        defaults={
            "address": "",
            "age": 18,
            "consent_given": True
        }
    )

    if request.method == "POST":
        # User fields
        user.first_name = request.POST.get("first_name", "").strip()
        user.last_name = request.POST.get("last_name", "").strip()

        # Profile fields
        profile.middle_initial = request.POST.get("middle_initial", "").strip()
        profile.address = request.POST.get("address", "").strip()
        profile.age = request.POST.get("age") or profile.age
        profile.phone_number = request.POST.get("phone_number", "").strip()
        profile.facebook_url = request.POST.get("facebook_url", "").strip()

        if request.FILES.get("profile_image"):
            profile.profile_image = request.FILES["profile_image"]

        user.save()
        profile.save()

        messages.success(request, "Profile updated successfully")
        return redirect("user:edit_profile")

    return render(request, "edit_profile.html", {
        "profile": profile
    })


@csrf_exempt
def face_auth(request):
    if "signup_data" not in request.session:
        return redirect("user:signup")
    return render(request, "face_auth.html")

#Save Face Images

@csrf_exempt
def save_face(request):
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



# Signup Complete
def signup_complete(request):
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
        consent_given=True
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

# USER HOME VIEW
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
    feed_token = _normalized_feed_token(request.GET.get("feed_token"))
    page_number = request.GET.get("page", 1)
    show_dogs_only = request.user.is_authenticated and not request.user.is_staff
    mixed_rows = _build_random_home_rows(query, feed_token=feed_token, dogs_only=show_dogs_only)

    paginator = Paginator(mixed_rows, FEED_POSTS_PER_PAGE)
    page_obj = paginator.get_page(page_number)
    feed_rows = list(page_obj.object_list)

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
        user_id=request.user.id,
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
    for row in feed_rows:
        post_type = row["feed_type"]
        post_id = row["id"]

        if post_type == "admin":
            p = admin_map.get(post_id)
            if not p:
                continue
            post_images = list(p.images.all())
            main_image = post_images[0] if post_images else None
            image_count = len(post_images)

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
            announcement_images = list(p.images.all())
            first_image_url = announcement_images[0].image.url if announcement_images else ""
            main_image_url = first_image_url or (p.background_image.url if p.background_image else "")

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
            post_images = list(p.images.all())
            main_image = post_images[0] if post_images else None

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
            })
            continue

        p = missing_map.get(post_id)
        if not p:
            continue
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
        })

    return {
        "posts": combined_posts,
        "page_obj": page_obj,
        "query": query,
        "feed_token": feed_token,
        "selected_type": selected_type,
        "adoption_form": adoption_form,
        "missing_form": missing_form,
        "open_create_modal": open_create_modal,
    }


def _render_home_with_auth_modal(request, auth_modal, **extra_context):
    context = _build_user_home_context(request)
    context.update({
        "auth_modal": auth_modal,
        **extra_context,
    })
    return render(request, "home/user_home.html", context)


def user_home(request):
    # Redirect staff to admin dashboard
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('dogadoption_admin:post_list')

    selected_type = request.GET.get("type", "adoption")
    adoption_form = UserAdoptionPostForm()
    missing_form = MissingDogPostForm()
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

    query = _normalized_feed_query(request.GET.get("q"))
    if request.GET.get("refresh") == "1":
        refresh_seed = f"{query}:{timezone.now().timestamp()}:{random.random()}"
        refresh_token = hashlib.md5(refresh_seed.encode("utf-8")).hexdigest()[:16]
        params = request.GET.copy()
        params.pop("refresh", None)
        params["feed_token"] = refresh_token
        params["page"] = "1"
        target = reverse("user:user_home")
        return redirect(f"{target}?{params.urlencode()}")

    return render(request, "home/user_home.html", _build_user_home_context(
        request,
        selected_type=selected_type,
        adoption_form=adoption_form,
        missing_form=missing_form,
        open_create_modal=open_create_modal,
    ))

@user_only
def create_post(request):
    selected_type = request.GET.get("type", "adoption")
    if request.method == "POST":
        selected_type = request.POST.get("post_type", "adoption")

    adoption_form = UserAdoptionPostForm()
    missing_form = MissingDogPostForm()

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
    post = get_object_or_404(UserAdoptionPost, id=post_id)

    if post.owner == request.user:
        return redirect('user:user_home')

    if post.status != "available":
        messages.warning(request, "This dog is no longer available.")
        return redirect("user:user_home")

    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.phone_number or not profile.facebook_url:
        messages.warning(request, "Please add your phone number and Facebook profile before requesting adoption.")
        return redirect("user:edit_profile")

    UserAdoptionRequest.objects.get_or_create(
        post=post,
        requester=request.user
    )

    return redirect('user:user_home')


@user_only
def user_adoption_requests(request):
    requests = UserAdoptionRequest.objects.filter(
        post__owner=request.user
    ).select_related("post", "requester", "requester__profile").order_by("-created_at")

    return render(request, "adopt/user_post_requests.html", {
        "requests": requests,
    })


@user_only
def user_adoption_request_action(request, req_id, action):
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
        messages.success(request, "Adoption request accepted.")
    elif action == "decline":
        req.status = "rejected"
        req.save(update_fields=["status"])
        messages.info(request, "Adoption request declined.")

    return redirect("user:user_adoption_requests")



# VIEW FOR FACEBOOK SHARED LINK PREVIEW
@user_only
def post_detail(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    return render(request, 'home/post_detail.html', {'post': post})


#USER REQUEST PAGE 
@user_only
def request_dog_capture(request):
    if request.method == 'POST':
        uploaded_images = list(request.FILES.getlist('images'))
        legacy_image = request.FILES.get('image')
        if legacy_image:
            uploaded_images.append(legacy_image)
        captured_image = request.POST.get('captured_image')
        reason = (request.POST.get('reason') or '').strip()
        description = (request.POST.get('description') or '').strip()
        location_mode = (request.POST.get('location_mode') or 'exact').strip().lower()
        if location_mode not in {'exact', 'manual'}:
            location_mode = 'exact'

        barangay = _clean_barangay(request.POST.get('barangay'))
        city = _clean_barangay(request.POST.get('city'))
        manual_full_address = " ".join(
            (request.POST.get('manual_full_address') or '').split()
        ).strip()
        location_landmark_images = list(request.FILES.getlist('location_landmark_image'))
        latitude_raw = (request.POST.get('latitude') or '').strip()
        longitude_raw = (request.POST.get('longitude') or '').strip()

        if not uploaded_images and captured_image and ';base64,' in captured_image:
            _, imgstr = captured_image.split(';base64,', 1)
            filename = f"capture_{request.user.id}_{int(timezone.now().timestamp())}.png"
            uploaded_images = [ContentFile(base64.b64decode(imgstr), name=filename)]

        if not _is_valid_capture_reason(reason):
            messages.error(request, "Please select a valid reason.")
            return redirect('user:dog_capture_request')

        if location_mode == 'manual':
            if not manual_full_address:
                messages.error(request, "Please provide your full manual address.")
                return redirect('user:dog_capture_request')
            if not location_landmark_images:
                messages.error(
                    request,
                    "Please upload at least one landmark/highway/crossing image for manual address.",
                )
                return redirect('user:dog_capture_request')
            latitude_value = None
            longitude_value = None
        else:
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

        new_req = DogCaptureRequest.objects.create(
            requested_by=request.user,
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
        from dogadoption_admin.models import AdminNotification
        AdminNotification.objects.create(
            title="New dog capture request",
            message=f"{request.user.username} submitted a request.",
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
    })




@user_only
@require_POST
def edit_dog_capture_request(request, req_id):
    req = get_object_or_404(
        DogCaptureRequest,
        id=req_id,
        requested_by=request.user,
    )

    # User can only update requests that are still waiting for admin action.
    if req.status != 'pending':
        messages.warning(request, "Only pending requests can be edited.")
        return redirect('user:dog_capture_request')

    reason = (request.POST.get('reason') or '').strip()
    if not _is_valid_capture_reason(reason):
        messages.error(request, "Please select a valid reason.")
        return redirect('user:dog_capture_request')

    description = (request.POST.get('description') or '').strip()
    barangay = _clean_barangay(request.POST.get('barangay'))
    city = _clean_barangay(request.POST.get('city'))
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

    # Exact mode stores GPS coordinates; manual mode stores full manual address.
    if location_mode == 'exact':
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
    else:
        if not manual_full_address:
            messages.error(request, "Please provide your full manual address.")
            return redirect('user:dog_capture_request')
        remaining_extra_landmarks = req.landmark_images.exclude(id__in=remove_landmark_ids)
        primary_count = 1 if (req.location_landmark_image and not remove_primary_landmark) else 0
        has_existing_landmarks = bool(primary_count or remaining_extra_landmarks.exists())
        if not has_existing_landmarks and not location_landmark_images:
            messages.error(
                request,
                "Please upload at least one landmark/highway/crossing image for manual address.",
            )
            return redirect('user:dog_capture_request')

        req.latitude = None
        req.longitude = None
        req.manual_full_address = manual_full_address

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

    req.reason = reason
    req.description = description or None
    req.barangay = (_resolve_barangay_name(barangay) or barangay) if barangay else None
    req.city = city or None
    req.save(
        update_fields=[
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


#CLAIM PAGE 
@user_only
def claim(request):
    return render(request, 'claim/claim.html')




#ADOPTION PAGE
@user_only
def adopt_list(request):
    filter_type = request.GET.get("filter", "all")
    page_number = request.GET.get("page", 1)
    posts_per_page = 12
    now = timezone.now()
    post_table = Post._meta.db_table

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
    active_statuses = ["rescued", "under_care"]

    posts_qs = Post.objects.select_related(
        "user", "user__profile"
    ).prefetch_related("images").order_by("-created_at")

    # Use database filters so large datasets can still paginate efficiently.
    if filter_type == "ready_claim":
        posts_qs = posts_qs.filter(status__in=active_statuses).annotate(
            claim_deadline_db=claim_deadline_expr
        ).filter(claim_deadline_db__gte=now)
    elif filter_type == "ready_adopt":
        posts_qs = posts_qs.filter(status__in=active_statuses).annotate(
            claim_deadline_db=claim_deadline_expr,
            adopt_deadline_db=adopt_deadline_expr,
        ).filter(
            claim_deadline_db__lt=now,
            adopt_deadline_db__gte=now,
        )
    elif filter_type == "adopted":
        posts_qs = posts_qs.filter(status="adopted")
    elif filter_type == "claimed":
        posts_qs = posts_qs.filter(status="reunited")

    paginator = Paginator(posts_qs, posts_per_page)
    page_obj = paginator.get_page(page_number)
    post_items = []
    for p in page_obj.object_list:
        post_images = list(p.images.all())
        main_image = post_images[0] if post_images else None
        phase, days, hours, minutes = _post_phase_payload(p)
        post_items.append({
            "post": p,
            "phase": phase,
            "days_left": days,
            "hours_left": hours,
            "minutes_left": minutes,
            "main_image_url": main_image.image.url if main_image else "",
        })

    return render(request, "adopt/adopt_list.html", {
        "posts": post_items,
        "current_filter": filter_type,
        "page_obj": page_obj,
    })

@user_only
def adopt_status(request):
    requests = _user_post_requests(request.user, "adopt")
    return render(request, 'adopt/adopt.html', {'requests': requests})

@user_only
def adopt_confirm(request, post_id):
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



@user_only
def announcement_list(request):
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

#CLAIM PAGE

@user_only
def my_claims(request):
    claims = _user_post_requests(request.user, "claim")

    return render(request, 'claim/claim.html', {
        'claims': claims
    })


@user_only
def claim_confirm(request, post_id):
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
