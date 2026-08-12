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

# Checkpoint 11: the Vite dev server (127.0.0.1:5173 / localhost:5173) is a
# different origin than the Django dev server (127.0.0.1:8000), so both
# CORS (to let the browser read cross-origin fetch() responses) and
# CSRF_TRUSTED_ORIGINS (Django 4+ requires the *referring* origin be
# explicitly trusted for unsafe-method requests, even same-site) must
# name it explicitly. Both hostnames are listed because browsers treat
# "localhost" and "127.0.0.1" as distinct origins even though they
# resolve to the same host.
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
