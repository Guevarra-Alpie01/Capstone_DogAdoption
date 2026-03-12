import random
from datetime import datetime

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from dogadoption_admin.models import DogAnnouncement, Post, PostRequest
from user.models import UserAdoptionPost, UserAdoptionRequest


USER_NOTIFICATIONS_CACHE_TTL_SECONDS = 20
USER_NOTIFICATIONS_MAX_ITEMS = 8
USER_NOTIFICATIONS_INCOMING_REQUEST_LIMIT = 4
USER_NOTIFICATIONS_ACCEPTED_LIMIT = 4
USER_NOTIFICATIONS_ADMIN_POST_CANDIDATE_LIMIT = 80
USER_NOTIFICATIONS_ADMIN_POST_SAMPLE_LIMIT = 2
USER_NOTIFICATIONS_ANNOUNCEMENT_CANDIDATE_LIMIT = 80
USER_NOTIFICATIONS_ANNOUNCEMENT_SAMPLE_LIMIT = 2
USER_NOTIFICATIONS_COMMUNITY_POST_CANDIDATE_LIMIT = 120
USER_NOTIFICATIONS_COMMUNITY_POST_SAMPLE_LIMIT = 3
USER_NOTIFICATIONS_SEEN_SESSION_KEY = "user_notifications_seen_at"
USER_NOTIFICATIONS_GLOBAL_VERSION_KEY = "user_notifications_global_version_v1"
USER_NOTIFICATIONS_REQUEST_VERSION_KEY = "user_notifications_request_version_v1:{user_id}"
USER_NOTIFICATION_REQUEST_REVIEW_TS_KEY = "user_notification_request_reviewed_at_v1:{request_id}"
USER_NOTIFICATIONS_ADMIN_POST_IDS_CACHE_KEY = "user_notifications_admin_post_ids_v1"
USER_NOTIFICATIONS_ANNOUNCEMENT_IDS_CACHE_KEY = "user_notifications_announcement_ids_v1"
USER_NOTIFICATIONS_COMMUNITY_POST_IDS_CACHE_KEY = "user_notifications_community_post_ids_v1"
USER_NOTIFICATION_REVIEW_TIMESTAMP_TTL_SECONDS = 60 * 60 * 24 * 30
USER_HOME_FEED_NAMESPACE_KEY = "user_home_feed_namespace_v1"


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


def get_user_home_feed_namespace():
    return _get_version_token(USER_HOME_FEED_NAMESPACE_KEY)


def bump_user_home_feed_namespace():
    cache.set(USER_HOME_FEED_NAMESPACE_KEY, _current_version_token(), None)


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
    cache.set(cache_key, sampled_ids, USER_NOTIFICATIONS_CACHE_TTL_SECONDS)
    return sampled_ids


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
    announcement_ids = _sample_recent_ids_with_cache(
        USER_NOTIFICATIONS_ANNOUNCEMENT_IDS_CACHE_KEY,
        DogAnnouncement.objects.filter(created_by__is_staff=True),
        USER_NOTIFICATIONS_ANNOUNCEMENT_CANDIDATE_LIMIT,
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
    admin_post_ids = _sample_recent_ids_with_cache(
        USER_NOTIFICATIONS_ADMIN_POST_IDS_CACHE_KEY,
        Post.objects.filter(user__is_staff=True),
        USER_NOTIFICATIONS_ADMIN_POST_CANDIDATE_LIMIT,
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
    community_post_ids = _sample_recent_ids_with_cache(
        USER_NOTIFICATIONS_COMMUNITY_POST_IDS_CACHE_KEY,
        UserAdoptionPost.objects.filter(status="available"),
        USER_NOTIFICATIONS_COMMUNITY_POST_CANDIDATE_LIMIT,
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
