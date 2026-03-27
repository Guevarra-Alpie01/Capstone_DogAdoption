import json
import logging
from time import perf_counter
from uuid import uuid4

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
