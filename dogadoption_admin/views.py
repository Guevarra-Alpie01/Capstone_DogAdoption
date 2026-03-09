from datetime import datetime, timedelta
from decimal import Decimal
from collections import defaultdict
import hashlib
import io
import json
import re
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Value
from django.db.models.functions import Concat, Lower, Trim, TruncDate
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_http_methods, require_POST

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xhtml2pdf import pisa

from .forms import CitationForm, PenaltyForm, PostForm, SectionForm
from .cache_utils import ANALYTICS_DASHBOARD_CACHE_KEY
from .context_processors import ADMIN_NOTIFICATIONS_CACHE_KEY
from .models import (
    AdminNotification,
    Barangay,
    CertificateSettings,
    Citation,
    DewormingTreatmentRecord,
    Dog,
    DogImage,
    DogAnnouncement,
    DogAnnouncementImage,
    DogCatcherContact,
    DogRegistration,
    GlobalAppointmentDate,
    Penalty,
    PenaltySection,
    Post,
    PostImage,
    PostRequest,
    VaccinationRecord,
)
from user.models import (
    DogCaptureRequest,
    FaceImage,
    Profile,
)
from user.notification_utils import (
    invalidate_user_notification_content,
    invalidate_user_notification_payload,
    remember_request_reviewed_at,
)

def _clean_barangay(value):
    return " ".join((value or "").split()).strip()


def _normalize_person_name(value):
    return " ".join((value or "").split()).strip().casefold()


def _owner_initials(name):
    parts = [part for part in (name or "").strip().split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return f"{parts[0][:1]}{parts[-1][:1]}".upper()


def _build_owner_profile_lookup(owner_names):
    normalized_names = {_normalize_person_name(name) for name in owner_names if name}
    if not normalized_names:
        return {}

    profiles = (
        Profile.objects.select_related("user")
        .annotate(
            owner_full_name_norm=Lower(
                Trim(
                    Concat(
                        "user__first_name",
                        Value(" "),
                        "user__last_name",
                    )
                )
            )
        )
        .filter(owner_full_name_norm__in=normalized_names)
    )

    lookup = {}
    for profile in profiles:
        image_field = getattr(profile, "profile_image", None)
        if not image_field:
            continue
        try:
            image_url = image_field.url
        except (ValueError, AttributeError):
            image_url = ""
        if image_url and profile.owner_full_name_norm not in lookup:
            lookup[profile.owner_full_name_norm] = image_url
    return lookup


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


#extracting barangays
def _extract_barangay_from_address(address):
    cleaned = _clean_barangay(address)
    if not cleaned:
        return ""

    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    if len(parts) >= 3 and parts[-2].lower() == "bayawan city" and parts[-1].lower() == "negros oriental":
        candidate = parts[-3]
        resolved = _resolve_barangay_name(candidate)
        return resolved or candidate

    for part in reversed(parts):
        resolved = _resolve_barangay_name(part)
        if resolved:
            return resolved

    return _resolve_barangay_name(cleaned)


BAYAWAN_ALLOWED_BARANGAYS = (
    "Ali-is",
    "Banaybanay",
    "Banga",
    "Boyco",
    "Bugay",
    "Cansumalig",
    "Dawis",
    "Kalamtukan",
    "Kalumboyan",
    "Malabugas",
    "Mandu-ao",
    "Maninihon",
    "Minaba",
    "Nangka",
    "Narra",
    "Pagatban",
    "Poblacion",
    "San Isidro",
    "San Jose",
    "San Miguel",
    "San Roque",
    "Suba",
    "Tabuan",
    "Tayawan",
    "Tinago",
    "Ubos",
    "Villareal",
    "Villasol",
)

BAYAWAN_ALLOWED_BARANGAY_KEYS = {
    _normalize_barangay(name) for name in BAYAWAN_ALLOWED_BARANGAYS
}


def _normalize_city(value):
    return "".join(ch.lower() for ch in _clean_barangay(value) if ch.isalnum())


def _is_bayawan_city(value):
    return _normalize_city(value) in {"bayawan", "bayawancity"}


def _extract_city_from_address(address):
    cleaned = _clean_barangay(address)
    if not cleaned:
        return ""

    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    for part in reversed(parts):
        if _is_bayawan_city(part):
            return "Bayawan City"
    return ""


def _is_allowed_bayawan_map_point(barangay, city):
    return (
        _normalize_barangay(barangay) in BAYAWAN_ALLOWED_BARANGAY_KEYS
        and _is_bayawan_city(city)
    )


def _build_owner_full_name(first_name, last_name, fallback=""):
    first = " ".join((first_name or "").split()).strip()
    last = " ".join((last_name or "").split()).strip()
    fallback_clean = " ".join((fallback or "").split()).strip()

    if first or last:
        return f"{first} {last}".strip()
    return fallback_clean


def _registration_owner_key_from_names(first_name, last_name, fallback=""):
    owner_name = _build_owner_full_name(first_name, last_name, fallback)
    return _normalize_person_name(owner_name)


def _resolve_registration_owner_identity(owner_first_name, owner_last_name, owner_user_id=""):
    first = " ".join((owner_first_name or "").split()).strip()
    last = " ".join((owner_last_name or "").split()).strip()
    owner_name_key = _registration_owner_key_from_names(first, last)
    resolved_owner_user = None

    owner_user_id_text = str(owner_user_id or "").strip()
    if owner_user_id_text.isdigit() and owner_name_key:
        resolved_owner_user = (
            User.objects.filter(
                id=int(owner_user_id_text),
                is_active=True,
                is_staff=False,
                first_name__iexact=first,
                last_name__iexact=last,
            )
            .only("id", "first_name", "last_name")
            .first()
        )

    if not resolved_owner_user and owner_name_key:
        resolved_owner_user = (
            User.objects.filter(
                is_active=True,
                is_staff=False,
                first_name__iexact=first,
                last_name__iexact=last,
            )
            .order_by("id")
            .only("id", "first_name", "last_name")
            .first()
        )

    canonical_first = resolved_owner_user.first_name if resolved_owner_user else first
    canonical_last = resolved_owner_user.last_name if resolved_owner_user else last
    canonical_owner_name = _build_owner_full_name(canonical_first, canonical_last)
    canonical_owner_key = _normalize_person_name(canonical_owner_name)

    return canonical_owner_name, canonical_owner_key, resolved_owner_user


def _build_owner_limit_query(owner_name_key, owner_name, owner_user=None):
    normalized_owner_key = _normalize_person_name(owner_name_key or owner_name)
    owner_query = Q()

    if normalized_owner_key:
        owner_query |= Q(owner_name_key=normalized_owner_key)

    if owner_name:
        owner_query |= Q(owner_name__iexact=owner_name)

    if owner_user is not None:
        owner_query |= Q(owner_user=owner_user)

    return owner_query


def _format_cert_date(value):
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%m-%d-%Y")
    return str(value)


def _pad_rows(rows, min_rows):
    padded = list(rows)
    while len(padded) < min_rows:
        padded.append({})
    return padded


def _build_certificate_payload(
    registration,
    vaccinations=None,
    dewormings=None,
    vac_limit=10,
    vac_min_rows=10,
    dew_limit=8,
    dew_min_rows=8,
):
    vac_records = list(vaccinations) if vaccinations is not None else list(
        VaccinationRecord.objects.filter(registration=registration).order_by("-date")
    )
    dew_records = list(dewormings) if dewormings is not None else list(
        DewormingTreatmentRecord.objects.filter(registration=registration).order_by("-date")
    )

    vac_rows = []
    for record in vac_records[:vac_limit]:
        vac_rows.append({
            "date": _format_cert_date(record.date),
            "vaccine_name": record.vaccine_name or "",
            "manufacturer_lot_no": record.manufacturer_lot_no or "",
            "vaccine_expiry_date": _format_cert_date(record.vaccine_expiry_date),
            "vaccination_expiry_date": _format_cert_date(record.vaccination_expiry_date),
            "veterinarian": record.veterinarian or "",
        })

    dew_rows = []
    for record in dew_records[:dew_limit]:
        route = (record.route or "").strip()
        frequency = (record.frequency or "").strip()
        route_frequency = f"{route} / {frequency}".strip(" /") if (route or frequency) else ""
        dew_rows.append({
            "date": _format_cert_date(record.date),
            "medicine_given": record.medicine_given or "",
            "route_frequency": route_frequency,
            "veterinarian": record.veterinarian or "",
        })

    return {
        "id": registration.id,
        "reg_no": registration.reg_no or "",
        "name_of_pet": registration.name_of_pet or "",
        "breed": registration.breed or "",
        "dob": _format_cert_date(registration.dob),
        "color_markings": registration.color_markings or "",
        "sex": registration.sex or "",
        "is_male": registration.sex == "M",
        "is_female": registration.sex == "F",
        "status": registration.status or "",
        "is_castrated": registration.status == "Castrated",
        "is_spayed": registration.status == "Spayed",
        "is_intact": registration.status == "Intact",
        "owner_name": registration.owner_name or "",
        "address": registration.address or "",
        "contact_no": registration.contact_no or "",
        "vaccination_rows": _pad_rows(vac_rows, vac_min_rows),
        "deworming_rows": _pad_rows(dew_rows, dew_min_rows),
        "vaccination_count": len(vac_records),
        "deworming_count": len(dew_records),
        "has_vaccinations": bool(vac_records),
        "has_dewormings": bool(dew_records),
    }

def _enrich_capture_request_user(req):
    user = req.requested_by
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        profile = None

    name_parts = [user.first_name, user.last_name]
    full_name = " ".join(part for part in name_parts if part).strip() or user.username

    req.requester_full_name = full_name
    req.requester_phone = (
        profile.phone_number.strip()
        if profile and profile.phone_number
        else "No phone number"
    )
    req.requester_address = (
        profile.address.strip()
        if profile and profile.address
        else "No address provided"
    )
    req.requester_facebook = (
        profile.facebook_url.strip()
        if profile and profile.facebook_url
        else ""
    )


def _enrich_capture_request_display(req):
    _enrich_capture_request_user(req)

    barangay = _clean_barangay(req.barangay)
    city = _clean_barangay(req.city)
    manual_full_address = _clean_barangay(req.manual_full_address)
    try:
        profile_address = _clean_barangay(req.requested_by.profile.address)
    except Profile.DoesNotExist:
        profile_address = ""

    if not barangay:
        profile_barangay = profile_address
        barangay = _resolve_barangay_name(profile_barangay) or profile_barangay

    if not city:
        city = _extract_city_from_address(profile_address)

    if manual_full_address:
        req.location_label = manual_full_address
    elif barangay and city:
        req.location_label = f"{barangay}, {city}"
    elif barangay:
        req.location_label = barangay
    elif city:
        req.location_label = city
    elif req.latitude is not None and req.longitude is not None:
        req.location_label = "Pinned location"
    else:
        req.location_label = "No location"
    req.has_location = req.location_label != "No location"
    req.display_barangay = barangay

    request_images = list(req.images.all())
    if request_images:
        image_url = request_images[0].image.url
    elif req.image:
        image_url = req.image.url
    else:
        image_url = ""
    req.preview_image_url = image_url


ANNOUNCEMENT_CATEGORY_OPTIONS = [
    {
        "slug": "dog-announcements",
        "value": DogAnnouncement.CATEGORY_DOG_ANNOUNCEMENT,
        "label": "Dog Announcements",
        "description": (
            "For vaccination programs, educational campaigns, dog-related events, "
            "and general dog care information."
        ),
        "topics": [
            "Vaccination programs",
            "Educational campaigns",
            "Dog-related events",
            "General dog care information",
        ],
    },
    {
        "slug": "dog-laws",
        "value": DogAnnouncement.CATEGORY_DOG_LAW,
        "label": "Dog Laws",
        "description": (
            "For rules and regulations about dogs, local ordinances, and legal "
            "responsibilities of dog owners."
        ),
        "topics": [
            "Rules and regulations about dogs",
            "Local ordinances",
            "Legal responsibilities of dog owners",
        ],
    },
]

ANNOUNCEMENT_CATEGORY_BY_SLUG = {
    option["slug"]: option for option in ANNOUNCEMENT_CATEGORY_OPTIONS
}

ANNOUNCEMENT_CATEGORY_BY_VALUE = {
    option["value"]: option for option in ANNOUNCEMENT_CATEGORY_OPTIONS
}

ANNOUNCEMENT_BUCKET_VALUES = {
    value for value, _label in DogAnnouncement.DISPLAY_BUCKET_CHOICES
}

ANALYTICS_DASHBOARD_CACHE_TTL_SECONDS = 60


def _set_post_form_barangay_source(post_form):
    post_form.fields["location"].widget.attrs["data-barangay-source-url"] = reverse(
        "dogadoption_admin:barangay_list_api"
    )


def _parse_appointment_dates(dates_raw):
    parsed_dates = []
    for value in [v.strip() for v in (dates_raw or "").split(",") if v.strip()]:
        parsed_date = parse_date(value)
        if parsed_date:
            parsed_dates.append(parsed_date)
    return sorted(set(parsed_dates))


def _save_global_appointment_dates(parsed_dates, user):
    with transaction.atomic():
        GlobalAppointmentDate.objects.exclude(
            appointment_date__in=parsed_dates
        ).delete()
        for day in parsed_dates:
            GlobalAppointmentDate.objects.update_or_create(
                appointment_date=day,
                defaults={
                    "created_by": user,
                    "is_active": True,
                },
            )


def _validate_and_save_global_appointment_dates(dates_raw, user):
    parsed_dates = _parse_appointment_dates(dates_raw)
    today = timezone.localdate()
    if any(d < today for d in parsed_dates):
        return False
    _save_global_appointment_dates(parsed_dates, user)
    return True


def _get_active_global_appointment_dates():
    return list(
        GlobalAppointmentDate.objects.filter(
            is_active=True
        ).order_by("appointment_date").values_list("appointment_date", flat=True)
    )


def _get_available_appointment_dates():
    return GlobalAppointmentDate.objects.filter(
        is_active=True,
        appointment_date__gte=timezone.localdate(),
    ).order_by("appointment_date")


def _build_requests_with_meta(post, request_type):
    requests_qs = (
        post.requests.filter(request_type=request_type)
        .select_related("user")
        .prefetch_related("images")
        .order_by("-created_at")
    )
    requests = list(requests_qs)
    user_ids = [req.user_id for req in requests]

    profiles = Profile.objects.filter(user_id__in=user_ids)
    faceauth = FaceImage.objects.filter(user_id__in=user_ids)
    profile_by_user_id = {profile.user_id: profile for profile in profiles}
    faceauth_by_user_id = defaultdict(list)
    for image in faceauth:
        faceauth_by_user_id[image.user_id].append(image)

    requests_with_meta = []
    for req in requests:
        requests_with_meta.append({
            "req": req,
            "profile": profile_by_user_id.get(req.user_id),
            "face_images": faceauth_by_user_id.get(req.user_id, []),
        })
    return requests_with_meta


def _build_request_redirect(req):
    if req.request_type == "claim":
        return redirect("dogadoption_admin:claim_requests", req.post.id)
    return redirect("dogadoption_admin:adoption_requests", req.post.id)


def _build_request_redirect_or_next(request, req):
    next_url = (request.POST.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return _build_request_redirect(req)


def _render_post_request_list(request, post_id, request_type, template_name):
    post = get_object_or_404(Post, id=post_id)
    return render(request, template_name, {
        "post": post,
        "requests_meta": _build_requests_with_meta(post, request_type),
        "available_dates": _get_available_appointment_dates(),
    })


def _apply_registration_date_filter(dogs, date_filter_type, filter_date, filter_month, filter_year):
    date_filter_label = ""

    if date_filter_type == "day" and filter_date:
        selected_date = parse_date(filter_date)
        if selected_date:
            dogs = dogs.filter(date_registered=selected_date)
            date_filter_label = selected_date.strftime("%b %d, %Y")
        else:
            date_filter_type = "all"
    elif date_filter_type == "month" and filter_month:
        month_match = re.match(r"^(\d{4})-(\d{2})$", filter_month)
        if month_match:
            month_year = int(month_match.group(1))
            month_value = int(month_match.group(2))
            if 1 <= month_value <= 12:
                dogs = dogs.filter(
                    date_registered__year=month_year,
                    date_registered__month=month_value,
                )
                date_filter_label = datetime(month_year, month_value, 1).strftime("%B %Y")
            else:
                date_filter_type = "all"
        else:
            date_filter_type = "all"
    elif date_filter_type == "year" and filter_year:
        if filter_year.isdigit():
            year_value = int(filter_year)
            if 1900 <= year_value <= 9999:
                dogs = dogs.filter(date_registered__year=year_value)
                date_filter_label = str(year_value)
            else:
                date_filter_type = "all"
        else:
            date_filter_type = "all"
    else:
        date_filter_type = "all"

    return dogs, date_filter_type, date_filter_label


def _build_registration_filter_params(date_filter_type, filter_date, filter_month, filter_year):
    if date_filter_type == "day" and filter_date:
        return {
            "date_filter_type": "day",
            "filter_date": filter_date,
        }
    if date_filter_type == "month" and filter_month:
        return {
            "date_filter_type": "month",
            "filter_month": filter_month,
        }
    if date_filter_type == "year" and filter_year:
        return {
            "date_filter_type": "year",
            "filter_year": filter_year,
        }
    return {}


def _create_vaccination_and_update_defaults(
    registration,
    cert_settings,
    vac_date,
    vaccine_name,
    manufacturer_lot_no,
    vaccine_expiry_date,
    vaccination_expiry_date,
):
    VaccinationRecord.objects.create(
        registration=registration,
        date=vac_date,
        vaccine_name=vaccine_name,
        manufacturer_lot_no=manufacturer_lot_no,
        vaccine_expiry_date=vaccine_expiry_date,
        vaccination_expiry_date=vaccination_expiry_date,
        veterinarian="",
    )
    settings_obj = cert_settings or CertificateSettings.objects.create()
    if vac_date:
        parsed_vac_date = parse_date(vac_date)
        if parsed_vac_date:
            settings_obj.default_vac_date = parsed_vac_date
    if vaccine_name:
        settings_obj.default_vaccine_name = vaccine_name
    if manufacturer_lot_no:
        settings_obj.default_manufacturer_lot_no = manufacturer_lot_no
    if vaccine_expiry_date:
        parsed_vac_expiry = parse_date(vaccine_expiry_date)
        if parsed_vac_expiry:
            settings_obj.default_vaccine_expiry_date = parsed_vac_expiry
    settings_obj.save(update_fields=[
        "default_vac_date",
        "default_vaccine_name",
        "default_manufacturer_lot_no",
        "default_vaccine_expiry_date",
    ])
    return settings_obj


def _get_vaccination_post_values(request):
    return (
        (request.POST.get("vac_date") or "").strip(),
        (request.POST.get("vaccine_name") or "").strip(),
        (request.POST.get("manufacturer_lot_no") or "").strip(),
        (request.POST.get("vaccine_expiry_date") or "").strip(),
        (request.POST.get("vaccination_expiry_date") or "").strip(),
    )


def _latest_certificate_record_date(rows):
    return next((row.get("date", "") for row in rows if row.get("date")), "")


DOG_REGISTRATION_MAX_IMAGES = 12
DOG_REGISTRATION_MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
DOG_REGISTRATION_OWNER_MAX_PETS = 4


def _validate_registration_images(uploaded_images):
    if len(uploaded_images) > DOG_REGISTRATION_MAX_IMAGES:
        return f"You can upload up to {DOG_REGISTRATION_MAX_IMAGES} photos per registration."

    for image in uploaded_images:
        if image.size <= 0:
            return "One of the uploaded files is empty."
        if image.size > DOG_REGISTRATION_MAX_IMAGE_SIZE_BYTES:
            return "Each image must be 10 MB or smaller."

        content_type = (getattr(image, "content_type", "") or "").lower()
        if not content_type.startswith("image/"):
            return "Only image files are allowed for registration photos."

    return ""


# views.py


# ADMIN-ONLY DECORATOR
def admin_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            return redirect('user:login')
        return view_func(request, *args, **kwargs)
    return wrapper

# AUTH VIEWS

def admin_login(request):
    return redirect('user:login')


@login_required
def admin_logout(request):
    logout(request)
    response = redirect('user:login')
    response.delete_cookie('admin_sessionid')
    return response


# ===================       HOMEPAGE OF THE ADMIN        ===================

# CREATE POST
@admin_required
def create_post(request):
    if request.method == 'POST':
        post_form = PostForm(request.POST)

        if post_form.is_valid():
            post = post_form.save(commit=False)
            post.user = request.user
            post.save()

            # Multiple images
            for image in request.FILES.getlist('images'):
                PostImage.objects.create(post=post, image=image)

            invalidate_user_notification_content()
            messages.success(request, "Post created successfully.", extra_tags="post_list")
            return redirect('dogadoption_admin:post_list')
    else:
        post_form = PostForm()

    _set_post_form_barangay_source(post_form)

    return render(request, 'admin_home/create_post.html', {
        'post_form': post_form
    })


# POST LIST
@admin_required
def post_list(request):
    show_create_modal = False
    show_appointment_modal = request.method == "GET" and (
        request.GET.get("open_appointment", "").lower() in {"1", "true", "yes"}
    )
    post_form = PostForm()
    if request.method == 'POST':
        form_type = (request.POST.get("form_type") or "").strip()

        if form_type == "appointment_dates":
            show_appointment_modal = True
            dates_raw = (request.POST.get('appointment_dates') or '').strip()
            if not _validate_and_save_global_appointment_dates(dates_raw, request.user):
                messages.error(request, "Past dates are not allowed.", extra_tags="post_list")
            else:
                messages.success(request, "Appointment dates saved.", extra_tags="post_list")
                return redirect(reverse('dogadoption_admin:post_list'))
        else:
            post_form = PostForm(request.POST)
            show_create_modal = True

            if post_form.is_valid():
                post = post_form.save(commit=False)
                post.user = request.user
                post.save()

                for image in request.FILES.getlist('images'):
                    PostImage.objects.create(post=post, image=image)

                invalidate_user_notification_content()
                messages.success(request, "Post created successfully.", extra_tags="post_list")
                return redirect(reverse('dogadoption_admin:post_list'))

    _set_post_form_barangay_source(post_form)

    base_qs = Post.objects.only(
        'id',
        'caption',
        'location',
        'status',
        'rescued_date',
        'claim_days',
        'created_at',
    ).annotate(
        claim_count=Count('requests', filter=Q(requests__request_type='claim')),
        adopt_count=Count('requests', filter=Q(requests__request_type='adopt')),
    )

    # Calculate days/hours/minutes left
    all_enriched = []

    def format_posted_label(dt):
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

    for p in base_qs:
        days = hours = minutes = 0
        phase = p.current_phase()
        if phase in ['claim', 'adopt']:
            diff = p.time_left()
            total_seconds = max(int(diff.total_seconds()), 0)

            days = total_seconds // 86400
            remainder = total_seconds % 86400
            hours = remainder // 3600
            remainder = remainder % 3600
            minutes = remainder // 60

        deadline = None
        if phase == 'claim':
            deadline = p.claim_deadline()
        elif phase == 'adopt':
            deadline = p.adoption_deadline()

        all_enriched.append({
            'post': p,
            'days_left': days,
            'hours_left': hours,
            'minutes_left': minutes,
            'phase': phase,
            'posted_label': format_posted_label(p.created_at),
            'deadline_iso': deadline.isoformat() if deadline else "",
            'time_left_label': (
                f"{days:02d}d {hours:02d}h {minutes:02d}m"
                if phase in ['claim', 'adopt']
                else "No active time window"
            ),
            'claim_request_count': int(getattr(p, "claim_count", 0) or 0),
            'adopt_request_count': int(getattr(p, "adopt_count", 0) or 0),
            'claim_requests': [],
            'adopt_requests': [],
            'primary_image_url': "",
        })

    # Sort by newest
    all_enriched.sort(key=lambda x: x['post'].created_at, reverse=True)

    claim_posts = [item for item in all_enriched if item['phase'] == 'claim']
    adoption_posts = [item for item in all_enriched if item['phase'] == 'adopt']
    reunited_posts = [item for item in all_enriched if item['post'].status == 'reunited']
    adopted_posts = [item for item in all_enriched if item['post'].status == 'adopted']

    # Rank active cards by request volume (highest first). Stable sort keeps original
    # order for ties, so if equal request counts the earlier post stays first.
    claim_posts = sorted(
        claim_posts,
        key=lambda item: item['claim_request_count'],
        reverse=True,
    )
    adoption_posts = sorted(
        adoption_posts,
        key=lambda item: item['adopt_request_count'],
        reverse=True,
    )

    claim_total = len(claim_posts)
    adoption_total = len(adoption_posts)
    reunited_total = len(reunited_posts)
    adopted_total = len(adopted_posts)

    rows_per_page = 10

    def _paginate_status(items, page_param):
        paginator = Paginator(items, rows_per_page)
        page_obj = paginator.get_page(request.GET.get(page_param, 1))
        return page_obj, list(page_obj.object_list)

    def _build_page_qs(page_param, page_num):
        params = request.GET.copy()
        params[page_param] = str(page_num)
        return params.urlencode()

    claim_page_obj, claim_posts = _paginate_status(claim_posts, "claim_page")
    adoption_page_obj, adoption_posts = _paginate_status(adoption_posts, "adoption_page")
    reunited_page_obj, reunited_posts = _paginate_status(reunited_posts, "reunited_page")
    adopted_page_obj, adopted_posts = _paginate_status(adopted_posts, "adopted_page")

    modal_posts_by_id = {}
    for item in claim_posts + adoption_posts + reunited_posts + adopted_posts:
        post_id = item["post"].id
        if post_id not in modal_posts_by_id:
            modal_posts_by_id[post_id] = item
    for item in modal_posts_by_id.values():
        item["claim_requests"] = []
        item["adopt_requests"] = []
        item["primary_image_url"] = ""
        item["finalized_user_name"] = "-"
        item["finalized_user_barangay"] = "-"

    paged_post_ids = list(modal_posts_by_id.keys())
    if paged_post_ids:
        paged_requests = list(
            PostRequest.objects.filter(post_id__in=paged_post_ids)
            .select_related("user")
            .only(
                "id",
                "post_id",
                "user_id",
                "request_type",
                "status",
                "appointment_date",
                "scheduled_appointment_date",
                "created_at",
                "user__id",
                "user__username",
                "user__first_name",
                "user__last_name",
            )
            .order_by("-created_at")
        )

        requests_by_post_id = defaultdict(lambda: {"claim": [], "adopt": []})
        request_user_ids = set()
        for req in paged_requests:
            request_user_ids.add(req.user_id)
            if req.request_type in {"claim", "adopt"}:
                requests_by_post_id[req.post_id][req.request_type].append(req)

        profile_image_by_user_id = {}
        profile_address_by_user_id = {}
        face_auth_count_by_user_id = {}
        if request_user_ids:
            profiles = Profile.objects.filter(user_id__in=request_user_ids).only(
                "user_id",
                "profile_image",
                "address",
            )
            for profile in profiles:
                profile_address_by_user_id[profile.user_id] = (profile.address or "").strip()
                image_field = getattr(profile, "profile_image", None)
                if not image_field:
                    continue
                try:
                    profile_image_by_user_id[profile.user_id] = image_field.url
                except (AttributeError, ValueError):
                    continue

            face_auth_count_by_user_id = dict(
                FaceImage.objects.filter(user_id__in=request_user_ids)
                .values("user_id")
                .annotate(total=Count("id"))
                .values_list("user_id", "total")
            )

        for req in paged_requests:
            display_name = f"{(req.user.first_name or '').strip()} {(req.user.last_name or '').strip()}".strip()
            if not display_name:
                display_name = req.user.username
            req.user_display_name = display_name
            req.user_initials = _owner_initials(display_name)
            req.user_profile_image_url = profile_image_by_user_id.get(req.user_id, "")
            req.face_auth_count = face_auth_count_by_user_id.get(req.user_id, 0)

        primary_image_by_post_id = {}
        for image in PostImage.objects.filter(post_id__in=paged_post_ids).only("post_id", "image").order_by("id"):
            if image.post_id in primary_image_by_post_id:
                continue
            try:
                primary_image_by_post_id[image.post_id] = image.image.url
            except (AttributeError, ValueError):
                continue

        for post_id, item in modal_posts_by_id.items():
            req_bucket = requests_by_post_id.get(post_id)
            if req_bucket:
                item["claim_requests"] = req_bucket["claim"]
                item["adopt_requests"] = req_bucket["adopt"]
                accepted_req = None
                if item["post"].status == "reunited":
                    accepted_req = next((r for r in req_bucket["claim"] if r.status == "accepted"), None)
                elif item["post"].status == "adopted":
                    accepted_req = next((r for r in req_bucket["adopt"] if r.status == "accepted"), None)

                if accepted_req:
                    item["finalized_user_name"] = accepted_req.user_display_name
                    user_address = profile_address_by_user_id.get(accepted_req.user_id, "")
                    user_barangay = _extract_barangay_from_address(user_address)
                    if not user_barangay and user_address:
                        user_barangay = user_address.split(",")[0].strip()
                    item["finalized_user_barangay"] = user_barangay or "-"
            item["primary_image_url"] = primary_image_by_post_id.get(post_id, "")

    paged_all_posts = list(modal_posts_by_id.values())

    global_dates = _get_active_global_appointment_dates()

    return render(request, 'admin_home/post_list.html', {
        'all_posts': paged_all_posts,
        'post_form': post_form,
        'show_create_modal': show_create_modal,
        'appointment_dates': [d.strftime('%Y-%m-%d') for d in global_dates],
        'show_appointment_modal': show_appointment_modal,
        'claim_total': claim_total,
        'adoption_total': adoption_total,
        'reunited_total': reunited_total,
        'adopted_total': adopted_total,
        'claim_posts': claim_posts,
        'adoption_posts': adoption_posts,
        'reunited_posts': reunited_posts,
        'adopted_posts': adopted_posts,
        'claim_page_obj': claim_page_obj,
        'adoption_page_obj': adoption_page_obj,
        'reunited_page_obj': reunited_page_obj,
        'adopted_page_obj': adopted_page_obj,
        'claim_prev_qs': _build_page_qs("claim_page", claim_page_obj.previous_page_number()) if claim_page_obj.has_previous() else "",
        'claim_next_qs': _build_page_qs("claim_page", claim_page_obj.next_page_number()) if claim_page_obj.has_next() else "",
        'adoption_prev_qs': _build_page_qs("adoption_page", adoption_page_obj.previous_page_number()) if adoption_page_obj.has_previous() else "",
        'adoption_next_qs': _build_page_qs("adoption_page", adoption_page_obj.next_page_number()) if adoption_page_obj.has_next() else "",
        'reunited_prev_qs': _build_page_qs("reunited_page", reunited_page_obj.previous_page_number()) if reunited_page_obj.has_previous() else "",
        'reunited_next_qs': _build_page_qs("reunited_page", reunited_page_obj.next_page_number()) if reunited_page_obj.has_next() else "",
        'adopted_prev_qs': _build_page_qs("adopted_page", adopted_page_obj.previous_page_number()) if adopted_page_obj.has_previous() else "",
        'adopted_next_qs': _build_page_qs("adopted_page", adopted_page_obj.next_page_number()) if adopted_page_obj.has_next() else "",
        'return_to': request.get_full_path(),
    })


@admin_required
@require_http_methods(["GET", "POST"])
def appointment_calendar(request):
    if request.method == 'POST':
        dates_raw = (request.POST.get('appointment_dates') or '').strip()
        if not _validate_and_save_global_appointment_dates(dates_raw, request.user):
            messages.error(request, "Past dates are not allowed.")
        else:
            messages.success(request, "Appointment dates saved.")
    global_dates = _get_active_global_appointment_dates()

    return render(request, 'admin_home/appointment_calendar.html', {
        'appointment_dates': [d.strftime('%Y-%m-%d') for d in global_dates],
    })

#   CLAIM REQUESTS
@admin_required
def claim_requests(request, post_id):
    return _render_post_request_list(
        request,
        post_id,
        "claim",
        "admin_claim/claim_requests.html",
    )


# ADOPTION REQUESTS
@admin_required
def adoption_requests(request, post_id):
    return _render_post_request_list(
        request,
        post_id,
        "adopt",
        "admin_adoption/adoption_request.html",
    )


# ACCEPT / REJECT REQUEST
@admin_required
@require_POST
def update_request(request, req_id, action):
    action = (action or "").strip().lower()

    with transaction.atomic():
        req = get_object_or_404(
            PostRequest.objects.select_related("post").select_for_update(),
            id=req_id,
        )
        post = Post.objects.select_for_update().get(id=req.post_id)

        if action not in {'accept', 'reject'}:
            messages.error(request, "Unsupported action.")
            return _build_request_redirect_or_next(request, req)

        if req.status != 'pending':
            messages.warning(request, "This request has already been processed.")
            return _build_request_redirect_or_next(request, req)

        if action == 'accept':
            scheduled_date_raw = (request.POST.get('scheduled_appointment_date') or '').strip()
            if scheduled_date_raw:
                scheduled_date = parse_date(scheduled_date_raw)
                if not scheduled_date:
                    messages.error(request, "Please select a valid appointment date.")
                    return _build_request_redirect_or_next(request, req)
                is_available = GlobalAppointmentDate.objects.filter(
                    appointment_date=scheduled_date,
                    is_active=True,
                ).exists()
                if not is_available:
                    messages.error(request, "Selected appointment date is not in the available schedule.")
                    return _build_request_redirect_or_next(request, req)
            else:
                scheduled_date = req.appointment_date

            req.status = 'accepted'
            req.scheduled_appointment_date = scheduled_date

            if req.request_type == 'claim':
                post.status = 'reunited'
            elif req.request_type == 'adopt':
                post.status = 'adopted'
            post.save(update_fields=['status'])

            post.requests.filter(status='pending').exclude(id=req.id).update(
                status='rejected',
                scheduled_appointment_date=None,
            )
        else:
            req.status = 'rejected'
            req.scheduled_appointment_date = None

        reviewed_at = timezone.now()
        req.save(update_fields=['status', 'scheduled_appointment_date'])
        remember_request_reviewed_at(req.id, reviewed_at)
        invalidate_user_notification_payload(req.user_id)

    return _build_request_redirect_or_next(request, req)



# Authenticating users using face auth dashboard
@admin_required
def view_faceauth(request, user_id):
    user = get_object_or_404(User, id=user_id)

    face_images = FaceImage.objects.filter(user=user).only("image", "created_at").order_by("-created_at")
    profile = Profile.objects.filter(user=user).only(
        "user_id",
        "address",
        "age",
        "middle_initial",
        "profile_image",
    ).first()

    return render(request, 'admin_home/view_faceauth.html', {
        'user': user,
        'profile': profile,
        'face_images': face_images,
    })

#+++++++++++++++++++++ DOG CAPTURE REQUESTS  ++++++++++++++++++++++++++++=
@admin_required
@require_http_methods(["GET", "POST"])
def admin_dog_capture_requests(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_contact':
            name = (request.POST.get('contact_name') or '').strip()
            phone = (request.POST.get('contact_phone') or '').strip()
            if phone:
                DogCatcherContact.objects.create(
                    name=name,
                    phone_number=phone,
                    active=True
                )
                messages.success(request, "Dog catcher contact added.")
            else:
                messages.error(request, "Phone number is required.")

        elif action == 'toggle_contact':
            contact_id = request.POST.get('contact_id')
            contact = DogCatcherContact.objects.filter(id=contact_id).first()
            if contact:
                contact.active = not contact.active
                contact.save(update_fields=['active'])
                state = "activated" if contact.active else "deactivated"
                messages.success(request, f"Contact {state}.")

        elif action == 'delete_contact':
            contact_id = request.POST.get('contact_id')
            DogCatcherContact.objects.filter(id=contact_id).delete()
            messages.success(request, "Contact removed.")

        return redirect('dogadoption_admin:requests')

    rows_per_page = 10
    valid_tabs = {"pending", "accepted", "captured", "declined"}
    active_tab = (request.GET.get("tab") or "pending").strip().lower()
    if active_tab not in valid_tabs:
        active_tab = "pending"

    base_qs = (
        DogCaptureRequest.objects.select_related(
            'requested_by', 'requested_by__profile', 'assigned_admin'
        )
        .prefetch_related('images')
        .order_by('-created_at')
    )

    def _paginate_status(status_key, page_param):
        filtered_qs = base_qs.filter(status=status_key)
        page_obj = Paginator(filtered_qs, rows_per_page).get_page(
            request.GET.get(page_param, 1)
        )
        items = list(page_obj.object_list)
        for req in items:
            _enrich_capture_request_display(req)
        return page_obj, items, filtered_qs.count()

    pending_page_obj, pending_requests, pending_total = _paginate_status(
        "pending", "pending_page"
    )
    accepted_page_obj, accepted_requests, accepted_total = _paginate_status(
        "accepted", "accepted_page"
    )
    captured_page_obj, captured_requests, captured_total = _paginate_status(
        "captured", "captured_page"
    )
    declined_page_obj, declined_requests, declined_total = _paginate_status(
        "declined", "declined_page"
    )

    map_points_qs = list(
        base_qs.filter(
            status='accepted',
            latitude__isnull=False,
            longitude__isnull=False,
        )[:400]
    )
    map_points = []
    for req in map_points_qs:
        _enrich_capture_request_display(req)
        scheduled_iso = req.scheduled_date.date().isoformat() if req.scheduled_date else ''
        scheduled_display = req.scheduled_date.strftime('%b %d, %Y %I:%M %p') if req.scheduled_date else ''
        map_points.append({
            'id': req.id,
            'user': req.requested_by.username,
            'reason': req.get_reason_display(),
            'status': req.get_status_display(),
            'status_key': req.status,
            'lat': float(req.latitude),
            'lng': float(req.longitude),
            'created_at': req.created_at.strftime('%b %d, %Y %I:%M %p'),
            'scheduled_date_iso': scheduled_iso,
            'scheduled_date_display': scheduled_display,
            'barangay': req.display_barangay,
            'location_label': req.location_label,
            'image_url': req.preview_image_url,
        })

    return render(request, 'admin_request/request.html', {
        'requests': bool(pending_total or accepted_total or captured_total or declined_total),
        'pending_requests': pending_requests,
        'accepted_requests': accepted_requests,
        'captured_requests': captured_requests,
        'declined_requests': declined_requests,
        'pending_page_obj': pending_page_obj,
        'accepted_page_obj': accepted_page_obj,
        'captured_page_obj': captured_page_obj,
        'declined_page_obj': declined_page_obj,
        'pending_total': pending_total,
        'accepted_total': accepted_total,
        'captured_total': captured_total,
        'declined_total': declined_total,
        'active_tab': active_tab,
        'map_points': map_points,
        'contacts': DogCatcherContact.objects.all(),
    })

@admin_required
def update_dog_capture_request(request, pk):
    req = get_object_or_404(
        DogCaptureRequest.objects.select_related('requested_by', 'requested_by__profile').prefetch_related('images', 'landmark_images'),
        pk=pk
    )
    _enrich_capture_request_user(req)

    if request.method == 'POST':
        action = request.POST.get('action')

        if req.status == 'captured' and action in {'accept', 'decline'}:
            messages.warning(request, "Captured records are closed and cannot be re-opened.")
            return redirect('dogadoption_admin:update_dog_capture_request', pk=req.id)

        if action == 'accept':
            scheduled_raw = request.POST.get('scheduled_date')
            scheduled_dt = parse_datetime(scheduled_raw) if scheduled_raw else None
            if not scheduled_dt:
                messages.error(request, "Scheduled capture date is required when accepting.")
                return redirect('dogadoption_admin:update_dog_capture_request', pk=req.id)
            if scheduled_dt and timezone.is_naive(scheduled_dt):
                scheduled_dt = timezone.make_aware(
                    scheduled_dt, timezone.get_current_timezone()
                )
            req.status = 'accepted'
            req.assigned_admin = request.user
            req.scheduled_date = scheduled_dt
            req.admin_message = request.POST.get('admin_message')
            req.captured_at = None
            req.notification_scheduled_for = None
            req.notification_sent_at = None
            req.save()

            messages.success(request, "Request accepted and scheduled.")

        elif action == 'mark_captured':
            if req.status != 'accepted':
                messages.error(request, "Only scheduled requests can be marked as captured.")
                return redirect('dogadoption_admin:update_dog_capture_request', pk=req.id)

            admin_message = (request.POST.get('admin_message') or '').strip()
            req.status = 'captured'
            req.assigned_admin = request.user
            req.captured_at = timezone.now()
            if admin_message:
                req.admin_message = admin_message
            req.notification_scheduled_for = None
            req.notification_sent_at = None
            req.save()

            messages.success(request, "Request marked as captured.")

        elif action == 'decline':
            req.status = 'declined'
            req.admin_message = request.POST.get('admin_message')
            req.assigned_admin = request.user
            req.scheduled_date = None
            req.captured_at = None
            req.notification_scheduled_for = None
            req.notification_sent_at = None
            req.save()

            messages.warning(request, "Request declined.")

        return redirect('dogadoption_admin:requests')

    return render(request, 'admin_request/update_request.html', {
        'req': req
    })


#  ++++++++++++++++++++++  ANNOUNCEMENTS PAGE   ++++++++++++++++++++++++++++++++++++++
@admin_required
def announcement_list(request):
    announcements_qs = (
        DogAnnouncement.objects.select_related('created_by', 'created_by__profile')
        .prefetch_related('images')
        .order_by('-created_at')
    )
    announcements = list(announcements_qs)
    default_admin_avatar_url = static("images/officialseal.webp")
    for post in announcements:
        profile = getattr(post.created_by, "profile", None)
        image_field = getattr(profile, "profile_image", None)
        try:
            image_url = image_field.url if image_field else ""
        except Exception:
            image_url = ""
        post.admin_profile_image_url = image_url or default_admin_avatar_url

    return render(request, 'admin_announcement/announcement.html', {
        'announcements': announcements,
        'category_options': ANNOUNCEMENT_CATEGORY_OPTIONS,
    })

#   -CREATING ANNOUNCEMENTS (CATEGORY PICKER)
@admin_required
def announcement_create(request):
    return redirect("dogadoption_admin:admin_announcements")


@admin_required
@require_http_methods(["GET", "POST"])
def announcement_create_form(request, category_slug):
    category_option = ANNOUNCEMENT_CATEGORY_BY_SLUG.get(category_slug)
    if not category_option:
        raise Http404("Announcement category not found.")

    if request.method == "GET":
        return redirect("dogadoption_admin:admin_announcements")

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        content = (request.POST.get("content") or "").strip()
        background_color = (request.POST.get("background_color") or "#eeedf3").strip()
        uploaded_images = request.FILES.getlist("background_images")
        if not uploaded_images and request.FILES.get("background_image"):
            uploaded_images = [request.FILES.get("background_image")]
        schedule_raw = request.POST.get("schedule_data")
        schedule = None

        if schedule_raw:
            try:
                schedule = json.loads(schedule_raw)
            except json.JSONDecodeError:
                schedule = None

        if not content:
            messages.error(request, "Post content is required.")
            return redirect("dogadoption_admin:admin_announcements")

        primary_image = uploaded_images[0] if uploaded_images else None
        post = DogAnnouncement.objects.create(
            title=title or category_option["label"],
            content=content,
            category=category_option["value"],
            background_color=background_color,
            background_image=primary_image,
            schedule_data=schedule,
            created_by=request.user,
        )
        for image in uploaded_images[1:]:
            DogAnnouncementImage.objects.create(announcement=post, image=image)
        invalidate_user_notification_content()
        messages.success(request, f"{category_option['label']} post published.")

        return redirect("dogadoption_admin:admin_announcements")
    return redirect("dogadoption_admin:admin_announcements")


@admin_required
def announcement_edit(request, post_id):
    post = DogAnnouncement.objects.get(id=post_id)

    if request.method == "POST":
        post.title = (request.POST.get("title") or post.title).strip()
        post.content = (request.POST.get("content") or post.content).strip()
        category = request.POST.get("category", post.category)
        uploaded_images = request.FILES.getlist("background_images")
        if not uploaded_images and request.FILES.get("background_image"):
            uploaded_images = [request.FILES.get("background_image")]
        if category in ANNOUNCEMENT_CATEGORY_BY_VALUE:
            post.category = category
        post.background_color = (
            request.POST.get("background_color") or post.background_color
        )
        if uploaded_images:
            post.background_image = uploaded_images[0]
        post.save()
        if uploaded_images:
            post.images.all().delete()
            for image in uploaded_images[1:]:
                DogAnnouncementImage.objects.create(announcement=post, image=image)
        invalidate_user_notification_content()
        messages.success(request, "Announcement updated.")
        return redirect("dogadoption_admin:admin_announcements")

    return render(request, "admin_announcement/edit_announcement.html", {
        "post": post,
        "category_options": ANNOUNCEMENT_CATEGORY_OPTIONS,
    })

@admin_required
@require_POST
def announcement_update_bucket(request, post_id):
    post = get_object_or_404(DogAnnouncement.objects.only("id", "display_bucket"), id=post_id)
    bucket = (request.POST.get("bucket") or "").strip().lower()

    if bucket not in ANNOUNCEMENT_BUCKET_VALUES:
        return JsonResponse({
            "ok": False,
            "error": "Invalid announcement bucket.",
        }, status=400)

    if post.display_bucket != bucket:
        post.display_bucket = bucket
        post.save(update_fields=["display_bucket"])

    return JsonResponse({
        "ok": True,
        "bucket": post.display_bucket,
        "bucket_label": post.get_display_bucket_display(),
    })

@admin_required
@require_POST
def announcement_delete(request, post_id):
    post = get_object_or_404(DogAnnouncement, id=post_id)
    post.delete()
    invalidate_user_notification_content()
    messages.success(request, "Announcement deleted.")

    return redirect("dogadoption_admin:admin_announcements")

#++++++++++++++++++++++++++++ USER MANAGEMENT PAGE +++++++++++++++++++++++++++++++++++++
@admin_required
def admin_users(request):
    query = request.GET.get('q', '')

    users = User.objects.select_related('profile').annotate(
        calculated_violations=Count(
            'postrequest',
            filter=Q(postrequest__request_type='claim')
        )
    )

    # Search functionality
    if query:
        users = users.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )

    users = users.order_by('-calculated_violations', 'first_name')

    return render(request, 'admin_user/users.html', {
        'users': users,
        'query': query
    })

def admin_user_detail(request, id):
    user = get_object_or_404(User, id=id)
    return render(request, 'admin_user/user_detail.html', {'user': user})

def admin_user_search_results(request):
    """
    Separate template for search results
    """
    query = request.GET.get('q', '')

    results = User.objects.select_related('profile').filter(
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query) |
        Q(username__icontains=query)
    ).order_by('first_name')

    context = {
        'results': results,
        'query': query,
    }

    return render(request, 'admin_user/user_search_results.html', context)

@admin_required
def admin_edit_profile(request):
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
        user.first_name = request.POST.get("first_name", "").strip()
        user.last_name = request.POST.get("last_name", "").strip()

        profile.middle_initial = request.POST.get("middle_initial", "").strip()
        profile.address = request.POST.get("address", "").strip()
        profile.age = request.POST.get("age") or profile.age

        if request.FILES.get("profile_image"):
            profile.profile_image = request.FILES["profile_image"]

        user.save()
        profile.save()
        messages.success(request, "Profile updated successfully.")
        return redirect("dogadoption_admin:admin_edit_profile")

    return render(request, "admin_profile/edit_profile.html", {
        "profile": profile
    })


@admin_required
def admin_notifications(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "mark_all_read":
            AdminNotification.objects.filter(is_read=False).update(is_read=True)
            cache.delete(ADMIN_NOTIFICATIONS_CACHE_KEY)
        return redirect("dogadoption_admin:admin_notifications")

    notifications = AdminNotification.objects.all()
    return render(request, "admin_notifications/notifications.html", {
        "notifications": notifications,
    })


@admin_required
@require_POST
def mark_notification_read(request, pk):
    notif = get_object_or_404(AdminNotification, pk=pk)
    notif.is_read = True
    notif.save(update_fields=["is_read"])
    cache.delete(ADMIN_NOTIFICATIONS_CACHE_KEY)
    target = notif.url or "dogadoption_admin:admin_notifications"
    return redirect(target)


# ++++++++++++++++++++++++++++ Analytics Dashboard ++++++++++++++++++++++++++++++++++++++++++++++++
@admin_required
def analytics_dashboard(request):
    cached_context = cache.get(ANALYTICS_DASHBOARD_CACHE_KEY)
    if cached_context is not None:
        return render(request, "admin_analytics/dashboard.html", cached_context)

    total_users = User.objects.filter(is_staff=False).count()
    total_posts = Post.objects.count()
    total_capture_requests = DogCaptureRequest.objects.count()
    total_registrations = DogRegistration.objects.count()

    registered_owners = (
        DogRegistration.objects.exclude(owner_name__isnull=True)
        .exclude(owner_name__exact="")
        .annotate(owner_name_normalized=Lower(Trim("owner_name")))
        .values("owner_name_normalized")
        .distinct()
        .count()
    )
    adopted_dogs = Post.objects.filter(status="adopted").count()
    claimed_dogs = Post.objects.filter(status="reunited").count()
    vaccinated_dogs = (
        VaccinationRecord.objects.exclude(registration__isnull=True)
        .values("registration_id")
        .distinct()
        .count()
    )
    today = timezone.localdate()
    expired_vaccinations = (
        VaccinationRecord.objects.exclude(registration__isnull=True)
        .filter(
            Q(vaccine_expiry_date__lt=today) |
            Q(vaccination_expiry_date__lt=today)
        )
        .values("registration_id")
        .distinct()
        .count()
    )

    post_status_totals = {
        row["status"]: row["total"]
        for row in Post.objects.values("status").annotate(total=Count("id"))
    }
    post_status_labels = [label for _, label in Post.STATUS_CHOICES]
    post_status_data = [post_status_totals.get(key, 0) for key, _ in Post.STATUS_CHOICES]

    request_matrix = {}
    for row in PostRequest.objects.values("request_type", "status").annotate(total=Count("id")):
        request_matrix.setdefault(row["request_type"], {})[row["status"]] = row["total"]

    request_type_labels = [label for _, label in PostRequest.REQUEST_TYPE_CHOICES]
    request_types = [key for key, _ in PostRequest.REQUEST_TYPE_CHOICES]
    request_statuses = [key for key, _ in PostRequest.STATUS_CHOICES]
    request_status_display = {
        "pending": "Pending",
        "accepted": "Accepted",
        "rejected": "Rejected",
    }
    request_status_chart = {
        "labels": request_type_labels,
        "datasets": [
            {
                "label": request_status_display.get(status, status.title()),
                "data": [request_matrix.get(rtype, {}).get(status, 0) for rtype in request_types],
            }
            for status in request_statuses
        ],
    }

    capture_status_totals = {
        row["status"]: row["total"]
        for row in DogCaptureRequest.objects.values("status").annotate(total=Count("id"))
    }
    capture_status_labels = [label for _, label in DogCaptureRequest.STATUS_CHOICES]
    capture_status_data = [
        capture_status_totals.get(key, 0) for key, _ in DogCaptureRequest.STATUS_CHOICES
    ]

    rescue_events = []
    rescue_years = set()
    for row in (
        Post.objects.exclude(location__isnull=True)
        .exclude(location__exact="")
        .values("location", "rescued_date", "created_at")
    ):
        post_date = row["rescued_date"] or timezone.localtime(row["created_at"]).date()
        if not post_date:
            continue
        location = (row["location"] or "").strip()
        if not location:
            continue
        barangay_name = _resolve_barangay_name(location) or location
        rescue_events.append({
            "barangay": barangay_name,
            "date": post_date.isoformat(),
        })
        rescue_years.add(post_date.year)

    rescue_barangay_trend_chart = {
        "events": rescue_events,
        "years": sorted(rescue_years),
    }

    vaccination_barangay_events = []
    vaccination_years = set()
    vaccination_records = (
        VaccinationRecord.objects.select_related("registration")
        .exclude(registration__isnull=True)
    )
    for record in vaccination_records:
        registration = record.registration
        if not registration:
            continue

        barangay_name = _extract_barangay_from_address(registration.address) or "Unknown"
        vaccination_date = record.date.isoformat() if record.date else ""
        vaccine_expiry_date = (
            record.vaccine_expiry_date.isoformat() if record.vaccine_expiry_date else ""
        )
        dog_vaccination_expiry_date = (
            record.vaccination_expiry_date.isoformat()
            if record.vaccination_expiry_date else ""
        )

        if record.date:
            vaccination_years.add(record.date.year)
        if record.vaccine_expiry_date:
            vaccination_years.add(record.vaccine_expiry_date.year)
        if record.vaccination_expiry_date:
            vaccination_years.add(record.vaccination_expiry_date.year)

        vaccination_barangay_events.append({
            "registration_id": record.registration_id,
            "barangay": barangay_name,
            "vaccination_date": vaccination_date,
            "vaccine_expiry_date": vaccine_expiry_date,
            "dog_vaccination_expiry_date": dog_vaccination_expiry_date,
        })

    vaccination_barangay_chart = {
        "events": vaccination_barangay_events,
        "years": sorted(vaccination_years),
        "today": today.isoformat(),
    }

    top_barangays = (
        Dog.objects.exclude(barangay__isnull=True)
        .exclude(barangay__exact="")
        .values("barangay")
        .annotate(total=Count("id"))
        .order_by("-total")[:6]
    )
    barangay_chart = {
        "labels": [row["barangay"] for row in top_barangays],
        "data": [row["total"] for row in top_barangays],
    }

    context = {
        "registered_owners": registered_owners,
        "adopted_dogs": adopted_dogs,
        "claimed_dogs": claimed_dogs,
        "vaccinated_dogs": vaccinated_dogs,
        "expired_vaccinations": expired_vaccinations,
        "total_users": total_users,
        "total_posts": total_posts,
        "total_capture_requests": total_capture_requests,
        "total_registrations": total_registrations,
        "post_status_chart": {
            "labels": post_status_labels,
            "data": post_status_data,
        },
        "request_status_chart": request_status_chart,
        "capture_status_chart": {
            "labels": capture_status_labels,
            "data": capture_status_data,
        },
        "rescue_barangay_trend_chart": rescue_barangay_trend_chart,
        "vaccination_barangay_chart": vaccination_barangay_chart,
        "barangay_chart": barangay_chart,
    }
    cache.set(
        ANALYTICS_DASHBOARD_CACHE_KEY,
        context,
        ANALYTICS_DASHBOARD_CACHE_TTL_SECONDS,
    )
    return render(request, "admin_analytics/dashboard.html", context)

#+++++++++++++++++++++++++++++  ADMIN REGISTRATION  +++++++++++++++++++++++++++++++++++++++++


@admin_required
def register_dogs(request):
    def _registration_error(text):
        messages.error(request, text, extra_tags="registration")

    def _registration_success(text):
        messages.success(request, text, extra_tags="registration")

    # Admin-controlled barangay and date stored in session
    barangay = request.session.get('barangay', '')
    date = request.session.get('date', '')

    if request.method == 'POST':
        barangay_input = request.POST.get('barangay', barangay)
        barangay = _resolve_barangay_name(barangay_input)
        date = request.POST.get('date', date)
        request.session['barangay'] = barangay
        request.session['date'] = date

        name = request.POST.get('name', '').strip()
        species = request.POST.get('species', 'Canine').strip()
        sex = request.POST.get('sex', 'M')
        age_value_raw = (request.POST.get('age_value') or '').strip()
        age_unit = (request.POST.get('age_unit') or 'years').strip()
        neutering = request.POST.get('neutering', 'No')
        color = request.POST.get('color', '').strip()
        owner_first_name = request.POST.get('owner_first_name', '').strip()
        owner_last_name = request.POST.get('owner_last_name', '').strip()
        owner_user_id = (request.POST.get("owner_user_id") or "").strip()
        uploaded_gallery_images = [img for img in request.FILES.getlist("dog_images") if img]
        uploaded_camera_images = [img for img in request.FILES.getlist("dog_camera_images") if img]
        uploaded_desktop_camera_images = [
            img for img in request.FILES.getlist("captured_camera_images") if img
        ]
        uploaded_images = (
            uploaded_gallery_images
            + uploaded_camera_images
            + uploaded_desktop_camera_images
        )

        if not barangay:
            _registration_error("Please select a valid barangay from the suggestions.")
            return redirect('dogadoption_admin:register_dogs')

        if not name or not owner_first_name or not owner_last_name:
            _registration_error("Dog Name and Owner First/Last Name are required.")
            return redirect('dogadoption_admin:register_dogs')

        if (owner_first_name or owner_last_name) and (not owner_first_name or not owner_last_name):
            _registration_error("Please provide both owner first name and last name.")
            return redirect('dogadoption_admin:register_dogs')

        owner_name, owner_name_key, owner_user = _resolve_registration_owner_identity(
            owner_first_name,
            owner_last_name,
            owner_user_id=owner_user_id,
        )
        if not owner_name or not owner_name_key:
            _registration_error("Please provide a valid owner first name and last name.")
            return redirect('dogadoption_admin:register_dogs')

        if species not in {"Canine", "Feline"}:
            _registration_error("Please select a valid species (Canine or Feline).")
            return redirect('dogadoption_admin:register_dogs')

        try:
            age_value = int(age_value_raw)
            if age_value <= 0:
                raise ValueError
        except (TypeError, ValueError):
            _registration_error("Age must be a valid positive number.")
            return redirect('dogadoption_admin:register_dogs')

        if age_unit not in {"months", "years"}:
            _registration_error("Please select a valid age unit.")
            return redirect('dogadoption_admin:register_dogs')

        age = f"{age_value} {'mos' if age_unit == 'months' else 'yrs'}"

        image_error = _validate_registration_images(uploaded_images)
        if image_error:
            _registration_error(image_error)
            return redirect('dogadoption_admin:register_dogs')

        try:
            date_registered = datetime.strptime(date, '%Y-%m-%d').date()
        except ValueError:
            _registration_error("Invalid date format.")
            return redirect('dogadoption_admin:register_dogs')
        
        formatted_address = f"{barangay}, Bayawan City, Negros Oriental"

        with transaction.atomic():
            owner_limit_query = _build_owner_limit_query(
                owner_name_key=owner_name_key,
                owner_name=owner_name,
                owner_user=owner_user,
            )
            owner_registered_count = (
                Dog.objects.select_for_update()
                .filter(owner_limit_query)
                .distinct()
                .count()
            )
            if owner_registered_count >= DOG_REGISTRATION_OWNER_MAX_PETS:
                _registration_error(
                    (
                        f"{owner_name} already has {DOG_REGISTRATION_OWNER_MAX_PETS} "
                        f"registered pets. A maximum of {DOG_REGISTRATION_OWNER_MAX_PETS} "
                        "pets is allowed per owner."
                    ),
                )
                return redirect('dogadoption_admin:register_dogs')

            dog = Dog.objects.create(
                date_registered=date_registered,
                name=name,
                species=species,
                sex=sex,
                age=age,
                neutering_status=neutering,
                color=color,
                owner_name=owner_name,
                owner_name_key=owner_name_key,
                owner_user=owner_user,
                owner_address=formatted_address,
                barangay=barangay,
            )
            for image_file in uploaded_images:
                DogImage.objects.create(dog=dog, image=image_file)

        cache.delete("registration_record_available_years")
        cache.delete("registration_record_active_barangays")
        image_suffix = f" with {len(uploaded_images)} photo(s)" if uploaded_images else ""
        _registration_success(f"Dog '{name}' registered successfully{image_suffix}!")
        return redirect('dogadoption_admin:register_dogs')

    return render(request, 'admin_registration/registration.html', {
        'barangay': barangay,
        'date': date
    })




@admin_required
def registration_record(request):
    selected_barangay_raw = request.GET.get('barangay', '').strip()
    selected_barangay = _resolve_barangay_name(selected_barangay_raw) if selected_barangay_raw else ''
    date_filter_type = (request.GET.get('date_filter_type') or 'all').strip().lower()
    filter_date = (request.GET.get('filter_date') or '').strip()
    filter_month = (request.GET.get('filter_month') or '').strip()
    filter_year = (request.GET.get('filter_year') or '').strip()

    if date_filter_type not in {'all', 'day', 'month', 'year'}:
        date_filter_type = 'all'

    barangay_list_parsed = cache.get("registration_record_active_barangays")
    if barangay_list_parsed is None:
        barangay_list_parsed = list(
            Barangay.objects.filter(is_active=True).values_list('name', flat=True)
        )
        cache.set("registration_record_active_barangays", barangay_list_parsed, 300)

    dogs = Dog.objects.all()
    if selected_barangay:
        dogs = dogs.filter(
            barangay__iexact=selected_barangay
        )

    dogs, date_filter_type, date_filter_label = _apply_registration_date_filter(
        dogs,
        date_filter_type,
        filter_date,
        filter_month,
        filter_year,
    )

    dogs = dogs.select_related("owner_user").only(
        "id",
        "date_registered",
        "name",
        "species",
        "sex",
        "age",
        "neutering_status",
        "color",
        "owner_name",
        "owner_address",
        "owner_user_id",
    ).order_by("date_registered", "id")
    page_number = (request.GET.get("page") or "1").strip()
    paginator = Paginator(dogs, 100)
    page_obj = paginator.get_page(page_number)
    dogs = list(page_obj.object_list)

    owner_user_ids = {dog.owner_user_id for dog in dogs if dog.owner_user_id}
    owner_profile_by_user_id = {}
    if owner_user_ids:
        profiles = Profile.objects.filter(user_id__in=owner_user_ids).only("user_id", "profile_image")
        for profile in profiles:
            image_field = getattr(profile, "profile_image", None)
            if not image_field:
                continue
            try:
                image_url = image_field.url
            except (ValueError, AttributeError):
                image_url = ""
            if image_url and profile.user_id not in owner_profile_by_user_id:
                owner_profile_by_user_id[profile.user_id] = image_url

    names_without_user_profile = [
        dog.owner_name
        for dog in dogs
        if dog.owner_name and not owner_profile_by_user_id.get(dog.owner_user_id)
    ]
    owner_profile_lookup = _build_owner_profile_lookup(names_without_user_profile)
    seen_owner_keys = set()
    owner_row_number = 0
    for dog in dogs:
        normalized_owner = _normalize_person_name(dog.owner_name)
        owner_key = normalized_owner or f"dog-{dog.id}"
        dog.owner_profile_image_url = (
            owner_profile_by_user_id.get(dog.owner_user_id)
            or owner_profile_lookup.get(normalized_owner, "")
        )
        dog.owner_initials = _owner_initials(dog.owner_name)
        if owner_key in seen_owner_keys:
            dog.owner_display_number = ""
            dog.show_owner_fields = False
        else:
            owner_row_number += 1
            dog.owner_display_number = owner_row_number
            dog.show_owner_fields = True
            seen_owner_keys.add(owner_key)

    available_years = cache.get("registration_record_available_years")
    if available_years is None:
        available_years = [
            d.year for d in Dog.objects.exclude(date_registered__isnull=True)
            .dates('date_registered', 'year', order='DESC')
        ]
        cache.set("registration_record_available_years", available_years, 300)

    date_filter_params = _build_registration_filter_params(
        date_filter_type,
        filter_date,
        filter_month,
        filter_year,
    )

    date_filter_query = urlencode(date_filter_params)
    download_params = {}
    if selected_barangay:
        download_params['barangay'] = selected_barangay
    download_params.update(date_filter_params)
    download_query = urlencode(download_params)

    context = {
        'selected_barangay': selected_barangay,
        'dogs': dogs,
        'barangay_list_parsed': barangay_list_parsed,
        'date_filter_type': date_filter_type,
        'filter_date': filter_date,
        'filter_month': filter_month,
        'filter_year': filter_year,
        'date_filter_label': date_filter_label,
        'available_years': available_years,
        'date_filter_query': date_filter_query,
        'download_query': download_query,
        'page_obj': page_obj,
    }

    return render(request, 'admin_registration/registration_record.html', context)


@admin_required
def barangay_list_api(request):
    cache_key = "active_barangay_names"
    barangays = cache.get(cache_key)
    if barangays is None:
        barangays = list(Barangay.objects.filter(is_active=True).values_list('name', flat=True))
        cache.set(cache_key, barangays, 300)
    return JsonResponse({"barangays": barangays})


@admin_required
def registration_user_search_api(request):
    query = " ".join((request.GET.get("q") or "").split()).strip()
    if len(query) < 2:
        return JsonResponse({"results": []})

    cache_key = f"registration_user_search:{query.casefold()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse({"results": cached})

    tokens = query.split()
    users = User.objects.filter(is_active=True, is_staff=False)
    if len(tokens) >= 2:
        users = users.filter(
            (Q(first_name__istartswith=tokens[0]) & Q(last_name__istartswith=tokens[-1]))
            | Q(username__istartswith=query)
        )
    else:
        term = tokens[0]
        users = users.filter(
            Q(first_name__istartswith=term)
            | Q(last_name__istartswith=term)
            | Q(username__istartswith=term)
        )

    rows = users.order_by("first_name", "last_name", "id").values(
        "id",
        "first_name",
        "last_name",
        "username",
        "profile__address",
    )[:12]
    results = []
    for row in rows:
        first_name = (row.get("first_name") or "").strip()
        last_name = (row.get("last_name") or "").strip()
        username = (row.get("username") or "").strip()
        full_name = f"{first_name} {last_name}".strip()
        barangay = _extract_barangay_from_address(row.get("profile__address") or "")
        results.append(
            {
                "id": row["id"],
                "first_name": first_name,
                "last_name": last_name,
                "username": username,
                "full_name": full_name or username,
                "barangay": barangay,
            }
        )

    cache.set(cache_key, results, 60)
    return JsonResponse({"results": results})


@admin_required
def registration_dog_images_api(request, dog_id):
    dog = get_object_or_404(
        Dog.objects.select_related("owner_user").prefetch_related("images"),
        pk=dog_id,
    )
    image_urls = []
    for image_obj in dog.images.all():
        image_field = getattr(image_obj, "image", None)
        if not image_field:
            continue
        try:
            image_urls.append(image_field.url)
        except (ValueError, AttributeError):
            continue

    return JsonResponse(
        {
            "dog_id": dog.id,
            "dog_name": dog.name or "",
            "owner_name": dog.owner_name or "",
            "photos": image_urls,
        }
    )


@admin_required
def download_registration(request, file_type):
    selected_barangay_raw = request.GET.get('barangay', None)
    selected_barangay = _resolve_barangay_name(selected_barangay_raw) if selected_barangay_raw else None
    date_filter_type = (request.GET.get('date_filter_type') or 'all').strip().lower()
    filter_date = (request.GET.get('filter_date') or '').strip()
    filter_month = (request.GET.get('filter_month') or '').strip()
    filter_year = (request.GET.get('filter_year') or '').strip()

    dogs = Dog.objects.all()

    if selected_barangay:
        dogs = dogs.filter(barangay__iexact=selected_barangay)

    dogs, _, _ = _apply_registration_date_filter(
        dogs,
        date_filter_type,
        filter_date,
        filter_month,
        filter_year,
    )
    dogs = dogs.order_by("date_registered", "id")
    selected_barangay_label = selected_barangay or "All Barangays"

    # ================= EXCEL =================
    if file_type == 'excel':
        wb = Workbook()
        ws = wb.active
        ws.title = "Dog Registrations"
        ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
        ws.page_setup.paperSize = ws.PAPERSIZE_LETTER
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0

        thin = Side(style='thin', color='000000')
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        header_fill = PatternFill(fill_type='solid', fgColor='D9D9D9')
        group_fill = PatternFill(fill_type='solid', fgColor='CFCFCF')

        ws.merge_cells('A1:J1')
        ws['A1'] = 'National Rabies Prevention and Control Program'
        ws.merge_cells('A2:J2')
        ws['A2'] = 'Rabies Free Visayas Project'
        ws.merge_cells('A3:J3')
        ws['A3'] = 'Dog Registry and Vaccination Record'
        ws.merge_cells('A5:J5')
        ws['A5'] = f'Name of Barangay: {selected_barangay_label}'

        for cell_ref, size, bold in [('A1', 11, False), ('A2', 12, True), ('A3', 14, True), ('A5', 11, False)]:
            cell = ws[cell_ref]
            cell.font = Font(size=size, bold=bold)
            cell.alignment = Alignment(horizontal='center' if cell_ref != 'A5' else 'left')

        ws.merge_cells('A7:B7')
        ws['A7'] = 'Registration'
        ws.merge_cells('C7:H7')
        ws['C7'] = 'Dog Profile'
        ws.merge_cells('I7:J7')
        ws['I7'] = 'Pet Owner'

        header_labels = [
            'No.', 'Date', 'Name', 'Species', 'Sex (M/F)',
            'Age (yrs)', 'Neutering (No./C/S)', 'Color',
            'Name', 'Complete Address'
        ]
        for col, label in enumerate(header_labels, start=1):
            ws.cell(row=8, column=col, value=label)

        for col in range(1, 11):
            group_cell = ws.cell(row=7, column=col)
            group_cell.fill = group_fill
            group_cell.font = Font(size=9, bold=True)
            group_cell.alignment = Alignment(horizontal='center', vertical='center')
            group_cell.border = border

            header_cell = ws.cell(row=8, column=col)
            header_cell.fill = header_fill
            header_cell.font = Font(size=8, bold=True)
            header_cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            header_cell.border = border

        start_data_row = 9
        for idx, dog in enumerate(dogs, start=1):
            row_idx = start_data_row + idx - 1
            row_values = [
                idx,
                dog.date_registered.strftime("%m-%d-%Y") if dog.date_registered else "",
                dog.name,
                dog.species,
                dog.sex,
                dog.age,
                dog.neutering_status,
                dog.color or "-",
                dog.owner_name,
                dog.owner_address,
            ]
            for col, value in enumerate(row_values, start=1):
                cell = ws.cell(row=row_idx, column=col, value=value)
                cell.font = Font(size=8)
                cell.border = border
                if col in (1, 2, 4, 5, 6, 7):
                    cell.alignment = Alignment(horizontal='center', vertical='top', wrap_text=True)
                else:
                    cell.alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)

        last_data_row = start_data_row + max(len(dogs), 1) - 1
        legend_start_row = last_data_row + 2
        ws.cell(row=legend_start_row, column=7, value='Legend:').font = Font(size=8, bold=True)
        ws.cell(row=legend_start_row + 1, column=7, value='C - Castrated').font = Font(size=8)
        ws.cell(row=legend_start_row + 2, column=7, value='S - Spaying').font = Font(size=8)
        ws.cell(row=legend_start_row + 3, column=7, value='No - Not castrated nor spayed').font = Font(size=8)

        widths = [5, 11, 18, 10, 10, 11, 16, 13, 20, 36]
        for idx, width in enumerate(widths, start=1):
            ws.column_dimensions[chr(64 + idx)].width = width

        ws.print_title_rows = '1:8'

        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

        filename = f"Dog_Registrations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response['Content-Disposition'] = f'attachment; filename={filename}'

        wb.save(response)
        return response

    # ================= PDF =================
    elif file_type == 'pdf':
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),
            leftMargin=18,
            rightMargin=18,
            topMargin=18,
            bottomMargin=20
        )
        styles = getSampleStyleSheet()
        title_style = styles['Heading4']
        title_style.alignment = 1
        title_style.fontSize = 11
        title_style.leading = 12

        small_center = styles['Normal'].clone('small_center')
        small_center.alignment = 1
        small_center.fontSize = 10

        small_left = styles['Normal'].clone('small_left')
        small_left.alignment = 0
        small_left.fontSize = 9

        elements = [
            Paragraph("National Rabies Prevention and Control Program", small_center),
            Paragraph("<b>Rabies Free Visayas Project</b>", small_center),
            Paragraph("<b>Dog Registry and Vaccination Record</b>", title_style),
            Spacer(1, 8),
            Paragraph(f"Name of Barangay: {selected_barangay_label}", small_left),
            Spacer(1, 6),
        ]

        pdf_cell = styles['Normal'].clone('pdf_cell')
        pdf_cell.fontSize = 7
        pdf_cell.leading = 8
        pdf_cell.wordWrap = 'CJK'

        data = [[
            'Registration', '', 'Dog Profile', '', '', '', '', '', 'Pet Owner', ''
        ], [
            'No.', 'Date', 'Name', 'Species', 'Sex (M/F)', 'Age (yrs)',
            'Neutering (No./C/S)', 'Color', 'Name', 'Complete Address'
        ]]

        for idx, dog in enumerate(dogs, start=1):
            data.append([
                idx,
                dog.date_registered.strftime("%m-%d-%Y") if dog.date_registered else "",
                dog.name,
                dog.species,
                dog.sex,
                dog.age,
                dog.neutering_status,
                dog.color or "-",
                Paragraph(dog.owner_name or "", pdf_cell),
                Paragraph(dog.owner_address or "", pdf_cell),
            ])

        col_widths = [28, 48, 76, 46, 42, 44, 74, 50, 80, 242]
        table = Table(data, colWidths=col_widths, repeatRows=0)
        table.setStyle(TableStyle([
            ('SPAN', (0, 0), (1, 0)),
            ('SPAN', (2, 0), (7, 0)),
            ('SPAN', (8, 0), (9, 0)),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d0d0d0')),
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#e6e6e6')),
            ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7.5),
            ('ALIGN', (0, 0), (-1, 1), 'CENTER'),
            ('ALIGN', (0, 2), (1, -1), 'CENTER'),
            ('ALIGN', (3, 2), (7, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('WORDWRAP', (8, 2), (9, -1), 'CJK'),
            ('GRID', (0, 0), (-1, -1), 0.7, colors.black),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ]))

        elements.append(table)
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("Legend:", small_left))
        elements.append(Paragraph("C - Castrated", small_left))
        elements.append(Paragraph("S - Spaying", small_left))
        elements.append(Paragraph("No - Not castrated nor spayed", small_left))

        doc.build(elements)
        buffer.seek(0)

        response = HttpResponse(buffer, content_type='application/pdf')
        filename = f"Dog_Registrations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        response['Content-Disposition'] = f'attachment; filename={filename}'

        return response

    return HttpResponse("Invalid file type.", status=400)
#certification for dogs views.py


@admin_required
def med_record(request, registration_id):
    registration = DogRegistration.objects.get(id=registration_id)

    vaccinations = VaccinationRecord.objects.filter(
        registration=registration
    ).order_by('-date')

    dewormings = DewormingTreatmentRecord.objects.filter(
        registration=registration
    ).order_by('-date')

    current_address = (registration.address or "").strip()
    current_street = ""
    current_barangay = ""
    if current_address:
        parts = [p.strip() for p in current_address.split(",") if p.strip()]
        if len(parts) >= 3 and parts[-2].lower() == "bayawan city" and parts[-1].lower() == "negros oriental":
            current_barangay = parts[-3]
            current_street = ", ".join(parts[:-3])
        else:
            matched_barangay = _resolve_barangay_name(current_address)
            current_barangay = matched_barangay
            if matched_barangay:
                current_street = current_address.replace(matched_barangay, "").strip(" ,")

    cert_settings = CertificateSettings.objects.first()
    vaccination_defaults = {
        "vac_date": cert_settings.default_vac_date.isoformat() if cert_settings and cert_settings.default_vac_date else "",
        "vaccine_name": cert_settings.default_vaccine_name if cert_settings else "",
        "manufacturer_lot_no": cert_settings.default_manufacturer_lot_no if cert_settings else "",
        "vaccine_expiry_date": cert_settings.default_vaccine_expiry_date.isoformat() if cert_settings and cert_settings.default_vaccine_expiry_date else "",
    }

    if request.method == "POST":
        record_type = request.POST.get("record_type")

        if record_type == "update_address":
            barangay_input = request.POST.get("barangay", "")
            street_address = (request.POST.get("street_address") or "").strip()
            barangay = _resolve_barangay_name(barangay_input)

            if not barangay:
                messages.error(request, "Please select a valid barangay from the suggestions.")
                return redirect('dogadoption_admin:med_records', registration_id=registration.id)

            registration.address = (
                f"{street_address}, {barangay}, Bayawan City, Negros Oriental"
                if street_address else
                f"{barangay}, Bayawan City, Negros Oriental"
            )
            registration.save(update_fields=["address"])
            messages.success(request, "Owner address updated.")
            return redirect('dogadoption_admin:med_records', registration_id=registration.id)

        if record_type == "vaccination":
            (
                vac_date,
                vaccine_name,
                manufacturer_lot_no,
                vaccine_expiry_date,
                vaccination_expiry_date,
            ) = _get_vaccination_post_values(request)
            cert_settings = _create_vaccination_and_update_defaults(
                registration,
                cert_settings,
                vac_date,
                vaccine_name,
                manufacturer_lot_no,
                vaccine_expiry_date,
                vaccination_expiry_date,
            )

        elif record_type == "deworming":
            DewormingTreatmentRecord.objects.create(
                registration=registration,
                date=request.POST.get("dew_date"),
                medicine_given=request.POST.get("medicine_given"),
                route=request.POST.get("route"),
                frequency=request.POST.get("frequency"),
                veterinarian=request.POST.get("dew_veterinarian"),
            )

        elif record_type == "all":
            (
                vac_date,
                vaccine_name,
                manufacturer_lot_no,
                vaccine_expiry_date,
                vaccination_expiry_date,
            ) = _get_vaccination_post_values(request)
            cert_settings = _create_vaccination_and_update_defaults(
                registration,
                cert_settings,
                vac_date,
                vaccine_name,
                manufacturer_lot_no,
                vaccine_expiry_date,
                vaccination_expiry_date,
            )

            DewormingTreatmentRecord.objects.create(
                registration=registration,
                date=request.POST.get("dew_date"),
                medicine_given=request.POST.get("medicine_given"),
                route=request.POST.get("route"),
                frequency=request.POST.get("frequency"),
                veterinarian=request.POST.get("dew_veterinarian"),
            )

        return redirect('dogadoption_admin:med_records', registration_id=registration.id)

    context = {
        "registration": registration,
        "vaccinations": vaccinations,
        "dewormings": dewormings,
        "current_street": current_street,
        "current_barangay": current_barangay,
        "vaccination_defaults": vaccination_defaults,
    }

    return render(request, "admin_registration/med_record.html", context)

@admin_required
def dog_certificate(request):
    settings = CertificateSettings.objects.first()

    if request.method == "POST":
        reg_no = (request.POST.get("reg_no") or "").strip()
        breed = (request.POST.get("breed") or "").strip()
        dob_input = (request.POST.get("dob") or "").strip()
        dob_value = parse_date(dob_input) if dob_input else None
        barangay_input = request.POST.get("barangay", "")
        barangay = _resolve_barangay_name(barangay_input)
        address_line = (request.POST.get("address") or "").strip()
        owner_first_name = (request.POST.get("owner_first_name") or "").strip()
        owner_last_name = (request.POST.get("owner_last_name") or "").strip()
        owner_name = _build_owner_full_name(
            owner_first_name,
            owner_last_name,
            (request.POST.get("owner_name") or "").strip(),
        )
        status = (request.POST.get("status") or "").strip()

        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9\-/]*$", reg_no):
            messages.error(request, "Registration Number can contain only letters, numbers, dash (-), or slash (/).")
            return render(request, 'admin_registration/dog_certificate.html', {'settings': settings})

        if not breed:
            messages.error(request, "Breed is required.")
            return render(request, 'admin_registration/dog_certificate.html', {'settings': settings})

        if dob_input and not dob_value:
            messages.error(request, "Please enter a valid Date of Birth.")
            return render(request, 'admin_registration/dog_certificate.html', {'settings': settings})

        if status not in {"Castrated", "Spayed", "Intact"}:
            messages.error(request, "Please select a valid status.")
            return render(request, 'admin_registration/dog_certificate.html', {'settings': settings})

        if not owner_name:
            messages.error(request, "Owner First and Last Name are required.")
            return render(request, 'admin_registration/dog_certificate.html', {'settings': settings})

        if (owner_first_name or owner_last_name) and (not owner_first_name or not owner_last_name):
            messages.error(request, "Please provide both owner first name and last name.")
            return render(request, 'admin_registration/dog_certificate.html', {'settings': settings})

        if not barangay:
            messages.error(request, "Please select a valid barangay from the suggestions.")
            return render(request, 'admin_registration/dog_certificate.html', {'settings': settings})

        contact_no_input = (request.POST.get("contact_no") or "").strip()
        contact_no_digits = re.sub(r"\D", "", contact_no_input)

        # Accept common PH mobile formats, including spaced numbers like 0912 345 6789.
        canonical_local = ""
        if len(contact_no_digits) == 11 and contact_no_digits.startswith("09"):
            canonical_local = contact_no_digits
        elif len(contact_no_digits) == 10 and contact_no_digits.startswith("9"):
            canonical_local = f"0{contact_no_digits}"
        elif len(contact_no_digits) == 12 and contact_no_digits.startswith("639"):
            canonical_local = f"0{contact_no_digits[2:]}"

        if not re.match(r"^09\d{9}$", canonical_local):
            messages.error(request, "Use a valid PH mobile number: 09XXXXXXXXX (spaces are allowed).")
            return render(request, 'admin_registration/dog_certificate.html', {'settings': settings})

        contact_no = f"+63{canonical_local[1:]}"

        if settings:
            if settings.reg_no != reg_no:
                settings.reg_no = reg_no
                settings.save()
        else:
            settings = CertificateSettings.objects.create(reg_no=reg_no)

        registration = DogRegistration.objects.create(
            # Keep address format standardized: "<Barangay>, Bayawan City, Negros Oriental"
            reg_no=settings.reg_no,
            name_of_pet=request.POST.get('name_of_pet'),
            breed=breed,
            dob=dob_value,
            color_markings=request.POST.get('color_markings'),
            sex=request.POST.get('sex'),
            status=status,
            owner_name=owner_name,
            address=f"{address_line}, {barangay}, Bayawan City, Negros Oriental" if address_line else f"{barangay}, Bayawan City, Negros Oriental",
            contact_no=contact_no,
        )

        #  Redirect to medical record with dog ID
        return redirect('dogadoption_admin:med_records', registration_id=registration.id)

    return render(request, 'admin_registration/dog_certificate.html', {'settings': settings})

@admin_required
def certificate_print(request, pk):
    registration = get_object_or_404(DogRegistration, pk=pk)

    vaccinations = VaccinationRecord.objects.filter(
        registration=registration
    ).order_by('-date')

    dewormings = DewormingTreatmentRecord.objects.filter(
        registration=registration
    ).order_by('-date')

    context = {
        'certificate': _build_certificate_payload(
            registration,
            vaccinations=vaccinations,
            dewormings=dewormings,
            vac_limit=3,
            vac_min_rows=3,
            dew_limit=3,
            dew_min_rows=3,
        ),
    }

    return render(request, 'admin_registration/certificate_print.html', context)

@admin_required
def certificate_list(request):
    today = timezone.localdate()
    barangay_names = list(
        Barangay.objects.filter(is_active=True)
        .order_by('sort_order', 'name')
        .values_list('name', flat=True)
    )
    selected_barangay = _clean_barangay(request.GET.get('barangay'))

    medical_records_qs = (
        VaccinationRecord.objects.select_related('registration')
        .filter(registration__isnull=False)
        .order_by('-date', '-id')
    )

    if selected_barangay:
        medical_records_qs = medical_records_qs.filter(registration__address__icontains=selected_barangay)

    combined_rows = []
    for record in medical_records_qs:
        reg = record.registration
        combined_rows.append({
            'registration_id': reg.id,
            'reg_no': reg.reg_no,
            'pet_name': reg.name_of_pet,
            'owner_name': reg.owner_name,
            'barangay': _extract_barangay_from_address(reg.address) or '-',
            'address': reg.address,
            'date_issued': reg.date_registered,
            'vaccination_date': record.date,
            'vaccine_name': record.vaccine_name,
            'vaccine_expiry_date': record.vaccine_expiry_date,
            'dog_vaccination_expiry_date': record.vaccination_expiry_date,
            'is_expired': (
                record.vaccine_expiry_date < today or
                record.vaccination_expiry_date < today
            ),
        })

    page_obj = Paginator(combined_rows, 10).get_page(request.GET.get('page'))

    expired_vaccinations = (
        VaccinationRecord.objects.select_related('registration')
        .filter(
            Q(vaccine_expiry_date__lt=today) |
            Q(vaccination_expiry_date__lt=today)
        )
        .order_by('vaccine_expiry_date', 'vaccination_expiry_date')
    )

    tracker_map = {name: [] for name in barangay_names}

    for row in expired_vaccinations:
        barangay_name = _extract_barangay_from_address(row.registration.address)
        if barangay_name not in tracker_map:
            continue

        tracker_map[barangay_name].append({
            'reg_no': row.registration.reg_no,
            'owner_name': row.registration.owner_name,
            'vaccine_name': row.vaccine_name,
            'vaccine_expiry_date': row.vaccine_expiry_date,
            'dog_vaccination_expiry_date': row.vaccination_expiry_date,
        })

    barangay_expiry_tracker = [
        {
            'barangay': name,
            'expired_count': len(tracker_map[name]),
            'expired_items': tracker_map[name],
        }
        for name in barangay_names
    ]

    return render(request, 'admin_registration/certificate_list.html', {
        'page_obj': page_obj,
        'selected_barangay': selected_barangay,
        'barangay_names': barangay_names,
        'barangay_expiry_tracker': barangay_expiry_tracker,
    })


@admin_required
def export_certificates_pdf(request):
    certificates = DogRegistration.objects.all().order_by('-date_registered')

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="certificates.pdf"'

    doc = SimpleDocTemplate(response)
    data = [["Reg No", "Pet Name", "Owner", "Date Issued"]]

    for cert in certificates:
        data.append([
            cert.reg_no,
            cert.name_of_pet,
            cert.owner_name,
            cert.date_registered.strftime("%b %d, %Y")
        ])

    table = Table(data)
    doc.build([table])
    return response

@admin_required
def export_certificates_word(request):
    certificates = DogRegistration.objects.all().order_by('-date_registered')

    document = Document()
    document.add_heading('Vaccination Certificates', level=1)

    table = document.add_table(rows=1, cols=4)
    headers = ["Reg No", "Pet Name", "Owner", "Date Issued"]

    for i, header in enumerate(headers):
        table.rows[0].cells[i].text = header

    for cert in certificates:
        row_cells = table.add_row().cells
        row_cells[0].text = cert.reg_no
        row_cells[1].text = cert.name_of_pet
        row_cells[2].text = cert.owner_name
        row_cells[3].text = cert.date_registered.strftime("%b %d, %Y")

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response['Content-Disposition'] = 'attachment; filename="certificates.docx"'
    document.save(response)
    return response

@admin_required
def export_certificates_excel(request):
    certificates = DogRegistration.objects.all().order_by('-date_registered')

    wb = Workbook()
    ws = wb.active
    ws.title = "Certificates"

    ws.append(["Reg No", "Pet Name", "Owner", "Date Issued"])

    for cert in certificates:
        ws.append([
            cert.reg_no,
            cert.name_of_pet,
            cert.owner_name,
            cert.date_registered.strftime("%b %d, %Y")
        ])

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="certificates.xlsx"'
    wb.save(response)
    return response


@admin_required
def bulk_certificate_print(request):
    if request.method == "POST":
        selected_ids = [int(pk) for pk in request.POST.getlist("selected_ids") if str(pk).isdigit()]

        if not selected_ids:
            return redirect("dogadoption_admin:certificate_list")

        # ONLY fetch the selected certificates
        registrations = (
            DogRegistration.objects.filter(id__in=selected_ids)
            .prefetch_related(
                Prefetch(
                    "vaccinations",
                    queryset=VaccinationRecord.objects.order_by("-date"),
                    to_attr="vaccination_records_sorted",
                ),
                Prefetch(
                    "dewormings",
                    queryset=DewormingTreatmentRecord.objects.order_by("-date"),
                    to_attr="deworming_records_sorted",
                ),
            )
            .order_by('id')
        )

        certificates = [
            _build_certificate_payload(
                registration,
                vaccinations=getattr(registration, "vaccination_records_sorted", []),
                dewormings=getattr(registration, "deworming_records_sorted", []),
                vac_limit=3,
                vac_min_rows=3,
                dew_limit=3,
                dew_min_rows=3,
            )
            for registration in registrations
        ]

        return render(
            request,
            "admin_registration/certificate_print.html",
            {"certificates": certificates}
        )

    return redirect("dogadoption_admin:certificate_list")


# Penalty and Citation  form
def citation_create(request):
    form = CitationForm(request.POST or None)
    latest_citation = Citation.objects.order_by('-id').first()
    citations_qs = Citation.objects.select_related('owner', 'penalty') \
        .prefetch_related('penalties', 'penalties__section') \
        .order_by('-id')[:10]
    citation_rows = []
    for citation in citations_qs:
        penalties = list(citation.penalties.all())
        if not penalties and citation.penalty_id:
            penalties = [citation.penalty]
        violations = ", ".join([p.title for p in penalties]) if penalties else "-"
        total_fees = sum([p.amount for p in penalties]) if penalties else 0
        citation_rows.append({
            "citation": citation,
            "violations": violations,
            "total_fees": total_fees,
        })
    penalties = Penalty.objects.filter(active=True).select_related('section').order_by('section__number', 'number')

    if request.method == 'POST' and form.is_valid():
        selected_ids = request.POST.getlist('penalties')
        selected_penalties = list(Penalty.objects.filter(id__in=selected_ids, active=True).order_by('section__number', 'number'))

        if not selected_penalties:
            messages.error(request, 'Please select at least one violation.')
        else:
            citation = form.save(commit=False)
            # Keep backward compatibility with existing single-penalty references.
            citation.penalty = selected_penalties[0]
            citation.save()
            citation.penalties.set(selected_penalties)
            return redirect('dogadoption_admin:citation_print', citation.pk)

    return render(request, 'admin_registration/citation_form.html', {
        'form': form,
        'latest_citation': latest_citation,
        'citation_rows': citation_rows,
        'penalties': penalties,
        'selected_penalty_ids': [int(x) for x in request.POST.getlist('penalties') if str(x).isdigit()] if request.method == 'POST' else [],
    })

def citation_print(request, pk):
    citation = get_object_or_404(Citation, pk=pk)
    selected_penalties = list(citation.penalties.all().select_related('section').order_by('section__number', 'number'))
    if not selected_penalties and citation.penalty_id:
        selected_penalties = [citation.penalty]

    owner_name = "Unknown Owner"
    owner_address = "-"
    owner_barangay = "-"
    if citation.owner_id:
        try:
            owner_name = citation.owner.get_full_name().strip() or citation.owner.username
            owner_address = citation.owner.profile.address or "-"
        except Exception:
            owner_address = "-"
            owner_name = citation.owner.username

    extracted_barangay = _extract_barangay_from_address(owner_address)
    if extracted_barangay:
        owner_barangay = extracted_barangay
    elif owner_address and owner_address != "-":
        owner_barangay = owner_address.split(",")[0].strip() or "-"

    total_amount = sum((p.amount for p in selected_penalties), Decimal("0.00"))
    receipt_seed = f"{citation.id}|{citation.owner_id or 0}|{citation.date_issued.isoformat()}"
    receipt_hash = hashlib.sha256(receipt_seed.encode("utf-8")).hexdigest()[:10].upper()
    receipt_no = f"CIT-{citation.id:06d}-{receipt_hash}"

    return render(request, 'admin_registration/citation_print.html', {
        'citation': citation,
        'selected_penalties': selected_penalties,
        'owner_name': owner_name,
        'owner_address': owner_address,
        'owner_barangay': owner_barangay,
        'total_amount': total_amount,
        'receipt_no': receipt_no,
    })




def penalty_manager(request):
    editing_penalty = None
    edit_penalty_id = request.GET.get('edit_penalty')
    if str(edit_penalty_id).isdigit():
        editing_penalty = get_object_or_404(
            Penalty.objects.select_related('section'),
            pk=int(edit_penalty_id),
        )

    s_form = SectionForm()
    p_form = PenaltyForm(instance=editing_penalty) if editing_penalty else PenaltyForm()

    if request.method == 'POST':
        if 'add_section' in request.POST:
            s_form = SectionForm(request.POST)
            if s_form.is_valid():
                s_form.save()
                messages.success(request, "Section added.")
                return redirect('dogadoption_admin:penalty_manage')

        elif 'add_penalty' in request.POST:
            p_form = PenaltyForm(request.POST)
            if p_form.is_valid():
                p_form.save()
                messages.success(request, "Penalty added.")
                return redirect('dogadoption_admin:penalty_manage')

        elif 'update_penalty' in request.POST:
            penalty_id = request.POST.get('penalty_id')
            editing_penalty = get_object_or_404(Penalty, pk=penalty_id)
            p_form = PenaltyForm(request.POST, instance=editing_penalty)
            if p_form.is_valid():
                p_form.save()
                messages.success(request, "Penalty updated.")
                return redirect('dogadoption_admin:penalty_manage')

        elif 'delete_penalty' in request.POST:
            penalty_id = request.POST.get('penalty_id')
            penalty = get_object_or_404(Penalty, pk=penalty_id)
            penalty.delete()
            messages.success(request, "Penalty deleted.")
            return redirect('dogadoption_admin:penalty_manage')

    sections = list(
        PenaltySection.objects.prefetch_related('penalties').order_by('number')
    )
    total_penalties = 0
    active_penalties = 0
    for section in sections:
        section_penalties = list(section.penalties.all().order_by('number'))
        section.penalties_list = section_penalties
        total_penalties += len(section_penalties)
        active_penalties += sum(1 for penalty in section_penalties if penalty.active)

    return render(request, 'admin_registration/penalty_manage.html', {
        'sections': sections,
        's_form': s_form,
        'p_form': p_form,
        'editing_penalty': editing_penalty,
        'section_count': len(sections),
        'penalty_count': total_penalties,
        'active_penalty_count': active_penalties,
    })
