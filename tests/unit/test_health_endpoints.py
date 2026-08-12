# tests/unit/test_health_endpoints.py
#
# Infrastructure smoke tests (Checkpoint 4 §11-12) for /healthz, /readyz,
# /version. Uses Django's test client against the testing settings module
# (SQLite in-memory + LocMemCache — see settings/testing.py's documented
# justification). No business-logic assertions.
from __future__ import annotations

import pytest
from django.test import Client

import intraday


def test_healthz_returns_alive() -> None:
    client = Client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_version_matches_package_metadata() -> None:
    client = Client()
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json()["version"] == intraday.__version__


@pytest.mark.django_db
def test_readyz_reports_checks_without_leaking_secrets() -> None:
    client = Client()
    response = client.get("/readyz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert "checks" in body
    assert "status" in body

    serialized = str(body).upper()
    for forbidden_token in ("PASSWORD", "SECRET", "TOKEN", "POSTGRES://", "REDIS://"):
        assert forbidden_token not in serialized


@pytest.mark.django_db
def test_readyz_reports_database_ok_with_test_database() -> None:
    client = Client()
    response = client.get("/readyz")
    assert response.json()["checks"]["database"] == "ok"
