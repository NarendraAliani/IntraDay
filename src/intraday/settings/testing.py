# src/intraday/settings/testing.py
#
# CI / pytest environment.
#
# RESOLVED AT CHECKPOINT 7: the SQLite exception documented here at
# Checkpoint 4 is now retired. Real Django models exist
# (infrastructure/persistence/models.py) with PostgreSQL-specific
# behavior (NUMERIC precision, JSONB, CHECK constraints) that SQLite
# cannot faithfully exercise — continuing to fall back to SQLite here
# would silently hide exactly the class of bug this checkpoint's models
# introduce. This module now uses the SAME PostgreSQL configuration as
# base.py (env-var driven, no SQLite anywhere in this file).
#
# Consequence: any test using Django's `db`/`django_db_setup` fixture
# requires a real, reachable PostgreSQL instance (the docker-compose `db`
# service locally, or the GitHub Actions Postgres service container in
# CI). Tests that need it are decorated with both `@pytest.mark.django_db`
# AND a `@requires_postgres` skipif guard (see
# tests/unit/infrastructure/persistence/conftest.py) — the skipif is
# evaluated at collection time, BEFORE pytest-django attempts to create
# a test database, so an unreachable PostgreSQL server produces a clean
# "skipped" report rather than a hard session-level failure. Pure-Python
# tests (domain contracts, config schema, non-DB unit tests) never touch
# a database connection and are unaffected either way.
from __future__ import annotations

from .base import *  # noqa: F401,F403
from .trading_mode import resolve_trading_mode

DEBUG = False
ALLOWED_HOSTS = ["testserver"]
SECRET_KEY = "test-secret-key-not-for-production"  # noqa: S105

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
