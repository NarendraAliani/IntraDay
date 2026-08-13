# tests/unit/infrastructure/api/test_universe_api.py
#
# Endpoint tests for the universe API resource (Checkpoint 8). Mirrors
# test_risk_api.py's coverage at lighter depth (the risk suite already
# covers the full vertical slice + error/activation edge cases in
# detail).
#
# Checkpoint 12 fix: authenticate before hitting protected endpoints -
# see test_risk_api.py's module docstring for why this was a real,
# previously-uncaught gap.
from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Version
from intraday.domain.universe.contracts import Universe, UniverseMember, UniverseMembershipStatus
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.persistence.repositories import DjangoUniverseRepository
from tests.postgres_utils import requires_postgres

READER_USERNAME = "reader"  # noqa: S105 - test fixture username, not a secret
OPERATOR_USERNAME = "operator"  # noqa: S105 - test fixture username, not a secret
PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - test-only fixture credential


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


def _client_as_reader() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


@requires_postgres
@pytest.mark.django_db
def test_get_version_returns_members_with_stable_shape() -> None:
    _seed("v1")
    client = _client_as_reader()

    response = client.get("/api/v1/config/universe/example/v1/")

    assert response.status_code == 200
    body = response.json()
    assert body["exchange"] == "NSE"
    assert body["members"] == [{"instrument_id": "NSE:RELIANCE", "status": "INCLUDED"}]


@requires_postgres
@pytest.mark.django_db
def test_unknown_universe_returns_404() -> None:
    client = _client_as_reader()
    response = client.get("/api/v1/config/universe/does-not-exist/v1/")
    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


@requires_postgres
@pytest.mark.django_db
def test_activate_updates_active_pointer_without_mutating_history() -> None:
    _seed("v1")
    _seed("v2")
    client = _client_as_operator()

    response = client.post("/api/v1/config/universe/example/v2/activate/")
    assert response.status_code == 200
    assert response.json()["version"] == "v2"

    historical = client.get("/api/v1/config/universe/example/v1/")
    assert historical.status_code == 200
    assert historical.json()["is_active"] is False
