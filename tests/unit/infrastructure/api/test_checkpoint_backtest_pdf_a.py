# tests/unit/infrastructure/api/test_checkpoint_backtest_pdf_a.py
#
# CHECKPOINT-BACKTEST-PDF-A: proves the new, read-only
# `GET /backtesting/results/<backtest_id>/report/` endpoint generates
# a REAL, valid, multi-page PDF from an already-completed backtest
# result - not merely "a PDF was produced," a real text-extraction
# check that the expected field labels genuinely appear. Runs a real
# backtest first (against the deterministic `NSE:FIXTURE01` fixture,
# `test_backtesting_api.py`'s own established payload pattern, reused
# verbatim - no network, no real Dhan call), then requests its PDF
# report - never a hand-built, disconnected fixture dict.
from __future__ import annotations

import io

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from pypdf import PdfReader

from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from tests.postgres_utils import requires_postgres

OPERATOR_USERNAME = "bt-pdf-operator"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


def _run_payload(**overrides: object) -> dict[str, object]:
    # Reused verbatim from test_backtesting_api.py's own
    # `_run_payload()` - the deterministic NSE:FIXTURE01 flow, zero
    # network, zero real Dhan credentials involved.
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


def _extract_text(pdf_bytes: bytes) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    return text, len(reader.pages)


@requires_postgres
@pytest.mark.django_db
def test_pdf_report_is_a_real_valid_multipage_pdf_with_expected_field_labels() -> None:
    client = _client_as_operator()
    run_response = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert run_response.status_code == 200, run_response.content
    backtest_id = run_response.json()["backtest_id"]

    pdf_response = client.get(f"/api/v1/config/backtesting/results/{backtest_id}/report/")
    assert pdf_response.status_code == 200
    assert pdf_response["Content-Type"] == "application/pdf"

    text, page_count = _extract_text(pdf_response.content)
    # Single-instrument result -> 3 pages (Summary, Signal/Trade
    # Breakdown, Ratio Analysis), never a 4th "Results by Instrument"
    # page (that requires a real ?run_id= for a multi-instrument run -
    # see the next test).
    assert page_count == 3

    # Page 1 - Summary.
    assert "Backtest Report" in text
    assert "ema_crossover" in text
    assert "NSE:FIXTURE01" in text
    assert "Win Rate" in text
    assert "Profit Factor" in text
    assert "Total Trades" in text
    assert "Total Signals" in text

    # Page 2 - Signal/Trade breakdown.
    assert "Signals Generated" in text
    assert "Skipped Signals" in text
    assert "Rejected Trades" in text
    assert "Pass %" in text
    assert "Fail %" in text
    assert "Total Profit" in text
    assert "Total Loss" in text
    assert "Investment vs. Returns" in text or "Investment vs" in text

    # Page 3 - Ratio Analysis.
    assert "Ratio Analysis" in text
    assert "Sharpe" in text
    assert "Sortino" in text

    # The exact on-screen disclaimer language, reused verbatim - every
    # page's own footer, never dropped for a "cleaner" report.
    assert "RESULT, not a promise" in text
    assert "Data quality" in text


@requires_postgres
@pytest.mark.django_db
def test_pdf_report_returns_404_for_an_unknown_backtest_id() -> None:
    client = _client_as_operator()
    response = client.get("/api/v1/config/backtesting/results/does-not-exist/report/")
    assert response.status_code == 404


@requires_postgres
@pytest.mark.django_db
def test_pdf_report_unauthenticated_request_is_rejected() -> None:
    client = Client()
    response = client.get("/api/v1/config/backtesting/results/anything/report/")
    assert response.status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db
def test_pdf_report_with_run_id_adds_results_by_instrument_page_for_a_multi_instrument_run() -> (
    None
):
    """The optional `?run_id=` path - reuses the SAME
    `DjangoBacktestRunRepository`/`result_backtest_ids` mechanism the
    existing run-progress endpoint already exposes, never a second
    universe-resolution system. Runs two REAL, independent
    single-instrument backtests (both against the same deterministic
    fixture instrument, since only NSE:FIXTURE01 is network-free -
    genuinely two distinct `BacktestResult` rows either way) and
    fabricates only the RUN SNAPSHOT linking them (the run orchestrator
    itself is out of this checkpoint's own scope - Part 3 is read-only
    PDF rendering over already-computed results, never new backtest
    computation)."""
    from datetime import UTC, date, datetime
    from decimal import Decimal

    from intraday.infrastructure.persistence.historical_backtest_run_repository import (
        DjangoBacktestRunRepository,
    )

    client = _client_as_operator()
    first = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    second = client.post(
        "/api/v1/config/backtesting/run/",
        # `_deterministic_backtest_id()` is derived from configuration +
        # DATA identity (instrument/timeframe/date-range/bar-count) +
        # cost-model identity - deliberately NOT `strategy_values` (see
        # `research/backtesting/engine.py`'s own docstring: "same bars,
        # different cost model must never collide"). A different
        # `strategy_values` alone would silently produce the SAME
        # backtest_id and overwrite the first result - widening the end
        # timestamp gives this second run genuinely different bars, and
        # therefore a genuinely distinct id, for this test's own purpose
        # (two REAL, independent `BacktestResult` rows).
        data=_run_payload(end="2026-01-02T06:30:00Z"),
        content_type="application/json",
    )
    assert first.status_code == 200, first.content
    assert second.status_code == 200, second.content
    first_id = first.json()["backtest_id"]
    second_id = second.json()["backtest_id"]

    now = datetime.now(tz=UTC)
    run_repository = DjangoBacktestRunRepository()
    run_repository.create(
        "pdf-a-multi-run",
        created_by=OPERATOR_USERNAME,
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 2),
        timeframe="5m",
        instrument_ids=["NSE:FIXTURE01", "NSE:FIXTUREB"],
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        strategy_values={"fast_lookback": 3, "slow_lookback": 6},
        cost_model_name="FLAT_PERCENTAGE",
        initial_capital=Decimal("100000"),
        position_sizing_mode="FIXED_QUANTITY",
        position_size_value=Decimal("10"),
        brokerage_percent=Decimal("0"),
        slippage_percent=Decimal("0"),
        total_instruments=2,
    )
    run_repository.update(
        "pdf-a-multi-run",
        status="COMPLETED",
        phase="DONE",
        completed_instruments=2,
        result_backtest_ids={"NSE:FIXTURE01": first_id, "NSE:FIXTUREB": second_id},
        completed_at=now,
    )

    snapshot = run_repository.get("pdf-a-multi-run")
    assert snapshot is not None
    assert snapshot.result_backtest_ids == {"NSE:FIXTURE01": first_id, "NSE:FIXTUREB": second_id}

    pdf_response = client.get(
        f"/api/v1/config/backtesting/results/{first_id}/report/?run_id=pdf-a-multi-run"
    )
    assert pdf_response.status_code == 200
    text, page_count = _extract_text(pdf_response.content)
    assert page_count == 4, "expected a 4th 'Results by Instrument' page"
    assert "Results by Instrument" in text
    assert "NSE:FIXTURE01" in text
