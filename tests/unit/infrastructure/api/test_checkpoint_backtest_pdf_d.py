# tests/unit/infrastructure/api/test_checkpoint_backtest_pdf_d.py
#
# CHECKPOINT-BACKTEST-PDF-D: proves Issue 1 (IST conversion) and
# Issue 2 (running header replacing the divider page) with real PDF
# generation + real `pypdf` text-extraction checks. Reuses the same
# dict-level fixture pattern `test_checkpoint_backtest_pdf_c.py`
# established (a dict matching the EXACT `to_json_dict()` shape,
# differing from a real run only in trade COUNT/timestamps, never in
# shape) - not a second, invented fixture convention.
from __future__ import annotations

import io

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from pypdf import PdfReader

from intraday.application.services.backtest_pdf_report import build_backtest_report_pdf
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from tests.postgres_utils import requires_postgres

OPERATOR_USERNAME = "bt-pdf-d-operator"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


def _run_payload(**overrides: object) -> dict[str, object]:
    # Reused verbatim from the PDF-A/PDF-C test files' own established
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


def _extract_page_texts(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [page.extract_text() or "" for page in reader.pages]


def _trade(index: int, *, entry_hour: int = 4, entry_minute: int = 0) -> dict[str, object]:
    return {
        "trade_id": f"ema_crossover-{index}",
        "strategy_id": "ema_crossover",
        "instrument_id": "NSE:FIXTURE01",
        "timeframe": "5m",
        "direction": "BULLISH",
        "entry_timestamp": f"2026-01-02T{entry_hour:02d}:{entry_minute:02d}:00Z",
        "entry_price": "100.00",
        "exit_timestamp": f"2026-01-02T{entry_hour:02d}:{(entry_minute + 5) % 60:02d}:00Z",
        "exit_price": "102.00",
        "quantity": "10",
        "gross_pnl": "20.00",
        "costs": "1.00",
        "net_pnl": "19.00",
        "reason": "signal_reversal",
        "cost_breakdown": {
            "brokerage": "0.50", "stt": "0.20", "exchange_transaction_charges": "0.10",
            "sebi_charges": "0.05", "gst": "0.10", "stamp_duty": "0.05",
            "other_statutory_charges": "0.00", "total": "1.00",
        },
    }


def _result(instrument_id: str = "NSE:FIXTURE01", *, n_trades: int = 1) -> dict[str, object]:
    """A dict matching the EXACT `to_json_dict()` shape (see
    `test_checkpoint_backtest_pdf_c.py`'s own identical convention)."""
    trades = [_trade(i) for i in range(n_trades)]
    return {
        "backtest_id": f"bt-{instrument_id}",
        # UTC 06:00:00 -> IST (UTC+5:30) 11:30:00 - a known conversion.
        "generated_at": "2026-01-02T06:00:00Z",
        "configuration": {
            "instrument_id": instrument_id, "timeframe": "5m",
            # UTC 03:00:00 -> IST 08:30:00; UTC 06:00:00 -> IST 11:30:00.
            "start": "2026-01-02T03:00:00Z", "end": "2026-01-02T06:00:00Z",
            "strategy_id": "ema_crossover", "specification_version": "v1", "code_version": "v1",
            "configuration_version": "v1", "initial_capital": "100000",
            "position_sizing_mode": "FIXED_QUANTITY", "position_size_value": "10",
        },
        "trades": trades,
        "equity_curve": [],
        "mark_to_market_curve": [
            {"timestamp": "2026-01-02T04:00:00Z", "total_equity": "100000", "drawdown_percent": "0"},
            {"timestamp": "2026-01-02T04:10:00Z", "total_equity": "100500", "drawdown_percent": "0"},
        ],
        "metrics": {
            "total_trades": n_trades, "winning_trades": n_trades, "losing_trades": 0,
            "win_rate_percent": "100.00", "gross_profit": str(20 * n_trades), "gross_loss": "0",
            "net_pnl": str(19 * n_trades), "profit_factor": "2.40", "max_drawdown": "500",
            "max_drawdown_percent": "0.50", "max_drawdown_duration_bars": 3,
            "average_trade": "19", "average_winner": "19", "average_loser": None,
            "sharpe_ratio_trade_level": "1.15", "sortino_ratio_trade_level": "1.60",
            "final_capital": str(100000 + 19 * n_trades), "return_percent": "0.418",
        },
        "data_quality": {
            "data_source": "fixture", "data_quality": "TRADING_GRADE_BAR", "bar_count": 72,
            "missing_bar_note": "",
            "transaction_cost_assumption": "Flat 0% brokerage assumed.",
            "slippage_assumption": "No slippage assumed.",
            "survivorship_bias_note": "No survivorship bias adjustment applied.",
        },
        "validation": {
            "bar_count": 72, "signal_count": n_trades + 3, "trade_count": n_trades,
            "warmup_bars": 6, "skipped_signals": 2, "rejected_trades": 1,
            "data_gaps_note": "None detected.",
        },
        "trust_level": "POC",
        "cost_model_identity": {
            "name": "FLAT_PERCENTAGE", "version": "1", "effective_from": "2026-01-01",
            "is_verified": False,
        },
    }


# ---------------------------------------------------------------------------
# Issue 1 - IST conversion
# ---------------------------------------------------------------------------


def test_trade_ledger_times_are_converted_to_ist_not_raw_utc() -> None:
    """A known UTC timestamp converts to the correct IST value
    (UTC+5:30) in the rendered PDF, not the raw UTC value."""
    result = _result(n_trades=1)
    pdf_bytes = build_backtest_report_pdf(result)
    text, _ = _extract_text(pdf_bytes)

    # Trade #1's own entry_timestamp is 2026-01-02T04:00:00Z (UTC) ->
    # 2026-01-02 09:30:00 IST. The raw UTC time must never appear as a
    # rendered trade time.
    assert "09:30:00" in text
    assert "04:00:00" not in text


def test_generated_and_date_range_are_converted_to_ist() -> None:
    result = _result(n_trades=1)
    pdf_bytes = build_backtest_report_pdf(result)
    text, _ = _extract_text(pdf_bytes)

    # "Generated" (2026-01-02T06:00:00Z UTC -> 11:30:00 IST).
    assert "2026-01-02 11:30:00 IST" in text
    # Configuration date range (03:00 UTC -> 08:30 IST, 06:00 UTC ->
    # 11:30 IST).
    assert "2026-01-02 08:30:00 IST to 2026-01-02 11:30:00 IST" in text
    # Never the raw, un-converted UTC strings.
    assert "2026-01-02T06:00:00Z" not in text
    assert "2026-01-02T03:00:00Z" not in text


def test_ist_conversion_survives_a_utc_calendar_date_boundary() -> None:
    """IST is UTC+5:30 - a UTC timestamp late in the day rolls over to
    the NEXT calendar date in IST. Confirms the date, not just the
    time, is converted correctly."""
    result = _result(n_trades=1)
    result["trades"][0]["entry_timestamp"] = "2026-01-02T19:15:00Z"
    result["trades"][0]["exit_timestamp"] = "2026-01-02T19:20:00Z"
    pdf_bytes = build_backtest_report_pdf(result)
    text, _ = _extract_text(pdf_bytes)

    # 2026-01-02T19:15:00Z UTC -> 2026-01-03 00:45:00 IST.
    assert "2026-01-03" in text
    assert "00:45:00" in text


# ---------------------------------------------------------------------------
# Issue 2 - running header replaces the divider page
# ---------------------------------------------------------------------------


def test_multi_instrument_running_header_replaces_the_old_divider_page() -> None:
    """The combined file's per-instrument section break is now a
    running header BANNER at the top of that instrument's own first
    content page, not a separate, mostly-blank divider page - fewer
    total pages than CHECKPOINT-BACKTEST-PDF-C's own divider-page
    design, same navigability."""
    primary = _result("NSE:FIXTURE01", n_trades=1)
    sibling = _result("NSE:FIXTUREB", n_trades=1)

    pdf_bytes = build_backtest_report_pdf(primary, sibling_results=[sibling])
    text, page_count = _extract_text(pdf_bytes)
    page_texts = _extract_page_texts(pdf_bytes)

    # 1 index page + instrument1 (Summary/Signal/Ratio/Ledger = 4) +
    # instrument2 (same shape = 4) = 9, not 11 (PDF-C's own count,
    # which still had 2 separate divider pages).
    assert page_count == 9
    assert "Instrument 1 of 2" in text
    assert "Instrument 2 of 2" in text

    # The running header for instrument 2 shares its page with real
    # report content ("Backtest Report" / "Configuration"), proving it
    # is a banner on the content page, not its own page.
    running_header_page = next(p for p in page_texts if "Instrument 2 of 2" in p)
    assert "Backtest Report" in running_header_page
    assert "Configuration" in running_header_page


def test_single_instrument_report_has_no_running_header() -> None:
    result = _result(n_trades=1)
    pdf_bytes = build_backtest_report_pdf(result)
    text, _ = _extract_text(pdf_bytes)
    assert "Instrument 1 of 1" not in text


# ---------------------------------------------------------------------------
# Real, end-to-end HTTP proof - confirms both fixes are wired into the
# live endpoint, not just correct in the pure function.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_real_backtest_pdf_report_shows_ist_times_end_to_end() -> None:
    client = _client_as_operator()
    run_response = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert run_response.status_code == 200, run_response.content
    backtest_id = run_response.json()["backtest_id"]

    pdf_response = client.get(f"/api/v1/config/backtesting/results/{backtest_id}/report/")
    assert pdf_response.status_code == 200
    text, _ = _extract_text(pdf_response.content)

    # The run's own "Generated" timestamp is set by the server at
    # request time - can't assert an exact IST value here - but the
    # " IST" suffix must appear, and the raw "Z"-suffixed UTC string
    # must never be shown directly in the Generated/date-range lines.
    assert " IST" in text
    assert "2026-01-02T03:00:00Z" not in text
    assert "2026-01-02T06:00:00Z" not in text
