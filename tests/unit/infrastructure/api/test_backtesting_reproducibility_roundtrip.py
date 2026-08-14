# tests/unit/infrastructure/api/test_backtesting_reproducibility_roundtrip.py
#
# Checkpoint 28 Part 17: verifies reproducibility survives persistence
# round-trip, API serialization, and API retrieval - the displayed
# result must correspond EXACTLY to the stored result, not merely have
# the same `backtest_id`.
from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from tests.postgres_utils import requires_postgres

OPERATOR_USERNAME = "roundtrip-operator"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


def _run_payload() -> dict[str, object]:
    return {
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


@requires_postgres
@pytest.mark.django_db
def test_displayed_result_matches_stored_result_exactly_after_roundtrip() -> None:
    client = _client_as_operator()
    run_response = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert run_response.status_code == 200
    run_body = run_response.json()

    backtest_id = run_body["backtest_id"]
    get_response = client.get(f"/api/v1/config/backtesting/results/{backtest_id}/")
    assert get_response.status_code == 200
    get_body = get_response.json()

    # Every field in the immediately-returned run response must survive
    # the persistence round-trip byte-for-byte (dict equality) - the
    # displayed result (what the frontend renders) corresponds exactly
    # to what was stored and re-fetched, not an approximation.
    assert run_body == get_body
    assert get_body["trust_level"] == "POC"
    assert "mark_to_market_curve" in get_body
    assert "validation" in get_body
    assert get_body["validation"]["bar_count"] == 8


@requires_postgres
@pytest.mark.django_db
def test_rerunning_same_configuration_produces_identical_persisted_payload() -> None:
    client = _client_as_operator()
    first = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    second = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    first_body = first.json()
    second_body = second.json()
    assert first_body["backtest_id"] == second_body["backtest_id"]
    assert first_body["trades"] == second_body["trades"]
    assert first_body["mark_to_market_curve"] == second_body["mark_to_market_curve"]
    assert first_body["metrics"] == second_body["metrics"]
