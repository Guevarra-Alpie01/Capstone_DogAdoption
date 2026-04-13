"""
PythonAnywhere WSGI entry point.

Point the PythonAnywhere Web tab at this file or copy its contents into the
platform-managed WSGI script.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pet_adoption.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
