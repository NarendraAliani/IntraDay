# tests/postgres_utils.py
#
# Shared PostgreSQL-availability check for gating Django-ORM tests
# (Checkpoint 7). Using a collection-time `skipif` (not a runtime
# `pytest.skip()` inside the test body) is essential: `skipif` is
# evaluated before pytest-django would attempt session-level test-
# database creation, so an unreachable PostgreSQL server produces a
# clean "skipped" report for the affected tests instead of a hard
# session-wide failure that would also break unrelated tests.
from __future__ import annotations

import os

import psycopg
import pytest


def postgres_reachable() -> bool:
    host = os.environ.get("POSTGRES_HOST")
    if not host:
        return False
    try:
        with psycopg.connect(
            host=host,
            port=os.environ.get("POSTGRES_PORT", "5432"),
            dbname=os.environ.get("POSTGRES_DB", "intraday"),
            user=os.environ.get("POSTGRES_USER", "intraday"),
            password=os.environ.get("POSTGRES_PASSWORD", ""),
            connect_timeout=2,
        ):
            return True
    except psycopg.OperationalError:
        return False


requires_postgres = pytest.mark.skipif(
    not postgres_reachable(),
    reason="PostgreSQL not reachable in this environment (POSTGRES_HOST unset or unreachable)",
)
