# src/intraday/wsgi.py
#
# WSGI entrypoint (Checkpoint 4). Retained for management-command and
# tooling compatibility only (e.g. some deployment/inspection tooling still
# expects a WSGI callable) — the actual serving entrypoint for
# staging/production is ASGI (see intraday/asgi.py and
# docs/architecture/TECHNOLOGY_MAPPING.md §2), since WebSocket/live-data
# support requires Channels' ASGI stack, which WSGI cannot serve.
from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "intraday.settings.development")

application = get_wsgi_application()
