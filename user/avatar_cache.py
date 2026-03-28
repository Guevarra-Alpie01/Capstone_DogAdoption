from django.core.cache import cache
from django.templatetags.static import static

from .models import Profile


USER_AVATAR_CACHE_TTL_SECONDS = 600
DEFAULT_AVATAR_URL = static("images/default-user-image.jpg")


def _user_avatar_cache_key(user_id):
    return f"user_avatar_url:{user_id}"


def get_cached_profile_avatar_url(user, default_url=DEFAULT_AVATAR_URL):
    user_id = getattr(user, "id", None)
    if not user_id:
        return default_url

    cache_key = _user_avatar_cache_key(user_id)
    cached_url = cache.get(cache_key)
    if cached_url is not None:
        return cached_url

    avatar_url = default_url
    profile = Profile.objects.only("profile_image").filter(user_id=user_id).first()
    if profile and getattr(profile, "profile_image", None):
        try:
            avatar_url = profile.profile_image.url
        except Exception:
            avatar_url = default_url

    cache.set(cache_key, avatar_url, USER_AVATAR_CACHE_TTL_SECONDS)
    return avatar_url


def invalidate_cached_profile_avatar(user_id):
    if user_id:
        cache.delete(_user_avatar_cache_key(user_id))
