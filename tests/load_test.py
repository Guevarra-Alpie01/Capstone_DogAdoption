"""
Locust suite for the Capstone Dog Adoption Django backend.

What this file covers:
- realistic public, authenticated user, and admin browsing flows
- broad GET coverage of user and vetadmin URL modules (static routes + link discovery)
- authenticated POST flows with CSRF handling
- adaptive stress profile that stops when the app degrades
- basic SQL injection and XSS probes with CSV findings export

Default concurrency (overridable via env):
- LOAD_TEST_PUBLIC_FIXED_COUNT default 8 (anonymous landing, auth pages, health)
- LOAD_TEST_USER_FIXED_COUNT default 50 (requires LOAD_TEST_USER_* credentials)
- LOAD_TEST_ADMIN_FIXED_COUNT default 7 (requires LOAD_TEST_ADMIN_* credentials)
- Steady ramp targets are auto-sized to at least the sum of those fixed counts

Safe defaults:
- login/logout are exercised, but repeated session cycling is disabled by default
- write-heavy tasks are opt-in and sampled to avoid polluting shared staging data
- security probes are sampled so they do not dominate normal traffic
- heavy export/download endpoints are not included in the default crawl
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
CLAIM_PATH_RE = re.compile(r"(/user/(?:claim|redeem)/[^\"'\s<]+/)")
ANNOUNCEMENT_COMMENT_PATH_RE = re.compile(r"(/user/announcements/[^\"'\s<]+/comment/)")
POST_DETAIL_PATH_RE = re.compile(r"(/user/post/\d+/)")
ANNOUNCEMENT_DETAIL_PATH_RE = re.compile(r"(/user/announcements/\d+/)")
ANNOUNCEMENT_SHARE_PATH_RE = re.compile(r"(/user/announcements/share/\d+/)")
USER_ADOPT_DETAIL_PATH_RE = re.compile(r"(/user/user-adopt/\d+/detail/)")
CAPTURE_REQUEST_EDIT_PATH_RE = re.compile(r"(/user/request/[^/\"'\s<]+/edit/)")
USER_PROFILE_PATH_RE = re.compile(r"(/user/profile/\d+/)")
USER_PROFILE_REQUESTER_PATH_RE = re.compile(r"(/user/profile/requester/\d+/)")
ADMIN_VIEW_USER_PROFILE_PATH_RE = re.compile(r"(/user/profile/view/\d+/)")
ADMIN_POST_EDIT_PATH_RE = re.compile(r"(/vetadmin/posts/\d+/edit/)")
ADMIN_POST_REQUESTS_PATH_RE = re.compile(r"(/vetadmin/post/\d+/requests/)")
ADMIN_POST_CLAIMS_PATH_RE = re.compile(r"(/vetadmin/posts/\d+/claims/)")
ADMIN_POST_HISTORY_RECORD_PATH_RE = re.compile(r"(/vetadmin/posts/\d+/history-record/)")
ADMIN_CAPTURE_UPDATE_PATH_RE = re.compile(r"(/vetadmin/dog-capture/request/[^/\"'\s<]+/update/)")
ADMIN_ANNOUNCEMENT_EDIT_PATH_RE = re.compile(r"(/vetadmin/announcements/\d+/edit/)")
ADMIN_MED_RECORD_PATH_RE = re.compile(r"(/vetadmin/med-records/[^/\"'\s<]+/)")
ADMIN_CERTIFICATE_PRINT_PATH_RE = re.compile(r"(/vetadmin/certificate/\d+/)")
ADMIN_USER_DETAIL_PATH_RE = re.compile(r"(/vetadmin/admin/user/\d+/)")
ADMIN_REGISTRATION_PROFILE_PATH_RE = re.compile(r"(/vetadmin/registration/profile/\d+/)")
ADMIN_USER_VIOLATIONS_PATH_RE = re.compile(r"(/vetadmin/users/\d+/violations/)")


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
    public_fixed_count: int
    user_fixed_count: int
    admin_fixed_count: int
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
    admin_announcement_create_slug: str

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

        public_fixed_count = max(0, env_int("LOAD_TEST_PUBLIC_FIXED_COUNT", 8))
        user_fixed_count = max(0, env_int("LOAD_TEST_USER_FIXED_COUNT", 50))
        admin_fixed_count = max(0, env_int("LOAD_TEST_ADMIN_FIXED_COUNT", 7))

        user_credentials = _parse_credentials("LOAD_TEST_USER")
        admin_credentials = _parse_credentials("LOAD_TEST_ADMIN")

        ramp_users_env = (os.getenv("LOAD_TEST_RAMP_USERS") or "").strip()
        if ramp_users_env:
            ramp_users = _parse_csv_ints(
                ramp_users_env,
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
        else:
            user_floor = max(0, user_fixed_count) if user_credentials else 0
            admin_floor = max(0, admin_fixed_count) if admin_credentials else 0
            floor = max(1, public_fixed_count + user_floor + admin_floor)
            ramp_users = [floor, min(floor * 2, 250), min(floor * 3, 500)]
            ramp_stage_seconds = [90, 120, 180]
            ramp_spawn_rates = [4.0, 10.0, 20.0]

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

        stress_floor = max(
            1,
            public_fixed_count
            + (user_fixed_count if user_credentials else 0)
            + (admin_fixed_count if admin_credentials else 0),
        )

        return cls(
            profile=profile,
            user_credentials=user_credentials,
            admin_credentials=admin_credentials,
            public_fixed_count=public_fixed_count,
            user_fixed_count=user_fixed_count,
            admin_fixed_count=admin_fixed_count,
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
            stress_start_users=env_int("LOAD_TEST_STRESS_START_USERS", stress_floor),
            stress_step_users=env_int("LOAD_TEST_STRESS_STEP_USERS", 40),
            stress_step_seconds=env_int("LOAD_TEST_STRESS_STEP_SECONDS", 60),
            stress_spawn_rate=env_float("LOAD_TEST_STRESS_SPAWN_RATE", 10.0),
            stress_max_users=env_int(
                "LOAD_TEST_STRESS_MAX_USERS",
                max(800, stress_floor * 4),
            ),
            stress_max_duration_seconds=env_int("LOAD_TEST_STRESS_MAX_DURATION_SECONDS", 1800),
            stress_fail_ratio_threshold=env_float("LOAD_TEST_STRESS_FAIL_RATIO", 0.10),
            stress_p95_threshold_ms=env_int("LOAD_TEST_STRESS_P95_MS", 5000),
            output_dir=output_dir,
            report_prefix=(os.getenv("LOAD_TEST_REPORT_PREFIX") or timestamp_prefix).strip(),
            admin_announcement_create_slug=(
                os.getenv("LOAD_TEST_ADMIN_ANNOUNCEMENT_SLUG") or "dog-announcements"
            ).strip()
            or "dog-announcements",
        )


SETTINGS = LoadSuiteSettings.from_env()


class CredentialPool:
    def __init__(self, credentials: list[tuple[str, str]]):
        self.credentials = list(credentials)
        self.lock = Lock()
        self.index = 0

    def next(self) -> tuple[str, str] | None:
        if not self.credentials:
            return None
        with self.lock:
            credential = self.credentials[self.index % len(self.credentials)]
            self.index += 1
            return credential


USER_CREDENTIAL_POOL = CredentialPool(SETTINGS.user_credentials)
ADMIN_CREDENTIAL_POOL = CredentialPool(SETTINGS.admin_credentials)


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
    print(
        "Locust mix config: "
        f"public_fixed={SETTINGS.public_fixed_count}, "
        f"user_fixed={SETTINGS.user_fixed_count}, "
        f"admin_fixed={SETTINGS.admin_fixed_count}, "
        f"user_creds={len(SETTINGS.user_credentials)}, "
        f"admin_creds={len(SETTINGS.admin_credentials)}, "
        f"steady_ramp={SETTINGS.ramp_users}"
    )
    if SETTINGS.user_fixed_count and not SETTINGS.user_credentials:
        print("WARNING: LOAD_TEST_USER_FIXED_COUNT is set, but no user credentials were provided.")
    if SETTINGS.admin_fixed_count and not SETTINGS.admin_credentials:
        print("WARNING: LOAD_TEST_ADMIN_FIXED_COUNT is set, but no admin credentials were provided.")
    if SETTINGS.user_fixed_count > len(SETTINGS.user_credentials) and SETTINGS.user_credentials:
        print(
            "WARNING: Fewer user credentials than fixed authenticated users. "
            "Some accounts will be reused during login bursts."
        )
    if SETTINGS.admin_fixed_count > len(SETTINGS.admin_credentials) and SETTINGS.admin_credentials:
        print(
            "WARNING: Fewer admin credentials than fixed admin users. "
            "Some staff accounts will be reused during login bursts."
        )


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
        self.announcement_comment_paths: list[str] = []
        self.post_detail_paths: list[str] = []
        self.announcement_detail_paths: list[str] = []
        self.announcement_share_paths: list[str] = []
        self.user_adopt_detail_paths: list[str] = []
        self.capture_request_edit_paths: list[str] = []
        self.user_profile_paths: list[str] = []
        self.user_profile_requester_paths: list[str] = []
        self.admin_view_user_profile_paths: list[str] = []
        self.admin_post_edit_paths: list[str] = []
        self.admin_post_requests_paths: list[str] = []
        self.admin_post_claims_paths: list[str] = []
        self.admin_post_history_record_paths: list[str] = []
        self.admin_capture_update_paths: list[str] = []
        self.admin_announcement_edit_paths: list[str] = []
        self.admin_med_record_paths: list[str] = []
        self.admin_certificate_print_paths: list[str] = []
        self.admin_user_detail_paths: list[str] = []
        self.admin_registration_profile_paths: list[str] = []
        self.admin_user_violations_paths: list[str] = []
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
        self.announcement_comment_paths = list(
            set(self.announcement_comment_paths).union(
                ANNOUNCEMENT_COMMENT_PATH_RE.findall(html)
            )
        )
        self.post_detail_paths = list(
            set(self.post_detail_paths).union(POST_DETAIL_PATH_RE.findall(html))
        )
        self.announcement_detail_paths = list(
            set(self.announcement_detail_paths).union(
                ANNOUNCEMENT_DETAIL_PATH_RE.findall(html)
            )
        )
        self.announcement_share_paths = list(
            set(self.announcement_share_paths).union(
                ANNOUNCEMENT_SHARE_PATH_RE.findall(html)
            )
        )
        self.user_adopt_detail_paths = list(
            set(self.user_adopt_detail_paths).union(
                USER_ADOPT_DETAIL_PATH_RE.findall(html)
            )
        )
        self.capture_request_edit_paths = list(
            set(self.capture_request_edit_paths).union(
                CAPTURE_REQUEST_EDIT_PATH_RE.findall(html)
            )
        )
        self.user_profile_paths = list(
            set(self.user_profile_paths).union(USER_PROFILE_PATH_RE.findall(html))
        )
        self.user_profile_requester_paths = list(
            set(self.user_profile_requester_paths).union(
                USER_PROFILE_REQUESTER_PATH_RE.findall(html)
            )
        )
        self.admin_view_user_profile_paths = list(
            set(self.admin_view_user_profile_paths).union(
                ADMIN_VIEW_USER_PROFILE_PATH_RE.findall(html)
            )
        )
        self.admin_post_edit_paths = list(
            set(self.admin_post_edit_paths).union(ADMIN_POST_EDIT_PATH_RE.findall(html))
        )
        self.admin_post_requests_paths = list(
            set(self.admin_post_requests_paths).union(
                ADMIN_POST_REQUESTS_PATH_RE.findall(html)
            )
        )
        self.admin_post_claims_paths = list(
            set(self.admin_post_claims_paths).union(
                ADMIN_POST_CLAIMS_PATH_RE.findall(html)
            )
        )
        self.admin_post_history_record_paths = list(
            set(self.admin_post_history_record_paths).union(
                ADMIN_POST_HISTORY_RECORD_PATH_RE.findall(html)
            )
        )
        self.admin_capture_update_paths = list(
            set(self.admin_capture_update_paths).union(
                ADMIN_CAPTURE_UPDATE_PATH_RE.findall(html)
            )
        )
        self.admin_announcement_edit_paths = list(
            set(self.admin_announcement_edit_paths).union(
                ADMIN_ANNOUNCEMENT_EDIT_PATH_RE.findall(html)
            )
        )
        self.admin_med_record_paths = list(
            set(self.admin_med_record_paths).union(ADMIN_MED_RECORD_PATH_RE.findall(html))
        )
        self.admin_certificate_print_paths = list(
            set(self.admin_certificate_print_paths).union(
                ADMIN_CERTIFICATE_PRINT_PATH_RE.findall(html)
            )
        )
        self.admin_user_detail_paths = list(
            set(self.admin_user_detail_paths).union(
                ADMIN_USER_DETAIL_PATH_RE.findall(html)
            )
        )
        self.admin_registration_profile_paths = list(
            set(self.admin_registration_profile_paths).union(
                ADMIN_REGISTRATION_PROFILE_PATH_RE.findall(html)
            )
        )
        self.admin_user_violations_paths = list(
            set(self.admin_user_violations_paths).union(
                ADMIN_USER_VIOLATIONS_PATH_RE.findall(html)
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
        if "The username or password you entered is incorrect" in body:
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
    fixed_count = SETTINGS.public_fixed_count

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

    @task(1)
    def health_metrics(self):
        token = (os.getenv("LOAD_TEST_HEALTH_METRICS_TOKEN") or "").strip()
        path = "/health/metrics/"
        if token:
            path = f"{path}?token={quote_plus(token)}"
        with self.client.get(path, name="GET /health/metrics/", catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"Health metrics failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def privacy_policy(self):
        with self.client.get(
            "/user/privacy-policy/",
            name="GET /user/privacy-policy/",
            catch_response=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"Privacy policy failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def data_deletion(self):
        with self.client.get(
            "/user/data-deletion/",
            name="GET /user/data-deletion/",
            catch_response=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"Data deletion page failed with {response.status_code}")
            else:
                response.success()


class UserJourney(CapstoneUserBase):
    abstract = not bool(SETTINGS.user_credentials)
    weight = 5
    fixed_count = SETTINGS.user_fixed_count
    user_label = "authenticated-user"
    dashboard_path = "/user/"
    logout_path = "/user/logout/"

    def choose_credentials(self) -> tuple[str, str] | None:
        return USER_CREDENTIAL_POOL.next()

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
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/request/"):
                response.failure("Request page redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_redeem_list(self):
        with self.client.get(
            "/user/redeem-list/",
            name="GET /user/redeem-list/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/redeem-list/"):
                response.failure("Redeem list redirected to login.")
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

    @task(2)
    def browse_privacy_policy_auth(self):
        with self.client.get(
            "/user/privacy-policy/",
            name="GET /user/privacy-policy/ (auth)",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            if response.status_code >= 400:
                response.failure(f"Privacy policy failed with {response.status_code}")
            else:
                response.success()

    @task(2)
    def browse_data_deletion_auth(self):
        with self.client.get(
            "/user/data-deletion/",
            name="GET /user/data-deletion/ (auth)",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            if response.status_code >= 400:
                response.failure(f"Data deletion page failed with {response.status_code}")
            else:
                response.success()

    @task(2)
    def browse_complete_profile(self):
        with self.client.get(
            "/user/complete-profile/",
            name="GET /user/complete-profile/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            if response.status_code >= 400:
                response.failure(f"Complete profile failed with {response.status_code}")
            else:
                response.success()

    @task(3)
    def browse_profile_edit(self):
        with self.client.get(
            "/user/profile/edit/",
            name="GET /user/profile/edit/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/profile/edit/"):
                response.failure("Edit profile redirected unexpectedly.")
            else:
                response.success()

    @task(2)
    def browse_post_create(self):
        with self.client.get(
            "/user/post/create/",
            name="GET /user/post/create/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/post/create/"):
                response.failure("Create post page redirected unexpectedly.")
            else:
                response.success()

    @task(3)
    def browse_user_adoption_requests_page(self):
        with self.client.get(
            "/user/user-adopt/requests/",
            name="GET /user/user-adopt/requests/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/user-adopt/requests/"):
                response.failure("Adoption requests page redirected unexpectedly.")
            else:
                response.success()

    @task(2)
    def browse_my_redemptions(self):
        with self.client.get(
            "/user/my-redemptions/",
            name="GET /user/my-redemptions/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/my-redemptions/"):
                response.failure("My redemptions redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_notification_open_safe(self):
        with self.client.get(
            "/user/notifications/open/?next=/user/",
            name="GET /user/notifications/open/",
            catch_response=True,
            allow_redirects=True,
        ) as response:
            if response.status_code >= 400:
                response.failure(f"Notification open failed with {response.status_code}")
            else:
                response.success()

    @task(2)
    def browse_discovered_post_detail(self):
        if not self.post_detail_paths:
            return
        path = random.choice(self.post_detail_paths)
        with self.client.get(path, name="GET /user/post/[id]/", catch_response=True) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/post/"):
                response.failure("Post detail redirected unexpectedly.")
            else:
                response.success()

    @task(2)
    def browse_discovered_announcement_detail(self):
        if not self.announcement_detail_paths:
            return
        path = random.choice(self.announcement_detail_paths)
        with self.client.get(
            path,
            name="GET /user/announcements/[id]/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/announcements/"):
                response.failure("Announcement detail redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_announcement_share(self):
        if not self.announcement_share_paths:
            return
        path = random.choice(self.announcement_share_paths)
        with self.client.get(
            path,
            name="GET /user/announcements/share/[id]/ (redirects to detail)",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/announcements/"):
                response.failure("Announcement legacy share URL redirected unexpectedly.")
            else:
                response.success()

    @task(2)
    def browse_discovered_user_adopt_detail(self):
        if not self.user_adopt_detail_paths:
            return
        path = random.choice(self.user_adopt_detail_paths)
        with self.client.get(
            path,
            name="GET /user/user-adopt/[id]/detail/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/user-adopt/"):
                response.failure("User adopt detail redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_capture_edit(self):
        if not self.capture_request_edit_paths:
            return
        path = random.choice(self.capture_request_edit_paths)
        with self.client.get(path, name="GET /user/request/[id]/edit/", catch_response=True) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/request/"):
                response.failure("Capture request edit redirected unexpectedly.")
            else:
                response.success()

    @task(2)
    def browse_discovered_user_profile(self):
        if not self.user_profile_paths:
            return
        path = random.choice(self.user_profile_paths)
        with self.client.get(path, name="GET /user/profile/[id]/", catch_response=True) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/profile/"):
                response.failure("User profile redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_user_profile_requester(self):
        if not self.user_profile_requester_paths:
            return
        path = random.choice(self.user_profile_requester_paths)
        with self.client.get(
            path,
            name="GET /user/profile/requester/[id]/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/profile/requester/"):
                response.failure("Requester profile redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_staff_adopt_page(self):
        if not self.staff_adopt_paths:
            return
        path = random.choice(self.staff_adopt_paths)
        with self.client.get(path, name="GET /user/adopt/[id]/", catch_response=True) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/adopt/"):
                response.failure("Staff adopt page redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_redeem_confirm(self):
        if not self.claim_paths:
            return
        path = random.choice(self.claim_paths)
        with self.client.get(path, name="GET /user/redeem/[id]/", catch_response=True) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/user/redeem/"):
                response.failure("Redeem confirm redirected unexpectedly.")
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
            "gps_accuracy": "50",
            "colors": "brown",
            "gender": "male",
        }
        files = [
            ("images", ("surrender-a.jpg", b"fake-jpeg-a", "image/jpeg")),
            ("images", ("surrender-b.jpg", b"fake-jpeg-b", "image/jpeg")),
        ]
        with self.client.post(
            "/user/request/",
            data=payload,
            files=files,
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
    # Higher weight so fewer concurrent admins still exercise vetadmin routes heavily.
    weight = 4
    fixed_count = SETTINGS.admin_fixed_count
    user_label = "admin-user"
    dashboard_path = "/vetadmin/post-list/"
    logout_path = "/vetadmin/logout/"

    def choose_credentials(self) -> tuple[str, str] | None:
        return ADMIN_CREDENTIAL_POOL.next()

    @task(5)
    def browse_post_list(self):
        with self.client.get(
            "/vetadmin/post-list/",
            name="GET /vetadmin/post-list/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
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
            self._capture_discovery(response.text)
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
            self._capture_discovery(response.text)
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
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Analytics dashboard redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_post_history(self):
        with self.client.get(
            "/vetadmin/post-history/",
            name="GET /vetadmin/post-history/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Post history redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_create_post(self):
        with self.client.get(
            "/vetadmin/create/",
            name="GET /vetadmin/create/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Create post redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_register_dogs(self):
        with self.client.get(
            "/vetadmin/register/",
            name="GET /vetadmin/register/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Register dogs redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_dog_certificate(self):
        with self.client.get(
            "/vetadmin/dog-certificate/",
            name="GET /vetadmin/dog-certificate/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Dog certificate redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_certificate_list(self):
        with self.client.get(
            "/vetadmin/certificates/",
            name="GET /vetadmin/certificates/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Certificate list redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_citation_lookup(self):
        with self.client.get(
            "/vetadmin/citation/lookup/",
            name="GET /vetadmin/citation/lookup/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Citation lookup redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_citation_create(self):
        with self.client.get(
            "/vetadmin/citation/new/",
            name="GET /vetadmin/citation/new/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Citation create redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_penalty_manager(self):
        with self.client.get(
            "/vetadmin/penalties/",
            name="GET /vetadmin/penalties/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Penalty manager redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_admin_announcements(self):
        with self.client.get(
            "/vetadmin/admin/announcements/",
            name="GET /vetadmin/admin/announcements/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Admin announcements redirected to login.")
            else:
                response.success()

    @task(1)
    def browse_announcement_create_options(self):
        with self.client.get(
            "/vetadmin/announcements/create/",
            name="GET /vetadmin/announcements/create/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Announcement create options redirected to login.")
            else:
                response.success()

    @task(1)
    def browse_announcement_create_form(self):
        slug = SETTINGS.admin_announcement_create_slug
        with self.client.get(
            f"/vetadmin/announcements/create/{slug}/",
            name="GET /vetadmin/announcements/create/[slug]/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Announcement create form redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_admin_users(self):
        with self.client.get(
            "/vetadmin/users/",
            name="GET /vetadmin/users/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Admin users redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_admin_profile_edit(self):
        with self.client.get(
            "/vetadmin/profile/edit/",
            name="GET /vetadmin/profile/edit/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Admin profile edit redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_admin_notifications(self):
        with self.client.get(
            "/vetadmin/notifications/",
            name="GET /vetadmin/notifications/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Admin notifications redirected to login.")
            else:
                response.success()

    @task(2)
    def browse_user_post_requests(self):
        with self.client.get(
            "/vetadmin/user-post-requests/",
            name="GET /vetadmin/user-post-requests/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("User post requests redirected to login.")
            else:
                response.success()

    @task(1)
    def browse_discovered_admin_post_edit(self):
        if not self.admin_post_edit_paths:
            return
        path = random.choice(self.admin_post_edit_paths)
        with self.client.get(path, name="GET /vetadmin/posts/[id]/edit/", catch_response=True) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Admin post edit redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_admin_post_requests(self):
        if not self.admin_post_requests_paths:
            return
        path = random.choice(self.admin_post_requests_paths)
        with self.client.get(
            path,
            name="GET /vetadmin/post/[id]/requests/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Admin adoption requests redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_admin_post_claims(self):
        if not self.admin_post_claims_paths:
            return
        path = random.choice(self.admin_post_claims_paths)
        with self.client.get(
            path,
            name="GET /vetadmin/posts/[id]/claims/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Admin claim requests redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_admin_history_record(self):
        if not self.admin_post_history_record_paths:
            return
        path = random.choice(self.admin_post_history_record_paths)
        with self.client.get(
            path,
            name="GET /vetadmin/posts/[id]/history-record/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("History record redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_admin_capture_update(self):
        if not self.admin_capture_update_paths:
            return
        path = random.choice(self.admin_capture_update_paths)
        with self.client.get(
            path,
            name="GET /vetadmin/dog-capture/request/[id]/update/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Capture update redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_admin_announcement_edit(self):
        if not self.admin_announcement_edit_paths:
            return
        path = random.choice(self.admin_announcement_edit_paths)
        with self.client.get(
            path,
            name="GET /vetadmin/announcements/[id]/edit/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Announcement edit redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_admin_med_record(self):
        if not self.admin_med_record_paths:
            return
        path = random.choice(self.admin_med_record_paths)
        with self.client.get(
            path,
            name="GET /vetadmin/med-records/[id]/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Med record redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_admin_certificate_print(self):
        if not self.admin_certificate_print_paths:
            return
        path = random.choice(self.admin_certificate_print_paths)
        with self.client.get(
            path,
            name="GET /vetadmin/certificate/[id]/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Certificate print redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_admin_user_detail(self):
        if not self.admin_user_detail_paths:
            return
        path = random.choice(self.admin_user_detail_paths)
        with self.client.get(
            path,
            name="GET /vetadmin/admin/user/[id]/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Admin user detail redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_admin_registration_profile(self):
        if not self.admin_registration_profile_paths:
            return
        path = random.choice(self.admin_registration_profile_paths)
        with self.client.get(
            path,
            name="GET /vetadmin/registration/profile/[id]/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("Registration owner profile redirected unexpectedly.")
            else:
                response.success()

    @task(1)
    def browse_discovered_admin_user_violations(self):
        if not self.admin_user_violations_paths:
            return
        path = random.choice(self.admin_user_violations_paths)
        with self.client.get(
            path,
            name="GET /vetadmin/users/[id]/violations/",
            catch_response=True,
        ) as response:
            self._capture_csrf(response)
            self._capture_discovery(response.text)
            if not self._maybe_reauthenticate(response, expected_prefix="/vetadmin/"):
                response.failure("User violations redirected unexpectedly.")
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
            self._capture_discovery(response.text)
            if response.status_code >= 400:
                response.failure(f"Registration user search failed with {response.status_code}")
            else:
                response.success()

    @task(1)
    def admin_user_search(self):
        path = f"/vetadmin/users/search/?q={quote_plus(SETTINGS.search_term)}"
        with self.client.get(path, name="GET /vetadmin/users/search/", catch_response=True) as response:
            self._capture_discovery(response.text)
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
