# tests/unit/infrastructure/api/test_scanner_configuration_api.py
#
# Checkpoint 64.4: API-level coverage for the live scanner control
# plane - desired-state write (validated against the REAL strategy
# registry and Timeframe enum), and the combined desired/effective
# read.
from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)
from tests.postgres_utils import requires_postgres

OPERATOR_USERNAME = "scanner-config-operator"  # noqa: S105
READER_USERNAME = "scanner-config-reader"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


def _client_as_reader() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "enabled": True,
        "timeframe": "5m",
        "universe_mode": "ALL_CONFIGURED",
        "selected_instrument_ids": [],
        "selected_watchlist_name": "",
        "selected_strategy_ids": ["ema_crossover"],
    }
    payload.update(overrides)
    return payload


@requires_postgres
@pytest.mark.django_db
def test_get_requires_authentication() -> None:
    response = Client().get("/api/v1/config/market-data/scanner-config/")
    assert response.status_code == 401


@requires_postgres
@pytest.mark.django_db
def test_update_requires_operator_role() -> None:
    client = _client_as_reader()
    response = client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(),
        content_type="application/json",
    )
    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_get_before_any_update_shows_sensible_defaults() -> None:
    client = _client_as_operator()
    response = client.get("/api/v1/config/market-data/scanner-config/")

    assert response.status_code == 200
    body = response.json()
    assert body["desired"]["enabled"] is False
    assert body["desired"]["configuration_version"] == 1
    assert body["status"] == "STOPPED"


@requires_postgres
@pytest.mark.django_db
def test_a_real_strategy_id_is_accepted() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(),
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["desired"]["strategy_ids"] == ["ema_crossover"]
    assert body["desired"]["configuration_version"] == 2  # bumped from the default row's 1


@requires_postgres
@pytest.mark.django_db
def test_an_unknown_strategy_id_is_rejected() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(selected_strategy_ids=["not_a_real_strategy"]),
        content_type="application/json",
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_an_unknown_timeframe_is_rejected() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(timeframe="not-a-real-timeframe"),
        content_type="application/json",
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_status_is_applying_when_the_worker_has_never_reconciled() -> None:
    client = _client_as_operator()
    client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(),
        content_type="application/json",
    )

    response = client.get("/api/v1/config/market-data/scanner-config/")

    assert response.json()["status"] == "APPLYING"


@requires_postgres
@pytest.mark.django_db
def test_status_is_effective_once_the_worker_reconciled_the_same_version() -> None:
    client = _client_as_operator()
    update_response = client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(),
        content_type="application/json",
    )
    version = update_response.json()["desired"]["configuration_version"]

    DjangoWorkerRuntimeStatusRepository().save_effective_scanner_state(
        "dhan",
        effective_configuration_version=version,
        effective_timeframe="5m",
        effective_strategy_ids=["ema_crossover"],
        effective_universe_requested_count=10,
        effective_universe_subscribed_count=10,
    )

    response = client.get("/api/v1/config/market-data/scanner-config/")
    body = response.json()
    assert body["status"] == "EFFECTIVE"
    assert body["effective"]["timeframe"] == "5m"


@requires_postgres
@pytest.mark.django_db
def test_status_is_degraded_when_the_universe_was_truncated() -> None:
    client = _client_as_operator()
    update_response = client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(),
        content_type="application/json",
    )
    version = update_response.json()["desired"]["configuration_version"]

    DjangoWorkerRuntimeStatusRepository().save_effective_scanner_state(
        "dhan",
        effective_configuration_version=version,
        effective_timeframe="5m",
        effective_strategy_ids=["ema_crossover"],
        effective_universe_requested_count=287,
        effective_universe_subscribed_count=200,
    )

    response = client.get("/api/v1/config/market-data/scanner-config/")
    assert response.json()["status"] == "DEGRADED"
