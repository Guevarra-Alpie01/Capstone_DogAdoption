import json
import logging
from time import perf_counter, time
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.utils.deprecation import MiddlewareMixin

from .observability import runtime_metrics


class RequestObservabilityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger("pet_adoption.request")

    def __call__(self, request):
        started_at = perf_counter()
        response = None
        raised_exception = None
        request_id = (request.headers.get("X-Request-ID") or "").strip() or uuid4().hex
        request.request_id = request_id

        try:
            response = self.get_response(request)
            return response
        except Exception as exc:
            raised_exception = exc
            raise
        finally:
            elapsed_ms = round((perf_counter() - started_at) * 1000.0, 2)
            status_code = getattr(response, "status_code", 500)
            resolver_match = getattr(request, "resolver_match", None)
            route_name = getattr(resolver_match, "view_name", "") or request.path
            user = getattr(request, "user", None)
            user_id = getattr(user, "id", None)

            runtime_metrics.record(
                method=request.method,
                route=route_name,
                status_code=status_code,
                latency_ms=elapsed_ms,
            )

            payload = {
                "event": "request.completed",
                "request_id": request_id,
                "method": request.method,
                "path": request.path,
                "route": route_name,
                "status_code": status_code,
                "latency_ms": elapsed_ms,
                "user_id": user_id,
                "is_authenticated": bool(getattr(user, "is_authenticated", False)),
            }
            self.logger.info(
                json.dumps(payload, sort_keys=True),
                exc_info=raised_exception is not None,
            )

            if response is not None:
                response["X-Request-ID"] = request_id


class RequestRateLimitMiddleware(MiddlewareMixin):
    MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
    AUTH_ROUTE_NAMES = {
        "user:login",
        "user:signup",
        "user:signup_complete",
        "user:save_face",
        "user:reset_signup_capture",
        "dogadoption_admin:admin_login",
    }
    INTERACTION_ROUTE_NAMES = {
        "user:announcement_react",
        "user:announcement_comment",
        "user:mark_notifications_seen",
        "dogadoption_admin:notification_read",
        "dogadoption_admin:announcement_update_bucket",
    }
    SUBMISSION_ROUTE_NAMES = {
        "user:user_home",
        "user:create_post",
        "user:adopt_user_post",
        "user:adopt_confirm",
        "user:claim_confirm",
        "user:dog_capture_request",
        "user:edit_dog_capture_request",
        "user:delete_dog_capture_request",
        "user:delete_user_adoption_post",
        "user:delete_missing_dog_post",
        "dogadoption_admin:create_post",
        "dogadoption_admin:update_request",
        "dogadoption_admin:requests",
        "dogadoption_admin:update_dog_capture_request",
        "dogadoption_admin:register_dogs",
        "dogadoption_admin:med_records",
        "dogadoption_admin:citation_create",
        "dogadoption_admin:penalty_manage",
        "dogadoption_admin:announcement_create",
        "dogadoption_admin:announcement_create_form",
        "dogadoption_admin:announcement_edit",
        "dogadoption_admin:announcement_delete",
        "dogadoption_admin:admin_edit_profile",
    }

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not getattr(settings, "RATE_LIMIT_ENABLED", True):
            return None
        if request.method not in self.MUTATING_METHODS:
            return None

        resolver_match = getattr(request, "resolver_match", None)
        route_name = getattr(resolver_match, "view_name", "") or request.path
        bucket_name, limit = self._policy_for_route(route_name)
        if limit <= 0:
            return None

        window_seconds = max(int(getattr(settings, "RATE_LIMIT_WINDOW_SECONDS", 60)), 1)
        identity = self._request_identity(request)
        current_time = int(time())
        period = current_time // window_seconds
        cache_key = f"rate_limit:{bucket_name}:{identity}:{period}"

        count = self._increment_counter(cache_key, window_seconds)
        if count <= limit:
            return None

        retry_after = max(window_seconds - (current_time % window_seconds), 1)
        return self._rate_limited_response(request, retry_after)

    def _policy_for_route(self, route_name):
        if route_name in self.AUTH_ROUTE_NAMES:
            return "auth", int(getattr(settings, "RATE_LIMIT_AUTH_REQUESTS", 10))
        if route_name in self.INTERACTION_ROUTE_NAMES:
            return "interaction", int(getattr(settings, "RATE_LIMIT_INTERACTION_REQUESTS", 30))
        if route_name in self.SUBMISSION_ROUTE_NAMES:
            return "submission", int(getattr(settings, "RATE_LIMIT_SUBMISSION_REQUESTS", 12))
        return "default", int(getattr(settings, "RATE_LIMIT_DEFAULT_REQUESTS", 60))

    def _increment_counter(self, cache_key, timeout_seconds):
        if cache.add(cache_key, 1, timeout=timeout_seconds):
            return 1
        try:
            return cache.incr(cache_key)
        except Exception:
            current_value = int(cache.get(cache_key) or 0) + 1
            cache.set(cache_key, current_value, timeout=timeout_seconds)
            return current_value

    def _request_identity(self, request):
        user = getattr(request, "user", None)
        user_part = f"user:{getattr(user, 'pk', '')}" if getattr(user, "is_authenticated", False) else "anon"
        forwarded_for = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
        client_ip = (
            forwarded_for
            or (request.META.get("HTTP_X_REAL_IP") or "").strip()
            or (request.META.get("REMOTE_ADDR") or "").strip()
            or "unknown"
        )
        return f"{user_part}:{client_ip}"

    def _rate_limited_response(self, request, retry_after):
        message = f"Too many requests. Please wait {retry_after} seconds and try again."
        wants_json = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or "application/json" in request.headers.get("Accept", "")
        )
        if wants_json:
            response = JsonResponse(
                {"ok": False, "message": message, "retry_after": retry_after},
                status=429,
            )
        else:
            response = HttpResponse(message, status=429)
        response["Retry-After"] = str(retry_after)
        response["Cache-Control"] = "no-store"
        return response


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        frame_ancestors = (getattr(settings, "CSP_FRAME_ANCESTORS", "") or "").strip()
        if frame_ancestors:
            response.setdefault(
                "Content-Security-Policy",
                f"frame-ancestors {frame_ancestors};",
            )
        response.setdefault(
            "Referrer-Policy",
            getattr(settings, "SECURE_REFERRER_POLICY", "strict-origin-when-cross-origin"),
        )
        if getattr(settings, "SECURE_CONTENT_TYPE_NOSNIFF", True):
            response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        return response
