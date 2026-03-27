from collections import Counter, deque
from threading import Lock
from time import monotonic

from django.utils import timezone


_GLOBAL_SAMPLE_SIZE = 2000
_ROUTE_SAMPLE_SIZE = 200


def _percentile(samples, percentile_value):
    values = list(samples or [])
    if not values:
        return 0.0
    if percentile_value <= 0:
        return float(min(values))
    if percentile_value >= 100:
        return float(max(values))
    values.sort()
    index = int(round((percentile_value / 100.0) * (len(values) - 1)))
    return float(values[index])


class RuntimeMetricsStore:
    def __init__(self):
        self._lock = Lock()
        self._reset_unlocked()

    def reset(self):
        with self._lock:
            self._reset_unlocked()

    def _reset_unlocked(self):
        self._started_at = monotonic()
        self._created_at = timezone.now()
        self._routes = {}
        self._total_requests = 0
        self._total_errors = 0
        self._latency_samples = deque(maxlen=_GLOBAL_SAMPLE_SIZE)

    def record(self, *, method, route, status_code, latency_ms):
        route_key = (method or "GET", route or "unknown")
        now = timezone.now()
        safe_latency = max(float(latency_ms or 0.0), 0.0)
        safe_status = int(status_code or 0)

        with self._lock:
            payload = self._routes.setdefault(
                route_key,
                {
                    "requests": 0,
                    "errors": 0,
                    "latency_sum_ms": 0.0,
                    "latency_samples": deque(maxlen=_ROUTE_SAMPLE_SIZE),
                    "status_counts": Counter(),
                    "last_seen_at": None,
                },
            )
            payload["requests"] += 1
            payload["latency_sum_ms"] += safe_latency
            payload["latency_samples"].append(safe_latency)
            payload["status_counts"][str(safe_status)] += 1
            payload["last_seen_at"] = now
            if safe_status >= 500:
                payload["errors"] += 1
                self._total_errors += 1

            self._total_requests += 1
            self._latency_samples.append(safe_latency)

    def snapshot(self, top_n=25):
        with self._lock:
            route_rows = []
            for (method, route), payload in self._routes.items():
                requests = payload["requests"]
                errors = payload["errors"]
                avg_latency_ms = (
                    payload["latency_sum_ms"] / requests if requests else 0.0
                )
                route_rows.append(
                    {
                        "method": method,
                        "route": route,
                        "requests": requests,
                        "errors": errors,
                        "error_rate_pct": round((errors / requests) * 100.0, 2)
                        if requests
                        else 0.0,
                        "avg_latency_ms": round(avg_latency_ms, 2),
                        "p95_latency_ms": round(
                            _percentile(payload["latency_samples"], 95), 2
                        ),
                        "status_counts": dict(payload["status_counts"]),
                        "last_seen_at": payload["last_seen_at"].isoformat()
                        if payload["last_seen_at"]
                        else "",
                    }
                )

            total_requests = self._total_requests
            total_errors = self._total_errors
            uptime_seconds = max(monotonic() - self._started_at, 0.001)
            latency_samples = list(self._latency_samples)
            avg_latency_ms = (
                sum(latency_samples) / len(latency_samples)
                if latency_samples
                else 0.0
            )

        route_rows.sort(key=lambda row: (-row["requests"], row["route"], row["method"]))

        return {
            "service": "pet_adoption",
            "generated_at": timezone.now().isoformat(),
            "started_at": self._created_at.isoformat(),
            "uptime_seconds": round(uptime_seconds, 2),
            "totals": {
                "requests": total_requests,
                "errors": total_errors,
                "error_rate_pct": round((total_errors / total_requests) * 100.0, 2)
                if total_requests
                else 0.0,
                "throughput_rps": round(total_requests / uptime_seconds, 2),
                "avg_latency_ms": round(avg_latency_ms, 2),
                "p95_latency_ms": round(_percentile(latency_samples, 95), 2),
            },
            "routes": route_rows[: max(min(int(top_n or 25), 100), 1)],
        }


runtime_metrics = RuntimeMetricsStore()
