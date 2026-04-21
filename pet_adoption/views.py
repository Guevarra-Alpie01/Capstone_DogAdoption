from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from dogadoption_admin.access import get_staff_landing_url
from .observability import runtime_metrics

def root_redirect(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect(get_staff_landing_url(request.user))
        else:
            return redirect('user:user_home')
    return redirect('user:user_home')


def _parse_positive_int(raw_value, default=25, max_value=100):
    try:
        value = int((raw_value or default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, max_value))


def health_live(request):
    return JsonResponse(
        {
            "status": "ok",
            "service": "pet_adoption",
            "timestamp": timezone.now().isoformat(),
        }
    )


_HEALTH_READY_CACHE_KEY = "health:ready:snapshot:v1"


def health_ready(request):
    ttl = int(getattr(settings, "HEALTH_READY_CACHE_SECONDS", 0) or 0)
    if ttl > 0:
        cached = cache.get(_HEALTH_READY_CACHE_KEY)
        if isinstance(cached, dict) and "body" in cached and "status" in cached:
            return JsonResponse(cached["body"], status=int(cached["status"]))

    checks = {}
    is_ready = True

    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception as exc:
        is_ready = False
        checks["database"] = f"error:{type(exc).__name__}"

    cache_key = f"healthcheck:{uuid4().hex}"
    try:
        cache.set(cache_key, "ok", 5)
        cache_ok = cache.get(cache_key) == "ok"
        cache.delete(cache_key)
        if not cache_ok:
            raise RuntimeError("cache_roundtrip_failed")
        checks["cache"] = "ok"
    except Exception as exc:
        is_ready = False
        checks["cache"] = f"error:{type(exc).__name__}"

    body = {
        "status": "ok" if is_ready else "degraded",
        "service": "pet_adoption",
        "timestamp": timezone.now().isoformat(),
        "checks": checks,
    }
    status = 200 if is_ready else 503
    if ttl > 0:
        cache.set(
            _HEALTH_READY_CACHE_KEY,
            {"body": body, "status": status},
            timeout=ttl,
        )
    return JsonResponse(body, status=status)


def health_metrics(request):
    token = getattr(settings, "HEALTH_METRICS_TOKEN", "") or ""
    top_n = _parse_positive_int(request.GET.get("limit"), default=25, max_value=100)
    if token:
        query_token = (request.GET.get("token") or "").strip()
        header_token = (request.headers.get("X-Health-Metrics-Token") or "").strip()
        if constant_time_compare(query_token, token) or constant_time_compare(
            header_token, token
        ):
            return JsonResponse(runtime_metrics.snapshot(top_n=top_n))

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_staff:
        return JsonResponse({"detail": "Forbidden"}, status=403)

    return JsonResponse(runtime_metrics.snapshot(top_n=top_n))
