"""
Locust suite for the Capstone Dog Adoption Django backend.

What this file covers:
- realistic public, authenticated user, and admin browsing flows
- authenticated POST flows with CSRF handling
- adaptive stress profile that stops when the app degrades
- basic SQL injection and XSS probes with CSV findings export

Safe defaults:
- login/logout are exercised, but repeated session cycling is disabled by default
- write-heavy tasks are opt-in and sampled to avoid polluting shared staging data
- security probes are sampled so they do not dominate normal traffic
"""

from __future__ import annotations

import csv
import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from urllib.parse import quote_plus

from locust import HttpUser, LoadTestShape, between, events, task
from locust.exception import StopUser
from locust.runners import WorkerRunner


CSRF_RE = re.compile(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']')
USER_ADOPT_PATH_RE = re.compile(r"(/user/user-adopt/[^\"'\s<]+/)")
STAFF_ADOPT_PATH_RE = re.compile(r"(/user/adopt/[^\"'\s<]+/)")
CLAIM_PATH_RE = re.compile(r"(/user/claim/[^\"'\s<]+/)")
ANNOUNCEMENT_REACT_PATH_RE = re.compile(r"(/user/announcements/[^\"'\s<]+/react/)")
ANNOUNCEMENT_COMMENT_PATH_RE = re.compile(r"(/user/announcements/[^\"'\s<]+/comment/)")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _parse_csv_ints(raw: str, default: list[int]) -> list[int]:
    if not raw.strip():
        return default
    values: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            continue
    return values or default


def _parse_csv_floats(raw: str, default: list[float]) -> list[float]:
    if not raw.strip():
        return default
    values: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(float(part))
        except ValueError:
            continue
    return values or default


def _parse_credentials(prefix: str) -> list[tuple[str, str]]:
    raw_pairs = (os.getenv(f"{prefix}_CREDENTIALS") or "").strip()
    credentials: list[tuple[str, str]] = []
    if raw_pairs:
        for pair in raw_pairs.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            username, password = pair.split(":", 1)
            username = username.strip()
            password = password.strip()
            if username and password:
                credentials.append((username, password))
        if credentials:
            return credentials

    username = (os.getenv(f"{prefix}_USERNAME") or "").strip()
    password = (os.getenv(f"{prefix}_PASSWORD") or "").strip()
    if username and password:
        credentials.append((username, password))
    return credentials


@dataclass(frozen=True)
class LoadSuiteSettings:
    profile: str
    user_credentials: list[tuple[str, str]]
    admin_credentials: list[tuple[str, str]]
    wait_min_seconds: float
    wait_max_seconds: float
    enable_writes: bool
    write_user_sample_rate: float
    enable_session_cycle: bool
    security_probes_enabled: bool
    security_probe_user_sample_rate: float
    security_probe_interval_seconds: int
    search_term: str
    barangay_query: str
    request_phone_number: str
    request_barangay: str
    request_city: str
    request_latitude: str
    request_longitude: str
    request_reason: str
    request_description: str
    announcement_comment_text: str
    sql_injection_payload: str
    xss_payload: str
    ramp_users: list[int]
    ramp_stage_seconds: list[int]
    ramp_spawn_rates: list[float]
    stress_start_users: int
    stress_step_users: int
    stress_step_seconds: int
    stress_spawn_rate: float
    stress_max_users: int
    stress_max_duration_seconds: int
    stress_fail_ratio_threshold: float
    stress_p95_threshold_ms: int
    output_dir: Path
    report_prefix: str

    @classmethod
    def from_env(cls) -> "LoadSuiteSettings":
        timestamp_prefix = time.strftime("loadtest_%Y%m%d_%H%M%S_")
        output_dir = Path(
            os.getenv(
                "LOAD_TEST_OUTPUT_DIR",
                str(Path(__file__).resolve().parent / "reports"),
            )
        )
        profile = (os.getenv("LOAD_TEST_PROFILE") or "steady").strip().lower()
        if profile not in {"steady", "stress"}:
            profile = "steady"

        ramp_users = _parse_csv_ints(
            os.getenv("LOAD_TEST_RAMP_USERS", ""),
            [10, 50, 100, 500],
        )
        ramp_stage_seconds = _parse_csv_ints(
            os.getenv("LOAD_TEST_RAMP_STAGE_SECONDS", ""),
            [60, 120, 180, 240],
        )
        ramp_spawn_rates = _parse_csv_floats(
            os.getenv("LOAD_TEST_RAMP_SPAWN_RATES", ""),
            [2.0, 5.0, 10.0, 25.0],
        )

        if len(ramp_stage_seconds) < len(ramp_users):
            ramp_stage_seconds.extend(
                [ramp_stage_seconds[-1] if ramp_stage_seconds else 60]
                * (len(ramp_users) - len(ramp_stage_seconds))
            )
        if len(ramp_spawn_rates) < len(ramp_users):
            ramp_spawn_rates.extend(
                [ramp_spawn_rates[-1] if ramp_spawn_rates else 5.0]
                * (len(ramp_users) - len(ramp_spawn_rates))
            )

        return cls(
            profile=profile,
            user_credentials=_parse_credentials("LOAD_TEST_USER"),
            admin_credentials=_parse_credentials("LOAD_TEST_ADMIN"),
            wait_min_seconds=env_float("LOAD_TEST_WAIT_MIN_SECONDS", 1.0),
            wait_max_seconds=env_float("LOAD_TEST_WAIT_MAX_SECONDS", 4.0),
            enable_writes=env_bool("LOAD_TEST_ENABLE_WRITES", False),
            write_user_sample_rate=max(
                0.0,
                min(1.0, env_float("LOAD_TEST_WRITE_USER_SAMPLE_RATE", 0.15)),
            ),
            enable_session_cycle=env_bool("LOAD_TEST_ENABLE_SESSION_CYCLE", False),
            security_probes_enabled=env_bool("LOAD_TEST_ENABLE_SECURITY_PROBES", True),
            security_probe_user_sample_rate=max(
                0.0,
                min(1.0, env_float("LOAD_TEST_SECURITY_PROBE_USER_SAMPLE_RATE", 0.10)),
            ),
            security_probe_interval_seconds=env_int(
                "LOAD_TEST_SECURITY_PROBE_INTERVAL_SECONDS",
                180,
            ),
            search_term=(os.getenv("LOAD_TEST_SEARCH_TERM") or "dog").strip() or "dog",
            barangay_query=(os.getenv("LOAD_TEST_BARANGAY_QUERY") or "ca").strip() or "ca",
            request_phone_number=(
                os.getenv("LOAD_TEST_REQUEST_PHONE_NUMBER") or "09171234567"
            ).strip(),
            request_barangay=(os.getenv("LOAD_TEST_REQUEST_BARANGAY") or "").strip(),
            request_city=(os.getenv("LOAD_TEST_REQUEST_CITY") or "Bayawan City").strip(),
            request_latitude=(os.getenv("LOAD_TEST_REQUEST_LATITUDE") or "9.364300").strip(),
            request_longitude=(os.getenv("LOAD_TEST_REQUEST_LONGITUDE") or "122.804300").strip(),
            request_reason=(os.getenv("LOAD_TEST_REQUEST_REASON") or "other").strip(),
            request_description=(
                os.getenv("LOAD_TEST_REQUEST_DESCRIPTION")
                or "Locust load test request for staging validation."
            ).strip(),
            announcement_comment_text=(
                os.getenv("LOAD_TEST_COMMENT_TEXT")
                or "Locust validation comment."
            ).strip(),
            sql_injection_payload=(
                os.getenv("LOAD_TEST_SQLI_PAYLOAD")
                or "' OR 1=1 --"
            ).strip(),
            xss_payload=(
                os.getenv("LOAD_TEST_XSS_PAYLOAD")
                or "<script>alert('locust-xss')</script>"
            ).strip(),
            ramp_users=ramp_users,
            ramp_stage_seconds=ramp_stage_seconds[: len(ramp_users)],
            ramp_spawn_rates=ramp_spawn_rates[: len(ramp_users)],
            stress_start_users=env_int("LOAD_TEST_STRESS_START_USERS", 10),
            stress_step_users=env_int("LOAD_TEST_STRESS_STEP_USERS", 40),
            stress_step_seconds=env_int("LOAD_TEST_STRESS_STEP_SECONDS", 60),
            stress_spawn_rate=env_float("LOAD_TEST_STRESS_SPAWN_RATE", 10.0),
            stress_max_users=env_int("LOAD_TEST_STRESS_MAX_USERS", 800),
            stress_max_duration_seconds=env_int("LOAD_TEST_STRESS_MAX_DURATION_SECONDS", 1800),
            stress_fail_ratio_threshold=env_float("LOAD_TEST_STRESS_FAIL_RATIO", 0.10),
            stress_p95_threshold_ms=env_int("LOAD_TEST_STRESS_P95_MS", 5000),
            output_dir=output_dir,
            report_prefix=(os.getenv("LOAD_TEST_REPORT_PREFIX") or timestamp_prefix).strip(),
        )


SETTINGS = LoadSuiteSettings.from_env()


@dataclass
class RunState:
    started_at_monotonic: float = 0.0
    started_at_utc: str = ""
    stage_history: list[dict] = field(default_factory=list)
    security_findings: list[dict] = field(default_factory=list)
    breaking_point: dict | None = None
    lock: Lock = field(default_factory=Lock)

    def reset(self) -> None:
        with self.lock:
            self.started_at_monotonic = time.monotonic()
            self.started_at_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self.stage_history = []
            self.security_findings = []
            self.breaking_point = None

    def record_stage(self, row: dict) -> None:
        with self.lock:
            self.stage_history.append(row)

    def record_probe(self, row: dict) -> None:
        with self.lock:
            self.security_findings.append(row)

    def record_breaking_point(self, row: dict) -> None:
        with self.lock:
            if self.breaking_point is None:
                self.breaking_point = row


RUN_STATE = RunState()


def _is_worker(environment) -> bool:
    return isinstance(getattr(environment, "runner", None), WorkerRunner)


def _stats_snapshot(runner, *, target_users: int = 0, spawn_rate: float = 0.0, stage_name: str = "") -> dict:
    total = runner.stats.total
    p95 = total.get_response_time_percentile(0.95) if total.num_requests else 0
    return {
        "recorded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(time.monotonic() - RUN_STATE.started_at_monotonic, 2),
        "stage_name": stage_name,
        "target_users": target_users,
        "active_users": getattr(runner, "user_count", 0),
        "spawn_rate": spawn_rate,
        "requests": total.num_requests,
        "failures": total.num_failures,
        "fail_ratio": round(total.fail_ratio, 4),
        "avg_response_time_ms": round(total.avg_response_time or 0.0, 2),
        "p95_response_time_ms": round(p95 or 0.0, 2),
        "current_rps": round(getattr(total, "current_rps", 0.0) or 0.0, 2),
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    if _is_worker(environment):
        return
    RUN_STATE.reset()
    SETTINGS.output_dir.mkdir(parents=True, exist_ok=True)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    if _is_worker(environment):
        return
    runner = getattr(environment, "runner", None)
    if runner is None:
        return
    RUN_STATE.record_stage(
        {
            **_stats_snapshot(
                runner,
                target_users=getattr(runner, "user_count", 0),
                spawn_rate=0.0,
                stage_name="final",
            ),
            "sample_type": "final",
        }
    )


@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    if _is_worker(environment):
        return

    runner = getattr(environment, "runner", None)
    if runner is None:
        return

    duration_seconds = max(time.monotonic() - RUN_STATE.started_at_monotonic, 0.001)
    total = environment.stats.total
    p95 = total.get_response_time_percentile(0.95) if total.num_requests else 0
    suspicious_findings = [
        row for row in RUN_STATE.security_findings if row.get("suspicious") == "yes"
    ]

    summary = {
        "started_at_utc": RUN_STATE.started_at_utc,
        "finished_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "profile": SETTINGS.profile,
        "host": environment.host,
        "duration_seconds": round(duration_seconds, 2),
        "total_requests": total.num_requests,
        "total_failures": total.num_failures,
        "fail_ratio": round(total.fail_ratio, 4),
        "avg_response_time_ms": round(total.avg_response_time or 0.0, 2),
        "p95_response_time_ms": round(p95 or 0.0, 2),
        "requests_per_second": round(total.num_requests / duration_seconds, 2),
        "security_probe_count": len(RUN_STATE.security_findings),
        "suspicious_probe_count": len(suspicious_findings),
        "breaking_point": RUN_STATE.breaking_point,
    }

    prefix = SETTINGS.report_prefix
    summary_path = SETTINGS.output_dir / f"{prefix}summary.json"
    probes_path = SETTINGS.output_dir / f"{prefix}security_probes.csv"
    stages_path = SETTINGS.output_dir / f"{prefix}stage_history.csv"

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_csv(probes_path, RUN_STATE.security_findings)
    _write_csv(stages_path, RUN_STATE.stage_history)

    print(f"Locust summary written to {summary_path}")
    print(f"Security probe findings written to {probes_path}")
    print(f"Stage history written to {stages_path}")


class CapstoneLoadShape(LoadTestShape):
    """
    One shape class for both steady ramp and adaptive stress mode.

    Locust automatically enables the single load shape found in the file.
    """

    def __init__(self):
        super().__init__()
        self._last_stage_name = ""

    def _record_stage_if_changed(self, stage_name: str, target_users: int, spawn_rate: float) -> None:
        if stage_name == self._last_stage_name or getattr(self, "runner", None) is None:
            return
        self._last_stage_name = stage_name
        RUN_STATE.record_stage(
            {
                **_stats_snapshot(
                    self.runner,
                    target_users=target_users,
                    spawn_rate=spawn_rate,
                    stage_name=stage_name,
                ),
                "sample_type": "transition",
            }
        )

    def _steady_tick(self):
        run_time = self.get_run_time()
        elapsed = 0
        for index, users in enumerate(SETTINGS.ramp_users):
            elapsed += SETTINGS.ramp_stage_seconds[index]
            if run_time < elapsed:
                spawn_rate = SETTINGS.ramp_spawn_rates[index]
                stage_name = f"steady-{index + 1}-{users}users"
                self._record_stage_if_changed(stage_name, users, spawn_rate)
                return users, spawn_rate
        return None

    def _stress_tick(self):
        runner = getattr(self, "runner", None)
        if runner is None:
            return SETTINGS.stress_start_users, SETTINGS.stress_spawn_rate

        run_time = self.get_run_time()
        if run_time >= SETTINGS.stress_max_duration_seconds:
            return None

        step_index = int(run_time // max(SETTINGS.stress_step_seconds, 1))
        target_users = min(
            SETTINGS.stress_start_users + (step_index * SETTINGS.stress_step_users),
            SETTINGS.stress_max_users,
        )
        spawn_rate = SETTINGS.stress_spawn_rate
        stage_name = f"stress-{step_index + 1}-{target_users}users"
        self._record_stage_if_changed(stage_name, target_users, spawn_rate)

        total = runner.stats.total
        p95 = total.get_response_time_percentile(0.95) if total.num_requests else 0
        fail_ratio = total.fail_ratio
        if (
            total.num_requests > 0
            and (
                fail_ratio > SETTINGS.stress_fail_ratio_threshold
                or (p95 or 0) > SETTINGS.stress_p95_threshold_ms
            )
        ):
            RUN_STATE.record_breaking_point(
                _stats_snapshot(
                    runner,
                    target_users=target_users,
                    spawn_rate=spawn_rate,
                    stage_name=stage_name,
                )
            )
            return None

        return target_users, spawn_rate

    def tick(self):
        if SETTINGS.profile == "stress":
            return self._stress_tick()
        return self._steady_tick()


class CapstoneUserBase(HttpUser):
    abstract = True
    wait_time = between(SETTINGS.wait_min_seconds, SETTINGS.wait_max_seconds)

    login_path = "/user/user-login/"
    logout_path = "/user/logout/"
    dashboard_path = "/user/"
    user_label = "base"

    def on_start(self):
        self.csrf_token = ""
        self.is_authenticated = False
        self.user_adopt_paths: list[str] = []
        self.staff_adopt_paths: list[str] = []
        self.claim_paths: list[str] = []
        self.announcement_react_paths: list[str] = []
        self.announcement_comment_paths: list[str] = []
        self.last_security_probe_at = 0.0
        self.write_enabled = SETTINGS.enable_writes and (
            random.random() <= SETTINGS.write_user_sample_rate
        )
        self.security_probes_allowed = SETTINGS.security_probes_enabled and (
            random.random() <= SETTINGS.security_probe_user_sample_rate
        )
        self.selected_credentials = self.choose_credentials()
        if not self.selected_credentials:
            raise StopUser("No credentials configured for this user class.")
        self.login()

    def on_stop(self):
        if self.is_authenticated:
            self.logout()

    def choose_credentials(self) -> tuple[str, str] | None:
        raise NotImplementedError

    def _absolute_url(self, path: str) -> str:
        base_url = (self.environment.host or "").rstrip("/")
        return f"{base_url}{path}"

    def _capture_csrf(self, response) -> str:
        cookie_token = self.client.cookies.get("csrftoken") or ""
        if cookie_token:
            self.csrf_token = cookie_token
            return self.csrf_token
        text = getattr(response, "text", "") or ""
        match = CSRF_RE.search(text)
        if match:
            self.csrf_token = match.group(1)
        return self.csrf_token

    def _ensure_csrf(self, referer_path: str) -> str:
        token = self.client.cookies.get("csrftoken") or self.csrf_token
        if token:
            self.csrf_token = token
            return token
        with self.client.get(
            referer_path,
            name="GET csrf-bootstrap",
            catch_response=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"Unable to bootstrap CSRF token from {referer_path}")
                raise StopUser("CSRF bootstrap failed.")
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            response.success()
        return self.csrf_token

    def _csrf_headers(self, referer_path: str, *, ajax: bool = False) -> dict[str, str]:
        token = self._ensure_csrf(referer_path)
        headers = {
            "Referer": self._absolute_url(referer_path),
        }
        if token:
            headers["X-CSRFToken"] = token
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
        return headers

    def _capture_discovery(self, html: str | None) -> None:
        if not html:
            return
        self.user_adopt_paths = list(
            set(self.user_adopt_paths).union(USER_ADOPT_PATH_RE.findall(html))
        )
        self.staff_adopt_paths = list(
            set(self.staff_adopt_paths).union(STAFF_ADOPT_PATH_RE.findall(html))
        )
        self.claim_paths = list(
            set(self.claim_paths).union(CLAIM_PATH_RE.findall(html))
        )
        self.announcement_react_paths = list(
            set(self.announcement_react_paths).union(
                ANNOUNCEMENT_REACT_PATH_RE.findall(html)
            )
        )
        self.announcement_comment_paths = list(
            set(self.announcement_comment_paths).union(
                ANNOUNCEMENT_COMMENT_PATH_RE.findall(html)
            )
        )

    def _maybe_reauthenticate(self, response, *, expected_prefix: str) -> bool:
        final_url = (getattr(response, "url", "") or "").lower()
        if response.status_code >= 400:
            return False
        if expected_prefix.lower() in final_url:
            return True
        if "/user/user-login/" in final_url:
            self.is_authenticated = False
            self.login()
            return False
        return True

    def _describe_login_failure(self, response, final_url: str) -> str:
        body = getattr(response, "text", "") or ""
        if response.status_code == 429 or "Too many requests" in body:
            return "Login failed: rate limited by the backend."
        if "Invalid username or password" in body:
            return "Login failed: invalid load-test credentials."
        if response.status_code >= 400:
            return f"Login failed with HTTP {response.status_code}."
        if "/user/user-login/" in final_url:
            return "Login failed: request stayed on the login page."
        return "Login failed for an unknown reason."

    def _abort_run_for_bad_auth(self, reason: str) -> None:
        runner = getattr(self.environment, "runner", None)
        if runner is None:
            return
        if "invalid load-test credentials" not in reason:
            return
        if (time.monotonic() - RUN_STATE.started_at_monotonic) > 30:
            return
        runner.quit()

    def login(self) -> None:
        username, password = self.selected_credentials
        with self.client.get(
            self.login_path,
            name="GET /user/user-login/",
            catch_response=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"Login page failed with {response.status_code}")
                raise StopUser("Login page unavailable.")
            self._capture_csrf(response)
            response.success()

        payload = {
            "username": username,
            "password": password,
            "csrfmiddlewaretoken": self.csrf_token,
        }
        headers = {
            "Referer": self._absolute_url(self.login_path),
            "X-CSRFToken": self.csrf_token,
        }
        with self.client.post(
            self.login_path,
            data=payload,
            headers=headers,
            allow_redirects=True,
            name="POST /user/user-login/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            final_url = (getattr(response, "url", "") or "").lower()
            if response.status_code >= 400 or "/user/user-login/" in final_url:
                failure_reason = self._describe_login_failure(response, final_url)
                response.failure(failure_reason)
                self._abort_run_for_bad_auth(failure_reason)
                raise StopUser(failure_reason)
            self.is_authenticated = True
            response.success()

    def logout(self) -> None:
        with self.client.get(
            self.logout_path,
            name=f"GET {self.logout_path}",
            allow_redirects=True,
            catch_response=True,
        ) as response:
            if response.status_code >= 500:
                response.failure(f"Logout failed with {response.status_code}")
            else:
                self._capture_csrf(response)
                response.success()
        self.is_authenticated = False

    def _record_probe_result(
        self,
        *,
        probe_name: str,
        method: str,
        path: str,
        status_code: int,
        content_type: str,
        suspicious: bool,
        reason: str,
    ) -> None:
        RUN_STATE.record_probe(
            {
                "recorded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "user_label": self.user_label,
                "probe_name": probe_name,
                "method": method,
                "path": path,
                "status_code": status_code,
                "content_type": content_type,
                "suspicious": "yes" if suspicious else "no",
                "reason": reason,
            }
        )

    def _run_get_probe(self, probe_name: str, path: str, payload: str) -> None:
        with self.client.get(
            path,
            name=f"SECURITY {probe_name}",
            catch_response=True,
        ) as response:
            body = (response.text or "")[:10000]
            raw_reflected = payload in body
            suspicious = response.status_code >= 500 or raw_reflected
            reason = "raw payload reflected" if raw_reflected else (
                "server error" if response.status_code >= 500 else "handled"
            )
            self._record_probe_result(
                probe_name=probe_name,
                method="GET",
                path=path,
                status_code=response.status_code,
                content_type=response.headers.get("Content-Type", ""),
                suspicious=suspicious,
                reason=reason,
            )
            if response.status_code >= 500:
                response.failure(f"{probe_name} triggered {response.status_code}")
            else:
                response.success()

    def _run_post_probe(self, probe_name: str, path: str, form_data: dict[str, str]) -> None:
        headers = self._csrf_headers(self.dashboard_path, ajax=False)
        with self.client.post(
            path,
            data=form_data,
            headers=headers,
            allow_redirects=True,
            name=f"SECURITY {probe_name}",
            catch_response=True,
        ) as response:
            body = (response.text or "")[:10000]
            suspicious = response.status_code >= 500 or self._contains_unescaped_xss(body)
            reason = "unescaped xss reflected" if self._contains_unescaped_xss(body) else (
                "server error" if response.status_code >= 500 else "handled"
            )
            self._record_probe_result(
                probe_name=probe_name,
                method="POST",
                path=path,
                status_code=response.status_code,
                content_type=response.headers.get("Content-Type", ""),
                suspicious=suspicious,
                reason=reason,
            )
            if response.status_code >= 500:
                response.failure(f"{probe_name} triggered {response.status_code}")
            else:
                response.success()

    def _contains_unescaped_xss(self, body: str) -> bool:
        return SETTINGS.xss_payload in body

    @task(1)
    def maybe_cycle_session(self):
        if not SETTINGS.enable_session_cycle or not self.is_authenticated:
            return
        self.logout()
        self.login()


class PublicVisitor(HttpUser):
    weight = 1
    wait_time = between(SETTINGS.wait_min_seconds, SETTINGS.wait_max_seconds)

    @task(2)
    def landing_redirect(self):
        with self.client.get("/", name="GET /", allow_redirects=True, catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"Landing failed with {response.status_code}")
            else:
                response.success()

    @task(3)
    def login_page(self):
        with self.client.get("/user/user-login/", name="GET /user/user-login/", catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"Login page failed with {response.status_code}")
            else:
                response.success()

    @task(2)
    def signup_page(self):
        with self.client.get("/user/sign-up/", name="GET /user/sign-up/", catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"Signup page failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def health_live(self):
        with self.client.get("/health/live/", name="GET /health/live/", catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"Health live failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def health_ready(self):
        with self.client.get("/health/ready/", name="GET /health/ready/", catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"Health ready failed with {response.status_code}")
            else:
                response.success()


class UserJourney(CapstoneUserBase):
    abstract = not bool(SETTINGS.user_credentials)
    weight = 5
    user_label = "authenticated-user"
    dashboard_path = "/user/"
    logout_path = "/user/logout/"

    def choose_credentials(self) -> tuple[str, str] | None:
        return random.choice(SETTINGS.user_credentials) if SETTINGS.user_credentials else None

    @task(6)
    def browse_home(self):
        with self.client.get("/user/", name="GET /user/", catch_response=True) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/"):
                response.failure("User home redirected away from authenticated area.")
            else:
                response.success()

    @task(4)
    def browse_announcements(self):
        with self.client.get(
            "/user/announcements/",
            name="GET /user/announcements/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/announcements/"):
                response.failure("Announcement feed redirected to login.")
            else:
                response.success()

    @task(4)
    def browse_adopt_list(self):
        with self.client.get(
            "/user/adopt-list/",
            name="GET /user/adopt-list/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/adopt-list/"):
                response.failure("Adopt list redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_request_page(self):
        with self.client.get(
            "/user/request/",
            name="GET /user/request/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/request/"):
                response.failure("Request page redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_claim_list(self):
        with self.client.get(
            "/user/claim-list/",
            name="GET /user/claim-list/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/claim-list/"):
                response.failure("Claim list redirected to login.")
            else:
                response.success()

    @task(3)
    def browse_adopt_status(self):
        with self.client.get(
            "/user/adopt/status/",
            name="GET /user/adopt/status/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/adopt/status/"):
                response.failure("Adopt status redirected to login.")
            else:
                response.success()

    @task(3)
    def notification_summary(self):
        with self.client.get(
            "/user/notifications/summary/",
            name="GET /user/notifications/summary/",
            catch_response=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"Notification summary failed with {response.status_code}")
            else:
                response.success()

    @task(2)
    def barangay_api(self):
        path = f"/user/barangays/?q={quote_plus(SETTINGS.barangay_query)}&limit=20"
        with self.client.get(path, name="GET /user/barangays/", catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"Barangay API failed with {response.status_code}")
            else:
                response.success()

    @task(2)
    def search_feed(self):
        path = f"/user/search/?q={quote_plus(SETTINGS.search_term)}"
        with self.client.get(path, name="GET /user/search/", catch_response=True) as response:
            self._capture_discovery(response.text)
            if response.status_code >= 400:
                response.failure(f"Feed search failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def mark_notifications_seen(self):
        headers = self._csrf_headers("/user/", ajax=True)
        with self.client.post(
            "/user/notifications/seen/",
            data={},
            headers=headers,
            name="POST /user/notifications/seen/",
            catch_response=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"Mark-seen failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def react_to_announcement(self):
        if not self.write_enabled or not self.announcement_react_paths:
            return
        path = random.choice(self.announcement_react_paths)
        headers = self._csrf_headers("/user/announcements/", ajax=True)
        with self.client.post(
            path,
            data={"next": "/user/announcements/"},
            headers=headers,
            name="POST /user/announcements/[announcement]/react/",
            catch_response=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"Announcement reaction failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def comment_on_announcement(self):
        if not self.write_enabled or not self.announcement_comment_paths:
            return
        path = random.choice(self.announcement_comment_paths)
        headers = self._csrf_headers("/user/announcements/", ajax=False)
        with self.client.post(
            path,
            data={
                "comment": SETTINGS.announcement_comment_text,
                "next": "/user/announcements/",
            },
            headers=headers,
            allow_redirects=True,
            name="POST /user/announcements/[announcement]/comment/",
            catch_response=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"Announcement comment failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def request_user_adoption(self):
        if not self.write_enabled or not self.user_adopt_paths:
            return
        path = random.choice(self.user_adopt_paths)
        headers = self._csrf_headers("/user/", ajax=True)
        with self.client.post(
            path,
            data={},
            headers=headers,
            allow_redirects=True,
            name="POST /user/user-adopt/[post]/",
            catch_response=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"User adoption request failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def submit_surrender_request(self):
        if not self.write_enabled or not SETTINGS.request_barangay:
            return
        headers = self._csrf_headers("/user/request/", ajax=False)
        payload = {
            "phone_number": SETTINGS.request_phone_number,
            "request_type": "surrender",
            "submission_type": "online",
            "reason": SETTINGS.request_reason,
            "description": SETTINGS.request_description,
            "location_mode": "exact",
            "barangay": SETTINGS.request_barangay,
            "city": SETTINGS.request_city,
            "latitude": SETTINGS.request_latitude,
            "longitude": SETTINGS.request_longitude,
        }
        with self.client.post(
            "/user/request/",
            data=payload,
            headers=headers,
            allow_redirects=True,
            name="POST /user/request/",
            catch_response=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"Dog surrender request failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def security_probes(self):
        if not self.security_probes_allowed:
            return
        now = time.monotonic()
        if now - self.last_security_probe_at < SETTINGS.security_probe_interval_seconds:
            return
        self.last_security_probe_at = now

        self._run_get_probe(
            "user-sqli-barangay",
            f"/user/barangays/?q={quote_plus(SETTINGS.sql_injection_payload)}&limit=5",
            SETTINGS.sql_injection_payload,
        )
        self._run_get_probe(
            "user-sqli-search",
            f"/user/search/?q={quote_plus(SETTINGS.sql_injection_payload)}",
            SETTINGS.sql_injection_payload,
        )
        self._run_get_probe(
            "user-xss-search",
            f"/user/search/?q={quote_plus(SETTINGS.xss_payload)}",
            SETTINGS.xss_payload,
        )
        if self.write_enabled and self.announcement_comment_paths:
            self._run_post_probe(
                "user-xss-announcement-comment",
                random.choice(self.announcement_comment_paths),
                {
                    "comment": SETTINGS.xss_payload,
                    "next": "/user/announcements/",
                },
            )


class AdminJourney(CapstoneUserBase):
    abstract = not bool(SETTINGS.admin_credentials)
    weight = 1
    user_label = "admin-user"
    dashboard_path = "/vetadmin/post-list/"
    logout_path = "/vetadmin/logout/"

    def choose_credentials(self) -> tuple[str, str] | None:
        return random.choice(SETTINGS.admin_credentials) if SETTINGS.admin_credentials else None

    @task(5)
    def browse_post_list(self):
        with self.client.get(
            "/vetadmin/post-list/",
            name="GET /vetadmin/post-list/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Admin post list redirected to login.")
            else:
                response.success()

    @task(3)
    def browse_capture_requests(self):
        with self.client.get(
            "/vetadmin/dog-capture/requests/",
            name="GET /vetadmin/dog-capture/requests/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Admin request board redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_registration_record(self):
        with self.client.get(
            "/vetadmin/registration-record/",
            name="GET /vetadmin/registration-record/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Registration record redirected to login.")
            else:
                response.success()

    @task(1)
    def browse_analytics(self):
        with self.client.get(
            "/vetadmin/analytics/dashboard/",
            name="GET /vetadmin/analytics/dashboard/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Analytics dashboard redirected to login.")
            else:
                response.success()

    @task(2)
    def admin_notification_summary(self):
        with self.client.get(
            "/vetadmin/notifications/summary/",
            name="GET /vetadmin/notifications/summary/",
            catch_response=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"Admin notification summary failed with {response.status_code}")
            else:
                response.success()

    @task(2)
    def admin_barangay_api(self):
        path = f"/vetadmin/barangays/?q={quote_plus(SETTINGS.barangay_query)}&limit=20"
        with self.client.get(path, name="GET /vetadmin/barangays/", catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"Admin barangay API failed with {response.status_code}")
            else:
                response.success()

    @task(2)
    def registration_user_search(self):
        path = f"/vetadmin/registration/users/search/?q={quote_plus(SETTINGS.search_term)}"
        with self.client.get(
            path,
            name="GET /vetadmin/registration/users/search/",
            catch_response=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"Registration user search failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def admin_user_search(self):
        path = f"/vetadmin/users/search/?q={quote_plus(SETTINGS.search_term)}"
        with self.client.get(path, name="GET /vetadmin/users/search/", catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"Admin user search failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def security_probes(self):
        if not self.security_probes_allowed:
            return
        now = time.monotonic()
        if now - self.last_security_probe_at < SETTINGS.security_probe_interval_seconds:
            return
        self.last_security_probe_at = now

        self._run_get_probe(
            "admin-sqli-registration-user-search",
            f"/vetadmin/registration/users/search/?q={quote_plus(SETTINGS.sql_injection_payload)}",
            SETTINGS.sql_injection_payload,
        )
        self._run_get_probe(
            "admin-sqli-citation-lookup",
            f"/vetadmin/citation/lookup/?citation_id={quote_plus('1 OR 1=1')}",
            "1 OR 1=1",
        )
        self._run_get_probe(
            "admin-xss-user-search",
            f"/vetadmin/users/search/?q={quote_plus(SETTINGS.xss_payload)}",
            SETTINGS.xss_payload,
        )
