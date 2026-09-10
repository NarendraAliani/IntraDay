# tests/unit/infrastructure/api/test_screening_api.py
#
# CHECKPOINT-SCANNER-B: API-level coverage for the read-only,
# Historical-mode-only `POST /api/v1/config/screening/evaluate/`
# endpoint. Real `HistoricalBar` fixtures (real PostgreSQL,
# `@requires_postgres`), real `ResearchDataGateService` gate - never
# mocked coverage/gate logic, matching this project's own established
# discipline for anything claiming to prove data-trustworthiness
# behavior.
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client

from intraday.application.services.historical_data_coverage import _expected_timestamps
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.models import HistoricalBar
from tests.postgres_utils import requires_postgres

USERNAME = "screening-tester"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105

# Checkpoint 67.12.2-O's own established convention, reused verbatim:
# 2026-08-17 is the one empirically-proven (NSE_EQ, 5m, CAS_ERA) date
# `ResearchDataGateService` actually accepts REAL_DHAN+CANONICALIZED
# rows for - the same date this whole session's own migration
# checkpoints (83 onward) used for exactly this reason.
CAS_ERA_TRADING_DATE = date(2026, 8, 17)
RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")


def _login_client() -> Client:
    User.objects.create_user(username=USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=USERNAME, password=PASSWORD)
    return client


def _gate_verified_bars(instrument_id, closes: list[float]) -> None:
    """Builds a full, gate-eligible day of `HistoricalBar` rows for
    `instrument_id` on `CAS_ERA_TRADING_DATE` - real `REAL_DHAN`
    provenance, real `CANONICALIZED` state, at the EXACT expected
    close-timestamps `HistoricalDataCoverageService` itself computes
    (never a guessed/approximate schedule), so
    `ResearchDataGateService.get_research_eligible_bars()` genuinely
    accepts them, not a synthetic bypass of the real gate."""
    timestamps = _expected_timestamps(
        datetime(2026, 8, 17, 3, 45, tzinfo=UTC),
        datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
        Timeframe.FIVE_MINUTE,
        instrument_id,
    )
    assert len(timestamps) == len(closes), (
        f"fixture must supply exactly {len(timestamps)} closes for a complete day, got {len(closes)}"
    )
    exchange, symbol = str(instrument_id).split(":")
    rows = []
    for ts, close in zip(timestamps, closes, strict=True):
        c = Decimal(str(close))
        rows.append(
            HistoricalBar(
                instrument_id=str(instrument_id),
                exchange=exchange,
                symbol=symbol,
                timeframe="5m",
                bar_timestamp=ts,
                open_price=c,
                high_price=c + Decimal("1"),
                low_price=c - Decimal("1"),
                close_price=c,
                volume=Decimal("1000"),
                source="API_FETCH",
                provenance=PROVENANCE_REAL_DHAN,
                canonicalization_state="CANONICALIZED",
                source_timestamp_semantics="CLOSE",
            )
        )
    HistoricalBar.objects.bulk_create(rows)


_EVALUATE_URL = "/api/v1/config/screening/evaluate/"


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_matched_instrument_reports_matched_status_with_evidence() -> None:
    client = _login_client()
    # 72 bars, steadily rising - the latest close is comfortably above 100.
    _gate_verified_bars(RELIANCE, [100 + i for i in range(72)])

    response = client.post(
        _EVALUATE_URL,
        data={
            "conditions": [{"field_id": "close", "operator": ">", "comparison": "100"}],
            "combinator": "AND",
            "instrument_ids": [str(RELIANCE)],
            "timeframe": "5m",
            "start_date": str(CAS_ERA_TRADING_DATE),
            "end_date": str(CAS_ERA_TRADING_DATE),
        },
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["mode"] == "HISTORICAL"
    assert body["matched_count"] == 1
    assert body["evaluated_count"] == 1
    assert body["not_gate_verified_count"] == 0
    result = body["results"][0]
    assert result["instrument_id"] == str(RELIANCE)
    assert result["status"] == "MATCHED"
    assert len(result["matched_condition_details"]) == 1
    assert "close" in result["matched_condition_details"][0]


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_no_match_instrument_reports_no_match_status() -> None:
    client = _login_client()
    _gate_verified_bars(RELIANCE, [100 + i for i in range(72)])  # last close ~171

    response = client.post(
        _EVALUATE_URL,
        data={
            "conditions": [{"field_id": "close", "operator": ">", "comparison": "500"}],
            "combinator": "AND",
            "instrument_ids": [str(RELIANCE)],
            "timeframe": "5m",
            "start_date": str(CAS_ERA_TRADING_DATE),
            "end_date": str(CAS_ERA_TRADING_DATE),
        },
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["matched_count"] == 0
    assert body["evaluated_count"] == 1
    result = body["results"][0]
    assert result["status"] == "NO_MATCH"
    assert result["matched_condition_details"] == []


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_insufficient_coverage_reports_not_gate_verified_honestly() -> None:
    """The honest-labeling requirement: an instrument with NO bars at
    all for the requested range must be reported as its own distinct
    NOT_GATE_VERIFIED status with a real rejection detail - never
    silently evaluated as a false NO_MATCH."""
    client = _login_client()
    # TCS has zero bars for this date - genuinely no data at all.

    response = client.post(
        _EVALUATE_URL,
        data={
            "conditions": [{"field_id": "close", "operator": ">", "comparison": "0"}],
            "combinator": "AND",
            "instrument_ids": [str(TCS)],
            "timeframe": "5m",
            "start_date": str(CAS_ERA_TRADING_DATE),
            "end_date": str(CAS_ERA_TRADING_DATE),
        },
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["matched_count"] == 0
    assert body["evaluated_count"] == 0
    assert body["not_gate_verified_count"] == 1
    result = body["results"][0]
    assert result["instrument_id"] == str(TCS)
    assert result["status"] == "NOT_GATE_VERIFIED"
    assert result["coverage_detail"] != ""
    assert "INCOMPLETE_COVERAGE" in result["coverage_detail"]


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_mixed_universe_reports_each_instrument_independently() -> None:
    client = _login_client()
    _gate_verified_bars(RELIANCE, [100 + i for i in range(72)])
    # TCS left with zero bars.

    response = client.post(
        _EVALUATE_URL,
        data={
            "conditions": [{"field_id": "close", "operator": ">", "comparison": "50"}],
            "combinator": "AND",
            "instrument_ids": [str(RELIANCE), str(TCS)],
            "timeframe": "5m",
            "start_date": str(CAS_ERA_TRADING_DATE),
            "end_date": str(CAS_ERA_TRADING_DATE),
        },
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    results_by_id = {r["instrument_id"]: r for r in body["results"]}
    assert results_by_id[str(RELIANCE)]["status"] == "MATCHED"
    assert results_by_id[str(TCS)]["status"] == "NOT_GATE_VERIFIED"
    assert body["matched_count"] == 1
    assert body["not_gate_verified_count"] == 1


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_or_combinator_and_field_vs_field_condition() -> None:
    client = _login_client()
    # A sharp, recent jump so the latest close sits above EMA(20).
    _gate_verified_bars(RELIANCE, [100] * 71 + [200])

    response = client.post(
        _EVALUATE_URL,
        data={
            "conditions": [
                {"field_id": "close", "operator": ">", "comparison": "ema_20"},
                {"field_id": "close", "operator": "<", "comparison": "1"},  # deliberately false
            ],
            "combinator": "OR",
            "instrument_ids": [str(RELIANCE)],
            "timeframe": "5m",
            "start_date": str(CAS_ERA_TRADING_DATE),
            "end_date": str(CAS_ERA_TRADING_DATE),
        },
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["results"][0]["status"] == "MATCHED"


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_unauthenticated_request_is_rejected() -> None:
    client = Client()
    response = client.post(
        _EVALUATE_URL,
        data={
            "conditions": [{"field_id": "close", "operator": ">", "comparison": "0"}],
            "combinator": "AND",
            "instrument_ids": [str(RELIANCE)],
            "timeframe": "5m",
            "start_date": str(CAS_ERA_TRADING_DATE),
            "end_date": str(CAS_ERA_TRADING_DATE),
        },
        content_type="application/json",
    )
    assert response.status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_invalid_operator_is_rejected_with_400() -> None:
    client = _login_client()
    response = client.post(
        _EVALUATE_URL,
        data={
            "conditions": [{"field_id": "close", "operator": "!=", "comparison": "0"}],
            "combinator": "AND",
            "instrument_ids": [str(RELIANCE)],
            "timeframe": "5m",
            "start_date": str(CAS_ERA_TRADING_DATE),
            "end_date": str(CAS_ERA_TRADING_DATE),
        },
        content_type="application/json",
    )
    assert response.status_code == 400
