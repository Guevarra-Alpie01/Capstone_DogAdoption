# middleware.py
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.utils.deprecation import MiddlewareMixin

class AdminSessionMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.user.is_authenticated:
            # Already logged in, nothing to do
            return

        session_key = request.COOKIES.get('admin_sessionid')
        if not session_key:
            return

        session = Session.objects.filter(session_key=session_key).first()
        if not session:
            return

        data = session.get_decoded()
        user_id = data.get('_auth_user_id')
        if not user_id:
            return

        User = get_user_model()
        try:
            user = User.objects.get(pk=user_id)
            request.user = user
        except User.DoesNotExist:
            pass
