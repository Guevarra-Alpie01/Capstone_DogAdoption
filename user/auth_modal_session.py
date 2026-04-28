"""Session flash and redirects for auth modal flows (avoid full-page swap to home on errors)."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

AUTH_MODAL_LOGIN_ERROR_SESSION_KEY = "auth_modal_login_error"
AUTH_MODAL_LOGIN_USERNAME_SESSION_KEY = "auth_modal_login_username"
AUTH_MODAL_SIGNUP_ERROR_SESSION_KEY = "auth_modal_signup_error"
AUTH_MODAL_SIGNUP_FORM_DATA_SESSION_KEY = "auth_modal_signup_form_data"


def safe_next_url(request, raw_value=""):
    """Return a safe in-app continuation URL or an empty string."""
    next_url = (raw_value or "").strip()
    if not next_url:
        return ""
    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return ""


def merge_query_params(url, updates):
    """Merge keys into url's query string (relative URLs supported)."""
    parts = urlsplit(url)
    pairs = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in updates.items():
        pairs[key] = value
    new_query = urlencode(pairs)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def build_home_auth_modal_url(request, auth_modal="login", next_url=""):
    """Build a safe home-page URL that opens an auth modal."""
    modal = auth_modal if auth_modal in {"login", "signup"} else "login"
    query = {"auth_modal": modal}
    safe_next = safe_next_url(request, next_url)
    if safe_next:
        query["next"] = safe_next
    return "{}?{}".format(reverse("user:user_home"), urlencode(query))


def flash_modal_login_error(request, message, username=""):
    request.session[AUTH_MODAL_LOGIN_ERROR_SESSION_KEY] = message
    request.session[AUTH_MODAL_LOGIN_USERNAME_SESSION_KEY] = username or ""
    request.session.modified = True


def flash_modal_signup_error(request, message, signup_form_data=None):
    """Store signup validation error + safe field echoes for modal reopen on redirect."""
    request.session[AUTH_MODAL_SIGNUP_ERROR_SESSION_KEY] = message
    if signup_form_data is not None:
        request.session[AUTH_MODAL_SIGNUP_FORM_DATA_SESSION_KEY] = dict(signup_form_data)
    else:
        request.session.pop(AUTH_MODAL_SIGNUP_FORM_DATA_SESSION_KEY, None)
    request.session.modified = True


def redirect_modal_login_error(request, *, message, username, next_url):
    """Redirect back to ``next`` (or home) with login modal and flashed error in session."""
    flash_modal_login_error(request, message, username)
    safe_next = safe_next_url(request, next_url)
    if safe_next:
        return redirect(merge_query_params(safe_next, {"auth_modal": "login"}))
    return redirect(build_home_auth_modal_url(request, "login", next_url))


def redirect_modal_signup_error(request, *, message, signup_form_data, next_url):
    """Redirect back like login: stay on page (via ?next) and reopen signup with error."""
    flash_modal_signup_error(request, message, signup_form_data)
    safe_next = safe_next_url(request, next_url)
    if safe_next:
        return redirect(merge_query_params(safe_next, {"auth_modal": "signup"}))
    return redirect(build_home_auth_modal_url(request, "signup", next_url))
