# src/intraday/settings/development.py
#
# Local developer environment (Checkpoint 4). TRADING_MODE is forced to a
# non-production resolution: setting TRADING_MODE=LIVE in a developer's
# .env while running under this module raises UnsafeLiveConfigurationError
# at import time and Django refuses to start. See settings/trading_mode.py.
from __future__ import annotations

import os

from .base import *  # noqa: F401,F403
from .trading_mode import resolve_trading_mode

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]  # noqa: S104 - local dev only

# Unconditional override (not `if not SECRET_KEY`) so the value's origin is
# unambiguous to both readers and static analysis: an explicit env var
# always wins, otherwise this fixed development-only placeholder is used.
SECRET_KEY = os.environ.get(  # noqa: S105 - placeholder, development-only
    "DJANGO_SECRET_KEY", "django-insecure-development-only-key-do-not-use-elsewhere"
)

TRADING_MODE = resolve_trading_mode(
    settings_module_is_production=False,
    live_broker_credentials_present=False,
)

# NOTE: no CORS package is configured yet (none added to dependencies at
# this checkpoint per "avoid unnecessary dependencies", Checkpoint 4 §5).
# Add django-cors-headers explicitly, with reasoning, when the frontend
# dev server actually needs cross-origin API access (Checkpoint 14+).
