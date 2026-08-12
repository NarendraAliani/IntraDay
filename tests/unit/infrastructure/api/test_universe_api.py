# tests/unit/infrastructure/api/test_universe_api.py
#
# Endpoint tests for the universe API resource (Checkpoint 8). Mirrors
# test_risk_api.py's coverage at lighter depth (the risk suite already
# covers the full vertical slice + error/activation edge cases in
# detail).
from __future__ import annotations

import pytest
from django.test import Client

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Version
from intraday.domain.universe.contracts import Universe, UniverseMember, UniverseMembershipStatus
from intraday.infrastructure.persistence.repositories import DjangoUniverseRepository
from tests.postgres_utils import requires_postgres


def _seed(version: str = "v1") -> None:
    DjangoUniverseRepository().save(
        Universe(
            universe_id="example",
            version=Version(value=version),
            exchange=Exchange.NSE,
            members=(
                UniverseMember(
                    make_instrument_id(Exchange.NSE, "RELIANCE"), UniverseMembershipStatus.INCLUDED
                ),
            ),
        )
    )


@requires_postgres
@pytest.mark.django_db
def test_get_version_returns_members_with_stable_shape() -> None:
    _seed("v1")
    client = Client()

    response = client.get("/api/v1/config/universe/example/v1/")

    assert response.status_code == 200
    body = response.json()
    assert body["exchange"] == "NSE"
    assert body["members"] == [{"instrument_id": "NSE:RELIANCE", "status": "INCLUDED"}]


@requires_postgres
@pytest.mark.django_db
def test_unknown_universe_returns_404() -> None:
    client = Client()
    response = client.get("/api/v1/config/universe/does-not-exist/v1/")
    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


@requires_postgres
@pytest.mark.django_db
def test_activate_updates_active_pointer_without_mutating_history() -> None:
    _seed("v1")
    _seed("v2")
    client = Client()

    response = client.post("/api/v1/config/universe/example/v2/activate/")
    assert response.status_code == 200
    assert response.json()["version"] == "v2"

    historical = client.get("/api/v1/config/universe/example/v1/")
    assert historical.status_code == 200
    assert historical.json()["is_active"] is False
