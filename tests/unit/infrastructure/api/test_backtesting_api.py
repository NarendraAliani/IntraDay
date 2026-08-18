# tests/unit/infrastructure/api/test_backtesting_api.py
#
# Endpoint tests for the Checkpoint 27 backtesting API resource. Mirrors
# test_strategy_configuration_api.py's auth pattern.
from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from tests.postgres_utils import requires_postgres

READER_USERNAME = "bt-reader"  # noqa: S105
OPERATOR_USERNAME = "bt-operator"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


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


def _run_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "instrument_id": "NSE:FIXTURE01",
        "timeframe": "5m",
        "start": "2026-01-02T03:00:00Z",
        "end": "2026-01-02T06:00:00Z",
        "strategy_id": "ema_crossover",
        "specification_version": "v1",
        "code_version": "v1",
        "configuration_version": "v1",
        "strategy_values": {"fast_lookback": 3, "slow_lookback": 6},
        "initial_capital": "100000",
        "position_sizing_mode": "FIXED_QUANTITY",
        "position_size_value": "10",
        "brokerage_percent": "0",
        "slippage_percent": "0",
    }
    payload.update(overrides)
    return payload


@requires_postgres
@pytest.mark.django_db
def test_run_backtest_requires_operator_role() -> None:
    client = _client_as_reader()
    response = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_run_backtest_unknown_strategy_returns_404() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/run/",
        data=_run_payload(strategy_id="nonexistent"),
        content_type="application/json",
    )
    assert response.status_code == 404


@requires_postgres
@pytest.mark.django_db
def test_run_backtest_invalid_timeframe_returns_400() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/run/",
        data=_run_payload(timeframe="not-a-timeframe"),
        content_type="application/json",
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_run_backtest_then_get_and_list_results() -> None:
    client = _client_as_operator()
    run_response = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert run_response.status_code == 200
    body = run_response.json()
    assert "backtest_id" in body
    assert body["configuration"]["strategy_id"] == "ema_crossover"
    assert "trades" in body and isinstance(body["trades"], list)
    assert "equity_curve" in body
    assert "metrics" in body
    assert body["data_quality"]["data_quality"] == "FIXTURE_OR_HISTORICAL"

    backtest_id = body["backtest_id"]
    get_response = client.get(f"/api/v1/config/backtesting/results/{backtest_id}/")
    assert get_response.status_code == 200
    assert get_response.json()["backtest_id"] == backtest_id

    list_response = client.get("/api/v1/config/backtesting/strategies/ema_crossover/results/")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


@requires_postgres
@pytest.mark.django_db
def test_get_unknown_backtest_result_returns_404() -> None:
    client = _client_as_reader()
    response = client.get("/api/v1/config/backtesting/results/nonexistent/")
    assert response.status_code == 404


@requires_postgres
@pytest.mark.django_db
def test_rerunning_identical_configuration_upserts_same_backtest_id() -> None:
    client = _client_as_operator()
    first = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    second = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert first.json()["backtest_id"] == second.json()["backtest_id"]
    list_response = client.get("/api/v1/config/backtesting/strategies/ema_crossover/results/")
    assert len(list_response.json()) == 1  # upsert, not a duplicate row


@requires_postgres
@pytest.mark.django_db
def test_run_backtest_against_a_real_instrument_is_db_first_not_fixture_only() -> None:
    """Checkpoint 63.x follow-up: debugging the reported "no bars
    available for NSE:FIXTURE01" experience - a real instrument/date
    combination (never seen by the fixture repository at all) must now
    succeed via the same DB-first coverage/fetch/persist pipeline the
    multi-instrument historical-run panel uses, not fail outright."""
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/run/",
        data=_run_payload(
            instrument_id="NSE:RELIANCE",
            start="2026-08-17T03:45:00Z",
            end="2026-08-17T10:00:00Z",
        ),
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data_quality"]["bar_count"] > 0


@requires_postgres
@pytest.mark.django_db
def test_run_backtest_against_fixture_instrument_still_uses_the_deterministic_fixture() -> None:
    """The FIXTURE01 flow's own reproducibility/cost-model tests depend
    on this staying exactly as it was - never routed through the DB-
    first pipeline."""
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert response.status_code == 200
    assert response.json()["data_quality"]["data_source"] == (
        "HistoricalMarketDataRepository (fixture/historical only)"
    )
