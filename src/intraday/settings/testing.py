# src/intraday/settings/testing.py
#
# CI / pytest environment (Checkpoint 4).
#
# JUSTIFIED, DOCUMENTED, TEMPORARY EXCEPTION (Checkpoint 4 §8): this module
# uses SQLite for Django's own test-database bootstrap. This is acceptable
# ONLY because no business models or migrations exist yet at this
# checkpoint — there is nothing PostgreSQL/TimescaleDB-specific (NUMERIC
# precision, JSONB, hypertables) to test against. This is NOT a production
# or business-data decision and does not violate Checkpoint 3's PostgreSQL
# system-of-record decision.
#
# THIS MUST BE REVISITED at the first checkpoint that introduces real
# domain models (Checkpoint 5+): from that point on, any test exercising
# model behavior must run against a real PostgreSQL instance (the
# docker-compose `db` service locally, the GitHub Actions Postgres service
# container in CI) and this module must stop silently falling back to
# SQLite for anything model-bearing. Tracked in taskReport.md's Checkpoint 4
# "Known Issues / Deferred Items".
#
# tests/integration/* independently verify real PostgreSQL/Redis/Celery
# connectivity using environment variables directly (not through this
# settings module) and skip gracefully when those services are unreachable
# — see tests/integration/test_postgres_connectivity.py.
from __future__ import annotations

from .base import *  # noqa: F401,F403
from .trading_mode import resolve_trading_mode

DEBUG = False
ALLOWED_HOSTS = ["testserver"]
SECRET_KEY = "test-secret-key-not-for-production"  # noqa: S105

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

TRADING_MODE = resolve_trading_mode(
    settings_module_is_production=False,
    live_broker_credentials_present=False,
)
