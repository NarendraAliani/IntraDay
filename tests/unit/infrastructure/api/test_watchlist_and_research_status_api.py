# tests/unit/infrastructure/api/test_watchlist_and_research_status_api.py
#
# Endpoint tests for the Checkpoint 27 watchlist (Part 19) and strategy
# research-monitor (Part 20) API resources.
from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from tests.postgres_utils import requires_postgres

READER_USERNAME = "wl-reader"  # noqa: S105
OPERATOR_USERNAME = "wl-operator"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


def _client_as_reader(username: str = READER_USERNAME) -> Client:
    User.objects.create_user(username=username, password=PASSWORD)
    client = Client()
    assert client.login(username=username, password=PASSWORD)
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
def test_save_list_get_delete_watchlist() -> None:
    client = _client_as_reader()
    save_response = client.post(
        "/api/v1/config/watchlists/save/",
        data={"name": "my-list", "instrument_ids": ["NSE:FIXTURE01", "NSE:TESTCO"]},
        content_type="application/json",
    )
    assert save_response.status_code == 201

    list_response = client.get("/api/v1/config/watchlists/")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = client.get("/api/v1/config/watchlists/my-list/")
    assert get_response.status_code == 200
    assert get_response.json()["instrument_ids"] == ["NSE:FIXTURE01", "NSE:TESTCO"]

    delete_response = client.delete("/api/v1/config/watchlists/my-list/delete/")
    assert delete_response.status_code == 204
    assert client.get("/api/v1/config/watchlists/my-list/").status_code == 404


@requires_postgres
@pytest.mark.django_db
def test_watchlists_are_isolated_per_owner() -> None:
    client_a = _client_as_reader("wl-owner-a")
    client_b = _client_as_reader("wl-owner-b")
    client_a.post(
        "/api/v1/config/watchlists/save/",
        data={"name": "shared-name", "instrument_ids": ["NSE:FIXTURE01"]},
        content_type="application/json",
    )
    response_b = client_b.get("/api/v1/config/watchlists/shared-name/")
    assert response_b.status_code == 404


@requires_postgres
@pytest.mark.django_db
def test_research_status_defaults_to_active_and_can_be_paused() -> None:
    client = _client_as_operator()
    get_response = client.get(
        "/api/v1/config/strategy-engine/strategies/ema_crossover/research-status/"
    )
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "RESEARCH_ACTIVE"

    pause_response = client.post(
        "/api/v1/config/strategy-engine/strategies/ema_crossover/research-status/set/",
        data={"status": "RESEARCH_PAUSED"},
        content_type="application/json",
    )
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "RESEARCH_PAUSED"

    get_after = client.get(
        "/api/v1/config/strategy-engine/strategies/ema_crossover/research-status/"
    )
    assert get_after.json()["status"] == "RESEARCH_PAUSED"


@requires_postgres
@pytest.mark.django_db
def test_research_status_set_requires_operator_role() -> None:
    client = _client_as_reader()
    response = client.post(
        "/api/v1/config/strategy-engine/strategies/ema_crossover/research-status/set/",
        data={"status": "RESEARCH_PAUSED"},
        content_type="application/json",
    )
    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_research_status_unknown_strategy_returns_404() -> None:
    client = _client_as_reader()
    response = client.get("/api/v1/config/strategy-engine/strategies/nonexistent/research-status/")
    assert response.status_code == 404


@requires_postgres
@pytest.mark.django_db
def test_research_status_list_covers_every_registered_strategy() -> None:
    client = _client_as_reader()
    response = client.get("/api/v1/config/strategy-engine/research-status/")
    assert response.status_code == 200
    strategy_ids = {row["strategy_id"] for row in response.json()}
    assert strategy_ids == {"ema_crossover", "sma_trend_filter", "atr_volatility_breakout"}
