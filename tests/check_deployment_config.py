"""
Lightweight deployment configuration checker for the Django backend.

Run this before load testing so you do not benchmark an unsafe configuration.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pet_adoption.settings")

import django  # noqa: E402


django.setup()

from django.conf import settings  # noqa: E402


def check(label: str, ok: bool, *, severity: str = "high") -> tuple[str, bool, str]:
    return label, ok, severity


def main() -> int:
    middleware = set(getattr(settings, "MIDDLEWARE", []))
    cache_default = getattr(settings, "CACHES", {}).get("default", {})
    checks = [
        check("DEBUG must be False", settings.DEBUG is False, severity="high"),
        check(
            "SecurityMiddleware enabled",
            "django.middleware.security.SecurityMiddleware" in middleware,
            severity="high",
        ),
        check(
            "CsrfViewMiddleware enabled",
            "django.middleware.csrf.CsrfViewMiddleware" in middleware,
            severity="high",
        ),
        check(
            "XFrameOptionsMiddleware enabled",
            "django.middleware.clickjacking.XFrameOptionsMiddleware" in middleware,
            severity="high",
        ),
        check(
            "Custom rate-limit middleware enabled",
            "pet_adoption.middleware.RequestRateLimitMiddleware" in middleware,
            severity="medium",
        ),
        check(
            "Custom security headers middleware enabled",
            "pet_adoption.middleware.SecurityHeadersMiddleware" in middleware,
            severity="medium",
        ),
        check(
            "CSRF trusted origins configured",
            bool(getattr(settings, "CSRF_TRUSTED_ORIGINS", [])),
            severity="medium",
        ),
        check(
            "X_FRAME_OPTIONS protects against framing",
            getattr(settings, "X_FRAME_OPTIONS", "") in {"DENY", "SAMEORIGIN"},
            severity="high",
        ),
        check(
            "SECURE_CONTENT_TYPE_NOSNIFF enabled",
            bool(getattr(settings, "SECURE_CONTENT_TYPE_NOSNIFF", False)),
            severity="medium",
        ),
        check(
            "Rate limiting enabled",
            bool(getattr(settings, "RATE_LIMIT_ENABLED", False)),
            severity="medium",
        ),
        check(
            "Session cookie uses SameSite",
            bool(getattr(settings, "SESSION_COOKIE_SAMESITE", "")),
            severity="medium",
        ),
        check(
            "CSRF cookie uses SameSite",
            bool(getattr(settings, "CSRF_COOKIE_SAMESITE", "")),
            severity="medium",
        ),
    ]

    if settings.DEBUG is False:
        checks.extend(
            [
                check(
                    "Session cookie secure in non-debug mode",
                    bool(getattr(settings, "SESSION_COOKIE_SECURE", False)),
                    severity="high",
                ),
                check(
                    "CSRF cookie secure in non-debug mode",
                    bool(getattr(settings, "CSRF_COOKIE_SECURE", False)),
                    severity="high",
                ),
                check(
                    "Production cache uses Redis",
                    cache_default.get("BACKEND") == "django.core.cache.backends.redis.RedisCache",
                    severity="high",
                ),
                check(
                    "Redis cache location configured",
                    bool(cache_default.get("LOCATION")),
                    severity="high",
                ),
            ]
        )

    failed = []
    for label, ok, severity in checks:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] ({severity.upper()}) {label}")
        if not ok:
            failed.append((label, severity))

    if failed:
        print("\nDeployment configuration is not ready for realistic load testing.")
        return 1

    print("\nDeployment configuration looks ready for load and stress testing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
