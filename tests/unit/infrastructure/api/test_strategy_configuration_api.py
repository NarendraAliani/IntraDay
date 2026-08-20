# tests/unit/infrastructure/api/test_strategy_configuration_api.py
#
# Endpoint tests for the Checkpoint 26 strategy-configuration API
# resource. Mirrors test_strategy_api.py's structure/auth pattern.
from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from tests.postgres_utils import requires_postgres

READER_USERNAME = "cfg-reader"  # noqa: S105
OPERATOR_USERNAME = "cfg-operator"  # noqa: S105
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


@requires_postgres
@pytest.mark.django_db
def test_field_registry_endpoint_lists_canonical_fields() -> None:
    client = _client_as_reader()
    response = client.get("/api/v1/config/strategy-engine/fields/")
    assert response.status_code == 200
    field_ids = {row["field_id"] for row in response.json()}
    assert field_ids == {"open", "high", "low", "close", "volume", "sma", "ema", "atr"}


@requires_postgres
@pytest.mark.django_db
def test_strategies_endpoint_lists_at_least_three() -> None:
    client = _client_as_reader()
    response = client.get("/api/v1/config/strategy-engine/strategies/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 3
    ids = [row["strategy_id"] for row in body]
    assert len(ids) == len(set(ids))


@requires_postgres
@pytest.mark.django_db
def test_strategy_schema_endpoint_returns_parameters() -> None:
    client = _client_as_reader()
    response = client.get("/api/v1/config/strategy-engine/strategies/ema_crossover/schema/")
    assert response.status_code == 200
    body = response.json()
    assert body["strategy_id"] == "ema_crossover"
    parameter_ids = {p["parameter_id"] for p in body["parameters"]}
    assert parameter_ids == {"fast_lookback", "slow_lookback"}


@requires_postgres
@pytest.mark.django_db
def test_strategy_schema_endpoint_exposes_the_conservative_baseline_defaults() -> None:
    """Checkpoint 64.17 §13/§14: `ParameterDefinition.default` is the
    ONE canonical source a new-configuration form pre-fills from - this
    proves the API actually serializes the real, current conservative
    baseline values (12/26 for EMA), never a duplicated/stale default
    living anywhere else."""
    client = _client_as_reader()

    ema = client.get("/api/v1/config/strategy-engine/strategies/ema_crossover/schema/").json()
    ema_defaults = {p["parameter_id"]: p["default"] for p in ema["parameters"]}
    assert ema_defaults == {"fast_lookback": 12, "slow_lookback": 26}

    sma = client.get("/api/v1/config/strategy-engine/strategies/sma_trend_filter/schema/").json()
    sma_defaults = {p["parameter_id"]: p["default"] for p in sma["parameters"]}
    assert sma_defaults == {"lookback": 30, "band_percent": 0.75}

    atr = client.get(
        "/api/v1/config/strategy-engine/strategies/atr_volatility_breakout/schema/"
    ).json()
    atr_defaults = {p["parameter_id"]: p["default"] for p in atr["parameters"]}
    assert atr_defaults == {
        "lookback": 14,
        "atr_multiplier": 2.0,
        "stop_loss_atr_multiplier": 1.0,
        "target_1_atr_multiplier": 1.5,
        "target_2_atr_multiplier": 2.5,
        "target_3_atr_multiplier": 3.5,
        "trailing_stop_atr_multiplier": 1.0,
    }


@requires_postgres
@pytest.mark.django_db
def test_strategy_schema_endpoint_unknown_strategy_returns_404() -> None:
    client = _client_as_reader()
    response = client.get("/api/v1/config/strategy-engine/strategies/nonexistent/schema/")
    assert response.status_code == 404


@requires_postgres
@pytest.mark.django_db
def test_unauthenticated_request_is_rejected() -> None:
    client = Client()
    response = client.get("/api/v1/config/strategy-engine/strategies/")
    assert response.status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db
def test_save_configuration_requires_operator_role() -> None:
    client = _client_as_reader()
    response = client.post(
        "/api/v1/config/strategy-engine/strategies/ema_crossover/configurations/save/",
        data={
            "specification_version": "v1",
            "code_version": "v1",
            "configuration_version": "cfg-v1",
            "values": {"fast_lookback": 5, "slow_lookback": 10},
        },
        content_type="application/json",
    )
    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_save_configuration_then_list_and_get() -> None:
    client = _client_as_operator()
    save_response = client.post(
        "/api/v1/config/strategy-engine/strategies/ema_crossover/configurations/save/",
        data={
            "specification_version": "v1",
            "code_version": "v1",
            "configuration_version": "cfg-v1",
            "values": {"fast_lookback": 5, "slow_lookback": 10},
        },
        content_type="application/json",
    )
    assert save_response.status_code == 201

    list_response = client.get(
        "/api/v1/config/strategy-engine/strategies/ema_crossover/configurations/"
    )
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = client.get(
        "/api/v1/config/strategy-engine/strategies/ema_crossover/configurations/" "v1/v1/cfg-v1/"
    )
    assert get_response.status_code == 200
    assert get_response.json()["values"] == {"fast_lookback": 5, "slow_lookback": 10}


@requires_postgres
@pytest.mark.django_db
def test_save_configuration_rejects_invalid_values() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/strategy-engine/strategies/ema_crossover/configurations/save/",
        data={
            "specification_version": "v1",
            "code_version": "v1",
            "configuration_version": "cfg-v1",
            "values": {"fast_lookback": "not-an-int", "slow_lookback": 10},
        },
        content_type="application/json",
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_save_configuration_rejects_duplicate_identity() -> None:
    client = _client_as_operator()
    payload = {
        "specification_version": "v1",
        "code_version": "v1",
        "configuration_version": "cfg-v1",
        "values": {"fast_lookback": 5, "slow_lookback": 10},
    }
    first = client.post(
        "/api/v1/config/strategy-engine/strategies/ema_crossover/configurations/save/",
        data=payload,
        content_type="application/json",
    )
    assert first.status_code == 201
    second = client.post(
        "/api/v1/config/strategy-engine/strategies/ema_crossover/configurations/save/",
        data=payload,
        content_type="application/json",
    )
    assert second.status_code == 409


@requires_postgres
@pytest.mark.django_db
def test_save_configuration_accepts_a_decimal_typed_parameter_sent_as_a_json_string() -> None:
    """The same real bug found and fixed in the backtesting flow: JSON
    has no native Decimal type, so sma_trend_filter's DECIMAL-typed
    band_percent can only ever arrive here as a string/number. Proves
    the save succeeds, and that the stored/returned value round-trips
    as the original JSON-safe value (never a raw Decimal that a plain
    JSONField couldn't have stored in the first place)."""
    client = _client_as_operator()
    save_response = client.post(
        "/api/v1/config/strategy-engine/strategies/sma_trend_filter/configurations/save/",
        data={
            "specification_version": "v1",
            "code_version": "v1",
            "configuration_version": "cfg-decimal-v1",
            "values": {"lookback": 20, "band_percent": "0.02"},
        },
        content_type="application/json",
    )
    assert save_response.status_code == 201
    assert save_response.json()["values"] == {"lookback": 20, "band_percent": "0.02"}

    get_response = client.get(
        "/api/v1/config/strategy-engine/strategies/sma_trend_filter/configurations/"
        "v1/v1/cfg-decimal-v1/"
    )
    assert get_response.status_code == 200
    assert get_response.json()["values"] == {"lookback": 20, "band_percent": "0.02"}
