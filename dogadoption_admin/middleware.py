# middleware.py
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.utils.deprecation import MiddlewareMixin


class AdminSessionMiddleware(MiddlewareMixin):
    SESSION_USER_CACHE_KEY_PREFIX = "admin_session_user_v1"
    USER_OBJECT_CACHE_KEY_PREFIX = "admin_user_object_v1"
    SESSION_USER_CACHE_TTL_SECONDS = 300
    USER_OBJECT_CACHE_TTL_SECONDS = 60

    @staticmethod
    def _session_user_cache_key(session_key):
        return f"{AdminSessionMiddleware.SESSION_USER_CACHE_KEY_PREFIX}:{session_key}"

    @staticmethod
    def _user_object_cache_key(user_id):
        return f"{AdminSessionMiddleware.USER_OBJECT_CACHE_KEY_PREFIX}:{user_id}"

    def process_request(self, request):
        if request.user.is_authenticated:
            # Already logged in, nothing to do
            return

        if not request.path.startswith('/vetadmin/'):
            return

        session_key = request.COOKIES.get('admin_sessionid')
        if not session_key:
            return

        session_user_cache_key = self._session_user_cache_key(session_key)
        user_id = cache.get(session_user_cache_key)

        if user_id is None:
            session = Session.objects.filter(session_key=session_key).first()
            if not session:
                return

            data = session.get_decoded()
            user_id = data.get('_auth_user_id')
            if not user_id:
                return

            cache.set(
                session_user_cache_key,
                user_id,
                self.SESSION_USER_CACHE_TTL_SECONDS,
            )

        if not user_id:
            return

        user_cache_key = self._user_object_cache_key(user_id)
        user = cache.get(user_cache_key)
        if user is None:
            User = get_user_model()
            user = (
                User.objects.select_related("profile")
                .filter(pk=user_id, is_active=True, is_staff=True)
                .first()
            )
            if not user:
                return
            cache.set(
                user_cache_key,
                user,
                self.USER_OBJECT_CACHE_TTL_SECONDS,
            )

        request.user = user
        request._cached_user = user
