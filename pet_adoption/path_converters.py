from django.core import signing
from django.http import Http404


def _sign_value(value, *, salt):
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        raise Http404("Invalid resource identifier.")
    return signing.dumps(str(normalized), salt=f"url-token:{salt}")


def _unsign_value(value, *, salt):
    try:
        normalized = signing.loads(value, salt=f"url-token:{salt}")
        return int(normalized)
    except (signing.BadSignature, signing.SignatureExpired, TypeError, ValueError):
        raise Http404("Invalid or expired resource link.")


def _build_converter(salt):
    class SignedIDConverter:
        regex = r"[-\w:=]+"

        def to_python(self, value):
            return _unsign_value(value, salt=salt)

        def to_url(self, value):
            if isinstance(value, str):
                try:
                    _unsign_value(value, salt=salt)
                    return value
                except Http404:
                    pass
            return _sign_value(value, salt=salt)

    return SignedIDConverter


UserIDConverter = _build_converter("user")
AdminPostIDConverter = _build_converter("admin-post")
AdoptionRequestIDConverter = _build_converter("adoption-request")
UserAdoptionPostIDConverter = _build_converter("user-adoption-post")
MissingDogPostIDConverter = _build_converter("missing-dog-post")
DogCaptureRequestIDConverter = _build_converter("dog-capture-request")
AnnouncementIDConverter = _build_converter("announcement")
RegistrationIDConverter = _build_converter("registration")
CitationIDConverter = _build_converter("citation")
NotificationIDConverter = _build_converter("notification")
