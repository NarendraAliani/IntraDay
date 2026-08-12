# src/intraday/asgi.py
#
# ASGI entrypoint (Checkpoint 4) — the actual serving entrypoint for
# staging/production per docs/architecture/TECHNOLOGY_MAPPING.md §2 (Django
# Channels serves both REST via DRF and WebSocket in one deployable). The
# WebSocket router is currently empty: no channel consumers exist yet since
# no business logic (live signal/position push) has been implemented.
from __future__ import annotations

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "intraday.settings.development")

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": URLRouter([]),  # no consumers yet — added with real live-data features
    }
)
