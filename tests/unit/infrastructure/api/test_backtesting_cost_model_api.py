# tests/unit/infrastructure/api/test_backtesting_cost_model_api.py
#
# Checkpoint 29: proves cost-model selection survives the full stack -
# API request -> engine -> persistence -> API retrieval - and that
# switching cost models via the real API changes the backtest_id
# (Part 16/19).
from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from tests.postgres_utils import requires_postgres

OPERATOR_USERNAME = "cost-model-operator"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


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
        "brokerage_percent": "0.03",
        "slippage_percent": "0",
    }
    payload.update(overrides)
    return payload


@requires_postgres
@pytest.mark.django_db
def test_default_cost_model_is_flat_percentage_not_verified() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cost_model_identity"]["name"] == "FLAT_PERCENTAGE"
    assert body["cost_model_identity"]["is_verified"] is False


@requires_postgres
@pytest.mark.django_db
def test_verified_indian_cost_model_selectable_via_api_and_exposes_breakdown() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/run/",
        data=_run_payload(cost_model_name="INDIAN_CASH_EQUITY_INTRADAY"),
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cost_model_identity"]["name"] == "INDIAN_CASH_EQUITY_INTRADAY"
    assert body["cost_model_identity"]["is_verified"] is True
    assert body["cost_model_identity"]["version"] == "v1"
    assert "effective_from" in body["cost_model_identity"]
    if body["trades"]:
        trade = body["trades"][0]
        assert "cost_breakdown" in trade
        for key in (
            "brokerage",
            "stt",
            "exchange_transaction_charges",
            "sebi_charges",
            "gst",
            "stamp_duty",
            "total",
        ):
            assert key in trade["cost_breakdown"]


@requires_postgres
@pytest.mark.django_db
def test_invalid_cost_model_name_returns_400() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/run/",
        data=_run_payload(cost_model_name="NOT_A_REAL_MODEL"),
        content_type="application/json",
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_switching_cost_model_produces_a_different_backtest_id_via_api() -> None:
    client = _client_as_operator()
    flat_response = client.post(
        "/api/v1/config/backtesting/run/",
        data=_run_payload(cost_model_name="FLAT_PERCENTAGE"),
        content_type="application/json",
    )
    indian_response = client.post(
        "/api/v1/config/backtesting/run/",
        data=_run_payload(cost_model_name="INDIAN_CASH_EQUITY_INTRADAY"),
        content_type="application/json",
    )
    assert flat_response.json()["backtest_id"] != indian_response.json()["backtest_id"]


@requires_postgres
@pytest.mark.django_db
def test_stored_and_retrieved_result_preserve_cost_model_identity_exactly() -> None:
    client = _client_as_operator()
    run_response = client.post(
        "/api/v1/config/backtesting/run/",
        data=_run_payload(cost_model_name="INDIAN_CASH_EQUITY_INTRADAY"),
        content_type="application/json",
    )
    backtest_id = run_response.json()["backtest_id"]
    get_response = client.get(f"/api/v1/config/backtesting/results/{backtest_id}/")
    assert get_response.json()["cost_model_identity"] == run_response.json()["cost_model_identity"]
