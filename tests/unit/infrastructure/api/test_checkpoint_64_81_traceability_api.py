# tests/unit/infrastructure/api/test_checkpoint_64_81_traceability_api.py
#
# Checkpoint 64.81 Phase 10: API-contract coverage for the traceability
# fields, plus OpenAPI schema verification. Mirrors
# `test_signal_api.py`'s established pattern (real Django test Client
# against the real URLconf, real persisted rows, never fabricated data).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client

from intraday.infrastructure.persistence.models import (
    PaperOrderRecord,
    PaperTradeRecord,
    SignalEvidenceRecord,
    SignalRecord,
)
from tests.postgres_utils import requires_postgres

READER_USERNAME = "traceability_reader"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105

BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
VERSION_IDENTIFIER = "specv1:codev1:configv1"


def _client() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


def _signal(**overrides: object) -> SignalRecord:
    defaults: dict[str, object] = {
        "signal_id": "sig-1",
        "strategy_id": "ema_crossover",
        "instrument_id": "NSE:RELIANCE",
        "direction": "BULLISH",
        "price": Decimal("101"),
        "timeframe": "1m",
        "signal_timestamp": BASE,
        "risk_status": "APPROVED",
    }
    defaults.update(overrides)
    return SignalRecord.objects.create(**defaults)


def _order(**overrides: object) -> PaperOrderRecord:
    defaults: dict[str, object] = {
        "order_id": "order-1",
        "idempotency_key": "idem-1",
        "correlation_id": "corr-1",
        "instrument_id": "NSE:RELIANCE",
        "strategy_id": "ema_crossover",
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": Decimal("10"),
        "filled_quantity": Decimal("10"),
        "status": "FILLED",
        "created_at": BASE,
    }
    defaults.update(overrides)
    return PaperOrderRecord.objects.create(**defaults)


def _trade(**overrides: object) -> PaperTradeRecord:
    defaults: dict[str, object] = {
        "trade_id": "trade-1",
        "strategy_id": "ema_crossover",
        "instrument_id": "NSE:RELIANCE",
        "direction": "BUY",
        "order_ids": ["order-1"],
        "entry_price": Decimal("100"),
        "exit_price": Decimal("101"),
        "quantity": Decimal("10"),
        "realized_pnl": Decimal("10"),
        "opened_at": BASE,
        "closed_at": BASE,
    }
    defaults.update(overrides)
    return PaperTradeRecord.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Signal response: scan_run_id + evidence field identity
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_signal_response_exposes_scan_run_id_when_a_run_produced_it() -> None:
    _signal(scan_run_id="2026-01-05T03:45:00+00:00")
    body = _client().get("/api/v1/config/signals/").json()
    assert body["items"][0]["scan_run_id"] == "2026-01-05T03:45:00+00:00"


@requires_postgres
@pytest.mark.django_db
def test_signal_response_exposes_the_exact_strategy_version() -> None:
    _signal(strategy_version_identifier=VERSION_IDENTIFIER)
    body = _client().get("/api/v1/config/signals/").json()
    assert body["items"][0]["strategy_version_identifier"] == VERSION_IDENTIFIER


@requires_postgres
@pytest.mark.django_db
def test_signal_without_recorded_version_reports_null() -> None:
    _signal()
    body = _client().get("/api/v1/config/signals/").json()
    assert body["items"][0]["strategy_version_identifier"] is None


@requires_postgres
@pytest.mark.django_db
def test_signal_response_reports_null_scan_run_id_rather_than_empty_string() -> None:
    """A signal not produced by a tracked scanner run must be
    distinguishable from one that was - `null`, never `""`."""
    _signal()
    body = _client().get("/api/v1/config/signals/").json()
    assert body["items"][0]["scan_run_id"] is None


@requires_postgres
@pytest.mark.django_db
def test_signal_evidence_exposes_feature_name_and_field_id() -> None:
    _signal()
    SignalEvidenceRecord.objects.create(
        signal_id="sig-1",
        strategy_id="ema_crossover",
        schema_version="1",
        fields=[["Fast EMA", "100.5", "ema_3"], ["Price", "101", None]],
        generated_at=BASE,
    )
    body = _client().get("/api/v1/config/signals/").json()
    fields = body["items"][0]["evidence"]["fields"]

    assert fields[0]["label"] == "Fast EMA"
    assert fields[0]["value"] == "100.5"
    assert fields[0]["feature_name"] == "ema_3"
    assert fields[0]["field_id"] == "ema"

    # A genuinely non-feature row carries no fabricated identity.
    assert fields[1]["label"] == "Price"
    assert fields[1]["feature_name"] is None
    assert fields[1]["field_id"] is None


@requires_postgres
@pytest.mark.django_db
def test_legacy_evidence_rows_still_serialize_cleanly() -> None:
    """Pre-64.81 2-element rows must remain renderable through the API."""
    _signal()
    SignalEvidenceRecord.objects.create(
        signal_id="sig-1",
        strategy_id="ema_crossover",
        schema_version="1",
        fields=[["Fast EMA", "100.5"]],
        generated_at=BASE,
    )
    body = _client().get("/api/v1/config/signals/").json()
    field = body["items"][0]["evidence"]["fields"][0]
    assert field["label"] == "Fast EMA"
    assert field["value"] == "100.5"
    assert field["feature_name"] is None
    assert field["field_id"] is None


# ---------------------------------------------------------------------------
# Paper order / trade responses
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_paper_order_response_exposes_signal_id() -> None:
    _order(signal_id="sig-1")
    body = _client().get("/api/v1/config/paper-trading/orders/").json()
    assert body[0]["signal_id"] == "sig-1"


@requires_postgres
@pytest.mark.django_db
def test_manual_paper_order_reports_null_not_a_fabricated_signal() -> None:
    _order()
    body = _client().get("/api/v1/config/paper-trading/orders/").json()
    assert body[0]["signal_id"] is None


@requires_postgres
@pytest.mark.django_db
def test_paper_trade_response_exposes_signal_and_version_resolved_through_it() -> None:
    """The version is NOT stored on the trade - it is read through
    `signal_id` from the signal that made the decision."""
    _signal(signal_id="sig-1", strategy_version_identifier=VERSION_IDENTIFIER)
    _trade(signal_id="sig-1")
    body = _client().get("/api/v1/config/paper-trading/trades/").json()
    assert body[0]["signal_id"] == "sig-1"
    assert body[0]["strategy_version_identifier"] == VERSION_IDENTIFIER


@requires_postgres
@pytest.mark.django_db
def test_paper_trade_without_traceability_reports_null() -> None:
    _trade()
    body = _client().get("/api/v1/config/paper-trading/trades/").json()
    assert body[0]["signal_id"] is None
    assert body[0]["strategy_version_identifier"] is None


# ---------------------------------------------------------------------------
# Strategy configuration: required_features
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_strategy_configuration_response_exposes_resolved_required_features() -> None:
    from intraday.infrastructure.persistence.models import StrategyConfigurationRecord

    StrategyConfigurationRecord.objects.create(
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        parameter_values={"fast_lookback": 3, "slow_lookback": 5},
        created_at=BASE,
        created_by="tester",
    )
    body = (
        _client()
        .get("/api/v1/config/strategy-engine/strategies/ema_crossover/configurations/")
        .json()
    )
    required = body[0]["required_features"]

    assert [f["feature_name"] for f in required] == ["ema_3", "ema_5"]
    assert [f["field_id"] for f in required] == ["ema", "ema"]
    assert [f["parameters"] for f in required] == [[3], [5]]
    assert required[0]["display_name"] == "Exponential Moving Average"


# ---------------------------------------------------------------------------
# OpenAPI schema verification
# ---------------------------------------------------------------------------


def _openapi_schema() -> dict:
    from drf_spectacular.generators import SchemaGenerator

    return SchemaGenerator().get_schema(request=None, public=True)


@requires_postgres
@pytest.mark.django_db
def test_openapi_schema_contains_every_new_traceability_field() -> None:
    """Guards the generated contract itself - if a field stops being
    emitted, the frontend silently loses it, so this asserts on the
    schema rather than only on runtime responses."""
    schemas = _openapi_schema()["components"]["schemas"]

    signal_properties = schemas["SignalResponse"]["properties"]
    assert "scan_run_id" in signal_properties
    assert "strategy_version_identifier" in signal_properties
    for name in ("PaperOrderResponse", "PaperTradeResponse"):
        assert "signal_id" in schemas[name]["properties"], name
    # The version is exposed on the TRADE too, resolved through the
    # signal - but deliberately NOT on the order (see the migration
    # header for why it is not duplicated).
    assert "strategy_version_identifier" in schemas["PaperTradeResponse"]["properties"]
    assert "strategy_version_identifier" not in schemas["PaperOrderResponse"]["properties"]
    assert "required_features" in schemas["StrategyConfigurationResponse"]["properties"]

    required_feature = schemas["RequiredFeature"]["properties"]
    for key in ("feature_name", "field_id", "display_name", "parameters"):
        assert key in required_feature, key

    evidence_field = schemas["SignalEvidenceField"]["properties"]
    for key in ("label", "value", "feature_name", "field_id"):
        assert key in evidence_field, key
