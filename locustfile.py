"""
Locust entrypoint at repo root.

The full suite lives in tests/load_test.py (credentials, shapes, tasks).
Run: locust -f locustfile.py --host https://YOURSITE.pythonanywhere.com
Or:  locust -f tests/load_test.py --host https://YOURSITE.pythonanywhere.com
"""

from __future__ import annotations

from pathlib import Path

_load_test = Path(__file__).resolve().parent / "tests" / "load_test.py"
_scope = globals()
_scope["__file__"] = str(_load_test)
exec(compile(_load_test.read_text(encoding="utf-8"), str(_load_test), "exec"), _scope)
