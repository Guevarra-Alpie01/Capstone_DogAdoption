"""
Authentication for staff with a VetAdminProfile row.

If auth_user.password is out of sync with the denormalized VetAdminProfile.password
hash, ModelBackend can fail; this backend re-checks using the profile hash and
syncs User.password on success.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import check_password

from dogadoption_admin.models import VetAdminProfile


class VetAdminProfileAuthBackend(BaseBackend):
    """Login for managed staff: verify against User, then against VetAdminProfile.hash."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or password is None or str(password) == "":
            return None

        uname = str(username).strip()
        if not uname:
            return None

        User = get_user_model()
        user = User.objects.filter(username__iexact=uname).first()
        if user is None:
            prof = (
                VetAdminProfile.objects.filter(username__iexact=uname)
                .select_related("user")
                .first()
            )
            if prof is not None:
                user = prof.user
        if user is None or not user.is_active or not user.is_staff:
            return None
        if not VetAdminProfile.objects.filter(user_id=user.pk).exists():
            return None

        if user.check_password(password):
            return user

        try:
            profile = user.staff_access
        except VetAdminProfile.DoesNotExist:
            return None

        if not profile.password:
            return None
        if check_password(password, profile.password):
            if user.password != profile.password:
                User.objects.filter(pk=user.pk).update(password=profile.password)
                user.password = profile.password
            return user
        return None

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
