# src/intraday/settings/production.py
#
# Production (live-capable) environment (Checkpoint 4). This is the ONLY
# settings module where TRADING_MODE=LIVE can ever resolve successfully —
# and even here, only when live broker credentials are also present. See
# settings/trading_mode.py for the full invariant and
# docs/architecture/TECHNOLOGY_MAPPING.md §14 for the safety rationale.
#
# No broker calls are made anywhere in this file — it only checks for the
# *presence* of the expected environment variables.
from __future__ import annotations

import os

from .base import *  # noqa: F401,F403
from .trading_mode import resolve_trading_mode

DEBUG = False
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")

if not SECRET_KEY:  # noqa: F405 - inherited from base
    raise RuntimeError(
        "DJANGO_SECRET_KEY must be set via the environment in production. Refusing to boot."
    )

_live_broker_credentials_present = bool(
    os.environ.get("DHAN_API_KEY") and os.environ.get("DHAN_ACCESS_TOKEN")
)

TRADING_MODE = resolve_trading_mode(
    settings_module_is_production=True,
    live_broker_credentials_present=_live_broker_credentials_present,
)

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
