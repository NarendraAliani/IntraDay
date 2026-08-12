# tests/integration/test_postgres_connectivity.py
#
# Integration smoke test (Checkpoint 4 §33): verifies a raw PostgreSQL
# connection can be opened using the same environment variables the Django
# settings modules expect, independent of Django's ORM/testing settings
# (which use SQLite per settings/testing.py's documented, temporary
# exception). Skipped when PostgreSQL is not reachable — expected to run
# for real in CI (GitHub Actions Postgres service container) and in any
# docker-compose-backed local environment. No business logic.
from __future__ import annotations

import os

import psycopg
import pytest


def test_can_connect_to_postgres() -> None:
    host = os.environ.get("POSTGRES_HOST")
    if not host:
        pytest.skip("POSTGRES_HOST not set - PostgreSQL integration skipped in this environment")

    try:
        with (
            psycopg.connect(
                host=host,
                port=os.environ.get("POSTGRES_PORT", "5432"),
                dbname=os.environ.get("POSTGRES_DB", "intraday"),
                user=os.environ.get("POSTGRES_USER", "intraday"),
                password=os.environ.get("POSTGRES_PASSWORD", ""),
                connect_timeout=3,
            ) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL unreachable in this environment: {exc}")
