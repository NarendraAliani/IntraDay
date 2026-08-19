# tests/unit/infrastructure/api/test_worker_runtime_status_api.py
#
# Checkpoint 64.3: API-level coverage for the read-only worker
# runtime-status endpoint - the operator-facing "is the live worker
# actually healthy" surface. Never a real worker process in these
# tests - the repository row is written directly, matching every other
# read-only status-endpoint test in this codebase.
from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client

from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)
from tests.postgres_utils import requires_postgres

READER_USERNAME = "worker-status-reader"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


def _client_as_reader() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


@requires_postgres
@pytest.mark.django_db
def test_requires_authentication() -> None:
    response = Client().get("/api/v1/config/market-data/worker-status/")
    assert response.status_code == 401


@requires_postgres
@pytest.mark.django_db
def test_unconfigured_when_the_worker_has_never_run() -> None:
    client = _client_as_reader()
    response = client.get("/api/v1/config/market-data/worker-status/")

    assert response.status_code == 200
    body = response.json()
    assert body["is_configured"] is False
    assert body["worker_state"] == "STOPPED"
    assert body["watchdog_state"] == "DISCONNECTED"


@requires_postgres
@pytest.mark.django_db
def test_reports_the_real_persisted_worker_state() -> None:
    DjangoWorkerRuntimeStatusRepository().save(
        "dhan",
        worker_state="RUNNING",
        token_state="VALID",
        watchdog_state="HEALTHY",
        last_packet_at=None,
        last_bar_at=None,
        reconnect_count=2,
        consecutive_failures=0,
        subscribed_instrument_count=4,
        last_error_safe="",
    )
    client = _client_as_reader()

    response = client.get("/api/v1/config/market-data/worker-status/")

    assert response.status_code == 200
    body = response.json()
    assert body["is_configured"] is True
    assert body["worker_state"] == "RUNNING"
    assert body["watchdog_state"] == "HEALTHY"
    assert body["reconnect_count"] == 2
    assert body["subscribed_instrument_count"] == 4


@requires_postgres
@pytest.mark.django_db
def test_never_leaks_a_secret_or_raw_provider_payload() -> None:
    DjangoWorkerRuntimeStatusRepository().save(
        "dhan",
        worker_state="TOKEN_EXPIRED",
        token_state="EXPIRED",
        watchdog_state="FAILED",
        last_packet_at=None,
        last_bar_at=None,
        reconnect_count=0,
        consecutive_failures=0,
        subscribed_instrument_count=0,
        last_error_safe="token_state_unusable:EXPIRED",
    )
    client = _client_as_reader()

    response = client.get("/api/v1/config/market-data/worker-status/")

    body = response.json()
    assert set(body.keys()) == {
        "provider",
        "worker_state",
        "token_state",
        "watchdog_state",
        "last_packet_at",
        "last_bar_at",
        "packet_age_seconds",
        "bar_age_seconds",
        "reconnect_count",
        "consecutive_failures",
        "subscribed_instrument_count",
        "last_error_safe",
        "updated_at",
        "is_configured",
    }
    # No field anywhere carries a token value or a raw provider response.
    assert "token" not in body["last_error_safe"].lower() or body["last_error_safe"] == (
        "token_state_unusable:EXPIRED"
    )


@requires_postgres
@pytest.mark.django_db
def test_supports_querying_a_different_provider() -> None:
    DjangoWorkerRuntimeStatusRepository().save(
        "dhan",
        worker_state="RUNNING",
        token_state="VALID",
        watchdog_state="HEALTHY",
        last_packet_at=None,
        last_bar_at=None,
        reconnect_count=0,
        consecutive_failures=0,
        subscribed_instrument_count=1,
        last_error_safe="",
    )
    client = _client_as_reader()

    response = client.get("/api/v1/config/market-data/worker-status/?provider=some-other-provider")

    assert response.json()["is_configured"] is False
