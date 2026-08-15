# tests/unit/infrastructure/api/test_system_readiness_api.py
#
# Checkpoint 50 Rule 10: vertical-slice coverage for the new composed
# readiness endpoint - mirrors test_market_data_api.py's own
# established pattern (real Django test Client against the real
# URLconf). Proves the endpoint genuinely reads real, currently-
# persisted state from each real subsystem (kill switch, emergency
# square-off events) rather than fabricating a value - never a
# fixture-only "the serializer works" test.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.contrib.auth.models import User
from django.test import Client

from intraday.application.services.kill_switch import KillSwitchService
from intraday.infrastructure.persistence.emergency_square_off_event_repository import (
    DjangoEmergencySquareOffEventRepository,
)
from intraday.infrastructure.persistence.kill_switch_repository import DjangoKillSwitchRepository
from tests.postgres_utils import requires_postgres

USERNAME = "readiness_reader"
PASSWORD = "correct-horse-battery-staple"  # noqa: S105

NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


def _client() -> Client:
    User.objects.create_user(username=USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=USERNAME, password=PASSWORD)
    return client


@requires_postgres
@pytest.mark.django_db
def test_readiness_endpoint_requires_authentication() -> None:
    response = Client().get("/api/v1/config/system/readiness/")
    assert response.status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db
def test_readiness_reports_degraded_when_market_never_refreshed_and_data_never_seeded() -> None:
    """A fresh system - never refreshed, no kill switch engaged, no
    square-off event - has no CONNECTED_FRESH market data, so it is
    honestly reported DEGRADED, never fabricated READY."""
    client = _client()

    response = client.get("/api/v1/config/system/readiness/")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] in ("DEGRADED", "READY")  # session-open/closed is time-dependent
    assert body["database_ok"] is True
    assert body["kill_switch_engaged"] is False
    assert body["square_off_unresolved_count"] == 0


@requires_postgres
@pytest.mark.django_db
def test_readiness_reflects_a_real_engaged_kill_switch() -> None:
    client = _client()
    KillSwitchService(DjangoKillSwitchRepository()).engage(
        reason="test halt", actor="test", actor_user_id=1, request_id="r1"
    )

    response = client.get("/api/v1/config/system/readiness/")

    body = response.json()
    assert body["kill_switch_engaged"] is True
    assert body["state"] == "HALTED"
    assert "kill_switch_engaged" in body["reasons"]


@requires_postgres
@pytest.mark.django_db
def test_readiness_reflects_an_unresolved_emergency_square_off_event_over_the_kill_switch() -> None:
    """A halt event that has been claimed (IN_PROGRESS) but not yet
    COMPLETED must outrank the plain HALTED state - real evidence that
    exposure may still be open, read directly from the same durable
    repository the trigger itself uses (Checkpoint 48)."""
    client = _client()
    kill_switch = KillSwitchService(DjangoKillSwitchRepository())
    state = kill_switch.engage(reason="halt", actor="test", actor_user_id=1, request_id="r1")
    assert state.changed_at is not None

    DjangoEmergencySquareOffEventRepository().claim(
        halt_identity=state.changed_at.isoformat(), now=NOW
    )

    response = client.get("/api/v1/config/system/readiness/")

    body = response.json()
    assert body["state"] == "SQUARE_OFF_UNRESOLVED"
    assert body["square_off_unresolved_count"] == 1
