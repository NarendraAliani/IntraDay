# src/intraday/settings/paper.py
#
# Paper-trading environment (Checkpoint 4). Mirrors production
# infrastructure configuration (real PostgreSQL, real Redis) but is not the
# production settings module — TRADING_MODE=LIVE is therefore always
# rejected here by construction, even if accidentally set in this
# environment's .env. Only TRADING_MODE=PAPER (or RESEARCH) is expected.
from __future__ import annotations

import os

from .base import *  # noqa: F401,F403
from .trading_mode import resolve_trading_mode

DEBUG = False
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")

TRADING_MODE = resolve_trading_mode(
    settings_module_is_production=False,
    live_broker_credentials_present=False,
)

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
