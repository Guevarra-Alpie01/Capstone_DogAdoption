from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.core.cache import cache
from django.db.models.functions import Lower, Trim
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from dogadoption_admin.models import Dog, DogAnnouncement, DogRegistration, Post, PostRequest, VaccinationRecord
from user.models import UserAdoptionPost, UserAdoptionRequest


USER_NOTIFICATIONS_CACHE_TTL_SECONDS = 20
USER_NOTIFICATIONS_MAX_ITEMS = 8
USER_NOTIFICATIONS_INCOMING_REQUEST_LIMIT = 4
USER_NOTIFICATIONS_ACCEPTED_LIMIT = 4
USER_NOTIFICATIONS_ADMIN_POST_SAMPLE_LIMIT = 2
USER_NOTIFICATIONS_ANNOUNCEMENT_SAMPLE_LIMIT = 2
USER_NOTIFICATIONS_COMMUNITY_POST_SAMPLE_LIMIT = 3
USER_NOTIFICATIONS_SEEN_SESSION_KEY = "user_notifications_seen_at"
USER_NOTIFICATIONS_READ_SESSION_KEY = "user_notifications_read_keys_v1"
USER_NOTIFICATIONS_GLOBAL_VERSION_KEY = "user_notifications_global_version_v1"
USER_NOTIFICATIONS_REQUEST_VERSION_KEY = "user_notifications_request_version_v1:{user_id}"
USER_NOTIFICATION_REQUEST_REVIEW_TS_KEY = "user_notification_request_reviewed_at_v1:{request_id}"
USER_NOTIFICATIONS_ADMIN_POST_IDS_CACHE_KEY = "user_notifications_admin_post_ids_v1"
USER_NOTIFICATIONS_ANNOUNCEMENT_IDS_CACHE_KEY = "user_notifications_announcement_ids_v1"
USER_NOTIFICATIONS_COMMUNITY_POST_IDS_CACHE_KEY = "user_notifications_community_post_ids_v1"
USER_NOTIFICATION_REVIEW_TIMESTAMP_TTL_SECONDS = 60 * 60 * 24 * 30
USER_NOTIFICATIONS_MAX_READ_KEYS = 200
USER_HOME_FEED_NAMESPACE_KEY = "user_home_feed_namespace_v1"
USER_VACCINATION_REMINDER_LEAD_DAYS = 30
USER_VACCINATION_REMINDER_MAX_ITEMS = 4


def _current_version_token():
    return timezone.now().strftime("%Y%m%d%H%M%S%f")


def _get_version_token(cache_key):
    token = cache.get(cache_key)
    if token is None:
        token = "0"
        cache.set(cache_key, token, None)
    return token


def _payload_cache_key(user_id):
    global_version = _get_version_token(USER_NOTIFICATIONS_GLOBAL_VERSION_KEY)
    request_version = _get_version_token(
        USER_NOTIFICATIONS_REQUEST_VERSION_KEY.format(user_id=user_id)
    )
    return f"user_notifications_summary_v3:{user_id}:{global_version}:{request_version}"


def invalidate_user_notification_payload(user_id):
    cache.set(
        USER_NOTIFICATIONS_REQUEST_VERSION_KEY.format(user_id=user_id),
        _current_version_token(),
        None,
    )


def remember_request_reviewed_at(request_id, reviewed_at):
    if not request_id or not reviewed_at:
        return
    cache.set(
        USER_NOTIFICATION_REQUEST_REVIEW_TS_KEY.format(request_id=request_id),
        reviewed_at.isoformat(),
        USER_NOTIFICATION_REVIEW_TIMESTAMP_TTL_SECONDS,
    )


def _get_request_reviewed_at_map(request_ids):
    if not request_ids:
        return {}
    raw_map = cache.get_many(
        [
            USER_NOTIFICATION_REQUEST_REVIEW_TS_KEY.format(request_id=request_id)
            for request_id in request_ids
        ]
    )
    reviewed_map = {}
    for request_id in request_ids:
        raw_value = raw_map.get(
            USER_NOTIFICATION_REQUEST_REVIEW_TS_KEY.format(request_id=request_id)
        )
        if not raw_value:
            continue
        try:
            parsed = datetime.fromisoformat(raw_value)
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
            reviewed_map[request_id] = parsed
        except Exception:
            continue
    return reviewed_map


def invalidate_user_notification_content():
    cache.set(USER_NOTIFICATIONS_GLOBAL_VERSION_KEY, _current_version_token(), None)
    cache.delete_many([
        USER_NOTIFICATIONS_ADMIN_POST_IDS_CACHE_KEY,
        USER_NOTIFICATIONS_ANNOUNCEMENT_IDS_CACHE_KEY,
        USER_NOTIFICATIONS_COMMUNITY_POST_IDS_CACHE_KEY,
    ])


def _normalize_notification_read_keys(raw_value):
    if not isinstance(raw_value, (list, tuple, set)):
        return []

    normalized = []
    seen = set()
    for key in raw_value:
        if not isinstance(key, str):
            continue
        normalized_key = key.strip()
        if not normalized_key or normalized_key in seen:
            continue
        seen.add(normalized_key)
        normalized.append(normalized_key)
    return normalized[:USER_NOTIFICATIONS_MAX_READ_KEYS]


def get_user_notification_read_keys(request):
    read_keys = _normalize_notification_read_keys(
        request.session.get(USER_NOTIFICATIONS_READ_SESSION_KEY, [])
    )
    if read_keys != request.session.get(USER_NOTIFICATIONS_READ_SESSION_KEY, []):
        request.session[USER_NOTIFICATIONS_READ_SESSION_KEY] = read_keys
        request.session.modified = True
    return set(read_keys)


def mark_user_notifications_read(request, notification_keys):
    normalized_existing = _normalize_notification_read_keys(
        request.session.get(USER_NOTIFICATIONS_READ_SESSION_KEY, [])
    )
    existing_set = set(normalized_existing)

    updated = list(normalized_existing)
    for key in notification_keys:
        if not isinstance(key, str):
            continue
        normalized_key = key.strip()
        if not normalized_key or normalized_key in existing_set:
            continue
        updated.append(normalized_key)
        existing_set.add(normalized_key)

    updated = updated[-USER_NOTIFICATIONS_MAX_READ_KEYS:]
    if updated != normalized_existing:
        request.session[USER_NOTIFICATIONS_READ_SESSION_KEY] = updated
        request.session.modified = True
    return existing_set


def mark_user_notification_read(request, notification_key):
    return mark_user_notifications_read(request, [notification_key])


def get_user_home_feed_namespace():
    return _get_version_token(USER_HOME_FEED_NAMESPACE_KEY)


def bump_user_home_feed_namespace():
    cache.set(USER_HOME_FEED_NAMESPACE_KEY, _current_version_token(), None)


def _cached_newest_entity_ids(cache_key, base_qs, limit):
    """Cache the newest entity ids by `created_at` (stable; avoids random resampling spikes)."""
    cached_ids = cache.get(cache_key)
    if cached_ids is not None:
        return cached_ids

    safe_limit = max(int(limit or 0), 1)
    ids = list(
        base_qs.order_by("-created_at").values_list("id", flat=True)[:safe_limit]
    )
    cache.set(cache_key, ids, USER_NOTIFICATIONS_CACHE_TTL_SECONDS)
    return ids


def _format_notification_time(dt):
    if not dt:
        return ""
    delta = timezone.now() - dt
    if delta.total_seconds() < 60:
        return "Just now"
    if delta.total_seconds() < 3600:
        minutes = max(int(delta.total_seconds() // 60), 1)
        return f"{minutes}m ago"
    if delta.total_seconds() < 86400:
        hours = max(int(delta.total_seconds() // 3600), 1)
        return f"{hours}h ago"
    if delta.days < 7:
        return f"{delta.days}d ago"
    return timezone.localtime(dt).strftime("%b %d, %Y")


def _normalize_person_name(value):
    return " ".join((value or "").split()).strip().casefold()


def _registered_dog_anchor_id(dog_id):
    return f"registered-dog-{dog_id}"


def _registered_dog_detail_url(dog_id):
    return f"{reverse('user:edit_profile')}#{_registered_dog_anchor_id(dog_id)}"


def _vaccination_effective_expiry_date(record):
    candidates = [
        expiry_date
        for expiry_date in (
            getattr(record, "vaccination_expiry_date", None),
            getattr(record, "vaccine_expiry_date", None),
        )
        if expiry_date
    ]
    return min(candidates) if candidates else None


def build_user_registered_dog_vaccination_status_map(user, dogs=None):
    if not user or not user.is_authenticated or user.is_staff:
        return {}

    registered_dogs = list(
        dogs
        if dogs is not None
        else Dog.objects.filter(owner_user=user).only(
            "id",
            "name",
            "owner_name",
            "owner_name_key",
            "date_registered",
        )
    )
    if not registered_dogs:
        return {}

    owner_keys = set()
    pet_keys = set()
    dog_signatures = {}
    for dog in registered_dogs:
        owner_key = _normalize_person_name(
            getattr(dog, "owner_name_key", "") or getattr(dog, "owner_name", "")
        )
        pet_key = _normalize_person_name(getattr(dog, "name", ""))
        signature = (owner_key, pet_key)
        dog_signatures[dog.id] = signature
        if owner_key and pet_key:
            owner_keys.add(owner_key)
            pet_keys.add(pet_key)

    if not owner_keys or not pet_keys:
        return {}

    registration_signature_by_id = {}
    registration_ids = []
    matching_registrations = DogRegistration.objects.annotate(
        owner_name_normalized=Lower(Trim("owner_name")),
        pet_name_normalized=Lower(Trim("name_of_pet")),
    ).filter(
        owner_name_normalized__in=owner_keys,
        pet_name_normalized__in=pet_keys,
    ).only("id", "owner_name", "name_of_pet")
    for registration in matching_registrations:
        signature = (
            getattr(registration, "owner_name_normalized", ""),
            getattr(registration, "pet_name_normalized", ""),
        )
        registration_signature_by_id[registration.id] = signature
        registration_ids.append(registration.id)

    if not registration_ids:
        return {}

    latest_vaccination_by_signature = {}
    vaccinations = (
        VaccinationRecord.objects.filter(registration_id__in=registration_ids)
        .only(
            "id",
            "registration_id",
            "date",
            "vaccine_name",
            "vaccine_expiry_date",
            "vaccination_expiry_date",
        )
        .order_by("-date", "-id")
    )
    for vaccination in vaccinations:
        signature = registration_signature_by_id.get(vaccination.registration_id)
        if signature and signature not in latest_vaccination_by_signature:
            latest_vaccination_by_signature[signature] = vaccination

    today = timezone.localdate()
    status_map = {}
    for dog in registered_dogs:
        signature = dog_signatures.get(dog.id)
        vaccination = latest_vaccination_by_signature.get(signature)
        expiry_date = _vaccination_effective_expiry_date(vaccination) if vaccination else None
        days_until_expiry = (expiry_date - today).days if expiry_date else None
        has_vaccination_record = vaccination is not None and expiry_date is not None

        if not has_vaccination_record:
            status_key = "no_record"
            status_label = "No Vaccination Record"
            status_message = "No vaccination record is on file yet for this registered dog."
        elif expiry_date < today:
            status_key = "expired"
            status_label = "Expired"
            status_message = f"Vaccination expired on {expiry_date.strftime('%b %d, %Y')}."
        elif days_until_expiry <= USER_VACCINATION_REMINDER_LEAD_DAYS:
            status_key = "due_soon"
            status_label = "Due Soon"
            day_word = "day" if days_until_expiry == 1 else "days"
            status_message = (
                f"Vaccination expires in {days_until_expiry} {day_word} "
                f"on {expiry_date.strftime('%b %d, %Y')}."
            )
        else:
            status_key = "active"
            status_label = "Active"
            status_message = f"Vaccination is active until {expiry_date.strftime('%b %d, %Y')}."

        status_map[dog.id] = {
            "has_vaccination_record": has_vaccination_record,
            "vaccination_date": getattr(vaccination, "date", None),
            "expiry_date": expiry_date,
            "days_until_expiry": days_until_expiry,
            "status_key": status_key,
            "status_label": status_label,
            "status_message": status_message,
            "detail_url": _registered_dog_detail_url(dog.id),
            "anchor_id": _registered_dog_anchor_id(dog.id),
        }

    return status_map


def build_user_vaccination_reminders(user, *, limit=USER_VACCINATION_REMINDER_MAX_ITEMS):
    dogs = list(
        Dog.objects.filter(owner_user=user).only(
            "id", "name", "owner_name", "owner_name_key", "date_registered",
        )
    )
    status_map = build_user_registered_dog_vaccination_status_map(user, dogs=dogs)
    if not status_map:
        return []

    reminder_rows = []
    for dog in dogs:
        status = status_map.get(dog.id)
        if not status or status["status_key"] not in {"expired", "due_soon"}:
            continue
        reminder_rows.append({
            "dog_id": dog.id,
            "pet_name": (dog.name or "Unnamed Dog").strip() or "Unnamed Dog",
            "status_key": status["status_key"],
            "status_label": status["status_label"],
            "expiry_date": status["expiry_date"],
            "days_until_expiry": status["days_until_expiry"],
            "message": status["status_message"],
            "detail_url": status["detail_url"],
            "anchor_id": status["anchor_id"],
            "vaccination_date": status["vaccination_date"],
        })

    reminder_rows.sort(
        key=lambda row: (
            0 if row["status_key"] == "expired" else 1,
            row["days_until_expiry"] if row["days_until_expiry"] is not None else 10**6,
            row["pet_name"].casefold(),
        )
    )
    if limit is not None:
        reminder_rows = reminder_rows[:limit]
    return reminder_rows


def build_user_vaccination_reminder_summary(user):
    reminders = build_user_vaccination_reminders(user, limit=None)
    return {
        "items": reminders[:USER_VACCINATION_REMINDER_MAX_ITEMS],
        "expired_count": sum(1 for item in reminders if item["status_key"] == "expired"),
        "due_soon_count": sum(1 for item in reminders if item["status_key"] == "due_soon"),
        "profile_url": f"{reverse('user:edit_profile')}#registered",
    }


def _post_phase_url(post):
    return reverse("user:post_detail", args=[post.id])


def _build_request_acceptance_items(user):
    requests = list(
        PostRequest.objects.filter(
            user_id=user.id,
            status="accepted",
        )
        .select_related("post")
        .only(
            "id",
            "request_type",
            "scheduled_appointment_date",
            "created_at",
            "post_id",
            "post__caption",
            "post__location",
        )
        .order_by("-created_at")[:USER_NOTIFICATIONS_ACCEPTED_LIMIT]
    )
    reviewed_at_map = _get_request_reviewed_at_map([req.id for req in requests])

    items = []
    for req in requests:
        reviewed_at = reviewed_at_map.get(req.id, req.created_at)
        label = "Claim request accepted" if req.request_type == "claim" else "Adoption request accepted"
        destination = reverse("user:my_claims") if req.request_type == "claim" else reverse("user:adopt_status")
        schedule_text = (
            f" Appointment: {req.scheduled_appointment_date.strftime('%b %d, %Y')}."
            if req.scheduled_appointment_date
            else ""
        )
        items.append({
            "key": f"accepted-request-{req.id}",
            "kind": "accepted_request",
            "title": label,
            "message": f"{strip_tags(req.post.caption)[:72]}{schedule_text}",
            "url": destination,
            "created_at": reviewed_at,
            "created_label": _format_notification_time(reviewed_at),
        })
    return items


def _build_incoming_user_request_items(user):
    requests = list(
        UserAdoptionRequest.objects.filter(
            post__owner_id=user.id,
            status="pending",
        )
        .select_related("post", "requester")
        .only(
            "id",
            "created_at",
            "post_id",
            "post__dog_name",
            "requester_id",
            "requester__username",
        )
        .order_by("-created_at")[:USER_NOTIFICATIONS_INCOMING_REQUEST_LIMIT]
    )

    items = []
    for req in requests:
        dog_name = (req.post.dog_name or "this dog").strip() or "this dog"
        items.append({
            "key": f"incoming-user-request-{req.id}",
            "kind": "incoming_user_request",
            "title": "New adoption request",
            "message": f"{req.requester.username} wants to adopt {dog_name}.",
            "url": reverse("user:user_adoption_requests"),
            "created_at": req.created_at,
            "created_label": _format_notification_time(req.created_at),
        })
    return items


def _build_announcement_items():
    announcement_ids = _cached_newest_entity_ids(
        USER_NOTIFICATIONS_ANNOUNCEMENT_IDS_CACHE_KEY,
        DogAnnouncement.objects.filter(created_by__is_staff=True),
        USER_NOTIFICATIONS_ANNOUNCEMENT_SAMPLE_LIMIT,
    )
    announcements = {
        announcement.id: announcement
        for announcement in DogAnnouncement.objects.select_related("created_by")
        .only("id", "title", "content", "created_at", "created_by__username")
        .filter(id__in=announcement_ids)
    }

    items = []
    for announcement_id in announcement_ids:
        announcement = announcements.get(announcement_id)
        if not announcement:
            continue
        content_preview = strip_tags(announcement.content or "").strip()
        if len(content_preview) > 90:
            content_preview = f"{content_preview[:87].rstrip()}..."
        items.append({
            "key": f"announcement-{announcement.id}",
            "kind": "announcement",
            "title": "New update from admin staff",
            "message": announcement.title or content_preview or "New official announcement.",
            "url": reverse("user:announcement_detail", args=[announcement.id]),
            "created_at": announcement.created_at,
            "created_label": _format_notification_time(announcement.created_at),
        })
    return items


def _build_admin_post_items():
    admin_post_ids = _cached_newest_entity_ids(
        USER_NOTIFICATIONS_ADMIN_POST_IDS_CACHE_KEY,
        Post.objects.filter(user__is_staff=True),
        USER_NOTIFICATIONS_ADMIN_POST_SAMPLE_LIMIT,
    )
    posts = {
        post.id: post
        for post in Post.objects.select_related("user")
        .only("id", "caption", "location", "status", "claim_days", "created_at", "user_id")
        .filter(id__in=admin_post_ids)
    }

    items = []
    for post_id in admin_post_ids:
        post = posts.get(post_id)
        if not post:
            continue
        message = strip_tags(post.caption or "").strip()[:90]
        items.append({
            "key": f"admin-post-{post.id}",
            "kind": "admin_post",
            "title": "New admin dog post",
            "message": message or "A rescued dog post was published by the admin staff.",
            "url": _post_phase_url(post),
            "created_at": post.created_at,
            "created_label": _format_notification_time(post.created_at),
        })
    return items


def _build_community_post_items(user):
    community_post_ids = _cached_newest_entity_ids(
        USER_NOTIFICATIONS_COMMUNITY_POST_IDS_CACHE_KEY,
        UserAdoptionPost.objects.filter(status="available"),
        USER_NOTIFICATIONS_COMMUNITY_POST_SAMPLE_LIMIT,
    )
    community_posts = {
        post.id: post
        for post in UserAdoptionPost.objects.select_related("owner")
        .only("id", "dog_name", "location", "created_at", "owner_id", "owner__username")
        .filter(id__in=community_post_ids)
        .exclude(owner_id=user.id)
    }

    items = []
    for post_id in community_post_ids:
        post = community_posts.get(post_id)
        if not post:
            continue
        location = f" in {post.location}" if post.location else ""
        items.append({
            "key": f"community-post-{post.id}",
            "kind": "community_post",
            "title": "Random community post",
            "message": f"{post.owner.username} posted {post.dog_name}{location}.",
            "url": reverse("user:user_home"),
            "created_at": post.created_at,
            "created_label": _format_notification_time(post.created_at),
        })
    return items


def _build_vaccination_reminder_items(user):
    reminders = build_user_vaccination_reminders(user, limit=USER_VACCINATION_REMINDER_MAX_ITEMS)
    if not reminders:
        return []

    now = timezone.now()
    total = len(reminders)
    items = []
    for index, reminder in enumerate(reminders):
        created_at = now + timedelta(minutes=total - index)
        if reminder["status_key"] == "expired":
            kind = "vaccination_expired"
            title = "Vaccination expired"
            message = (
                f"{reminder['pet_name']}'s vaccination expired on "
                f"{reminder['expiry_date'].strftime('%b %d, %Y')}."
            )
            created_label = f"Expired {reminder['expiry_date'].strftime('%b %d, %Y')}"
        else:
            kind = "vaccination_due"
            days_left = reminder["days_until_expiry"]
            day_word = "day" if days_left == 1 else "days"
            title = "Vaccination due soon"
            message = (
                f"{reminder['pet_name']}'s vaccination expires in {days_left} {day_word} "
                f"on {reminder['expiry_date'].strftime('%b %d, %Y')}."
            )
            created_label = f"Due {reminder['expiry_date'].strftime('%b %d, %Y')}"

        items.append({
            "key": f"{kind}-{reminder['dog_id']}-{reminder['expiry_date'].isoformat()}",
            "kind": kind,
            "title": title,
            "message": message,
            "url": reminder["detail_url"],
            "created_at": created_at,
            "created_label": created_label,
        })
    return items


def build_user_notification_summary(request):
    """Build badge count and dropdown rows, applying per-session read keys to cached payload."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or user.is_staff:
        return {"unread_count": 0, "notifications": []}

    payload = build_user_notification_payload(user)
    read_keys = get_user_notification_read_keys(request)
    notifications = []
    unread_count = 0
    for item in payload.get("items", []):
        notification_key = (item.get("key", "") or "").strip()
        target_url = item.get("url") or reverse("user:user_home")
        is_unread = bool(notification_key and notification_key not in read_keys)
        if is_unread:
            unread_count += 1
        notifications.append({
            "kind": item.get("kind", "notification"),
            "key": notification_key,
            "title": item.get("title", ""),
            "message": item.get("message", ""),
            "url": target_url,
            "created_label": item.get("created_label", ""),
            "is_unread": is_unread,
            "open_url": "{}?{}".format(
                reverse("user:open_notification"),
                urlencode({"key": notification_key, "next": target_url}),
            ),
        })
    return {
        "unread_count": unread_count,
        "notifications": notifications,
    }


def build_user_notification_payload(user):
    if not user or not user.is_authenticated or user.is_staff:
        return {"items": []}

    cache_key = _payload_cache_key(user.id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    items = []
    seen_keys = set()
    for bucket in (
        _build_incoming_user_request_items(user),
        _build_request_acceptance_items(user),
        _build_vaccination_reminder_items(user),
        _build_announcement_items(),
        _build_admin_post_items(),
        _build_community_post_items(user),
    ):
        for item in bucket:
            if item["key"] in seen_keys:
                continue
            seen_keys.add(item["key"])
            items.append(item)

    items.sort(key=lambda item: item["created_at"] or timezone.now(), reverse=True)
    payload = {"items": items[:USER_NOTIFICATIONS_MAX_ITEMS]}
    cache.set(cache_key, payload, USER_NOTIFICATIONS_CACHE_TTL_SECONDS)
    return payload
