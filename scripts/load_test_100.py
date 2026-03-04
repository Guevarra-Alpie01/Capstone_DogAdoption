import argparse
import random
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Tuple
from urllib.parse import urljoin

import requests


def parse_weighted_path(raw: str) -> Tuple[str, int]:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Path cannot be empty.")
    if "@" not in text:
        return text, 1
    path, weight = text.rsplit("@", 1)
    parsed_weight = int(weight)
    if parsed_weight <= 0:
        raise ValueError(f"Weight must be > 0 for path '{raw}'.")
    return path.strip(), parsed_weight


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    ordered = sorted(values)
    index = int(round((p / 100.0) * (len(ordered) - 1)))
    return ordered[index]


@dataclass
class SharedStats:
    latencies_ms: List[float] = field(default_factory=list)
    status_counts: Counter = field(default_factory=Counter)
    error_counts: Counter = field(default_factory=Counter)
    total_requests: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record_success(self, latency_ms: float, status_code: int) -> None:
        with self.lock:
            self.total_requests += 1
            self.latencies_ms.append(latency_ms)
            self.status_counts[status_code] += 1

    def record_error(self, latency_ms: float, error_label: str) -> None:
        with self.lock:
            self.total_requests += 1
            self.latencies_ms.append(latency_ms)
            self.error_counts[error_label] += 1


def worker(
    worker_id: int,
    total_workers: int,
    base_url: str,
    weighted_paths: List[Tuple[str, int]],
    timeout_seconds: float,
    ramp_seconds: float,
    verify_tls: bool,
    stop_event: threading.Event,
    stats: SharedStats,
    raw_cookie: str,
) -> None:
    if ramp_seconds > 0:
        ramp_delay = (worker_id / max(total_workers - 1, 1)) * ramp_seconds
        time.sleep(ramp_delay)

    session = requests.Session()
    if raw_cookie:
        for part in raw_cookie.split(";"):
            entry = part.strip()
            if "=" not in entry:
                continue
            name, value = entry.split("=", 1)
            session.cookies.set(name.strip(), value.strip())

    while not stop_event.is_set():
        path = random.choices(
            population=[p for p, _ in weighted_paths],
            weights=[w for _, w in weighted_paths],
            k=1,
        )[0]
        url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))

        started = time.perf_counter()
        try:
            response = session.get(
                url,
                timeout=timeout_seconds,
                allow_redirects=True,
                verify=verify_tls,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            stats.record_success(elapsed_ms, response.status_code)
        except requests.RequestException as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            stats.record_error(elapsed_ms, type(exc).__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Threaded load test for Django endpoints."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--duration", type=int, default=60, help="Seconds.")
    parser.add_argument("--ramp-seconds", type=float, default=8.0)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument(
        "--path",
        action="append",
        default=[
            "/user/@5",
            "/user/announcements/@2",
            "/user/adopt-list/?filter=all@2",
            "/user/request/@1",
        ],
        help="Path format: /path/@weight . Repeat this option.",
    )
    parser.add_argument(
        "--cookie",
        default="",
        help="Optional cookie header value, for example: sessionid=abc123",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for HTTPS testing.",
    )
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    if args.concurrency <= 0:
        raise SystemExit("--concurrency must be greater than 0.")
    if args.duration <= 0:
        raise SystemExit("--duration must be greater than 0.")

    random.seed(args.seed)

    weighted_paths = [parse_weighted_path(raw) for raw in args.path]
    stop_event = threading.Event()
    stats = SharedStats()

    threads = []
    started_at = time.perf_counter()
    for i in range(args.concurrency):
        thread = threading.Thread(
            target=worker,
            args=(
                i,
                args.concurrency,
                args.base_url,
                weighted_paths,
                args.timeout,
                args.ramp_seconds,
                not args.insecure,
                stop_event,
                stats,
                args.cookie,
            ),
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    time.sleep(args.duration)
    stop_event.set()
    for thread in threads:
        thread.join(timeout=2.0)

    elapsed = max(time.perf_counter() - started_at, 0.001)

    total = stats.total_requests
    status_ok = sum(
        count for code, count in stats.status_counts.items() if 200 <= code < 400
    )
    status_fail = sum(
        count for code, count in stats.status_counts.items() if code >= 400
    )
    errors = sum(stats.error_counts.values())

    print("Load test summary")
    print(f"Base URL: {args.base_url}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Duration: {args.duration}s")
    print(f"Total requests: {total}")
    print(f"Requests/sec: {total / elapsed:.2f}")
    print(f"HTTP 2xx/3xx: {status_ok}")
    print(f"HTTP 4xx/5xx: {status_fail}")
    print(f"Network errors: {errors}")
    print(f"Latency p50: {percentile(stats.latencies_ms, 50):.2f} ms")
    print(f"Latency p95: {percentile(stats.latencies_ms, 95):.2f} ms")
    print(f"Latency p99: {percentile(stats.latencies_ms, 99):.2f} ms")

    if stats.status_counts:
        print("Status codes:")
        for code in sorted(stats.status_counts):
            print(f"  {code}: {stats.status_counts[code]}")
    if stats.error_counts:
        print("Errors:")
        for label, count in stats.error_counts.most_common():
            print(f"  {label}: {count}")


if __name__ == "__main__":
    main()
