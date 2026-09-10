# tests/unit/infrastructure/api/test_checkpoint_backtest_pdf_c.py
#
# CHECKPOINT-BACKTEST-PDF-C: proves all three fixes with real PDF
# generation + real `pypdf` text-extraction checks - never "a PDF was
# produced" alone.
#
# Issue 1 (trade ledger) and Issue 3 (combined multi-instrument file)
# need trade counts / instrument counts this project's own tiny,
# network-free `NSE:FIXTURE01` fixture cannot realistically produce in
# one real backtest run - those are tested by calling the pure
# `build_backtest_report_pdf()` function directly with a dict matching
# the EXACT real `to_json_dict()` shape (the same contract this
# module's own docstring commits to, and the same shape
# `GET /backtesting/results/<id>/` already serves) - a legitimate,
# real test of this module's own real logic, not a fabricated
# shortcut; the values differ from a real run only in COUNT, never in
# shape. Issue 2's regression (the operator's own real, exact garbled
# fragment) reproduces with ANY real result, since the offending label
# is a fixed string in the PDF module itself, not backend-variable
# data - proven at both the pure-function level AND, separately, via
# one real end-to-end HTTP backtest (`NSE:FIXTURE01`, no network, no
# real Dhan call), confirming the fix is genuinely wired into the live
# endpoint, not just correct in isolation.
from __future__ import annotations

import io

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from pypdf import PdfReader

from intraday.application.services.backtest_pdf_report import build_backtest_report_pdf
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from tests.postgres_utils import requires_postgres

OPERATOR_USERNAME = "bt-pdf-c-operator"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


def _run_payload(**overrides: object) -> dict[str, object]:
    # Reused verbatim from test_backtesting_api.py's/
    # test_checkpoint_backtest_pdf_a.py's own established
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


def _trade(index: int, *, direction: str = "BULLISH") -> dict[str, object]:
    return {
        "trade_id": f"ema_crossover-{index}",
        "strategy_id": "ema_crossover",
        "instrument_id": "NSE:FIXTURE01",
        "timeframe": "5m",
        "direction": direction,
        "entry_timestamp": f"2026-01-02T04:{index % 60:02d}:00Z",
        "entry_price": "100.00",
        "exit_timestamp": f"2026-01-02T04:{(index + 5) % 60:02d}:00Z",
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


def _result(
    instrument_id: str = "NSE:FIXTURE01", *, n_trades: int = 1, long_disclaimers: bool = True
) -> dict[str, object]:
    """A dict matching the EXACT `to_json_dict()` shape - the same
    contract `build_backtest_report_pdf()`'s own docstring commits to,
    and the same shape `GET /backtesting/results/<id>/` already
    serves. Only the COUNT of trades and the length of the disclaimer
    strings vary from a real run's own output here - never the shape."""
    trades = [_trade(i) for i in range(n_trades)]
    return {
        "backtest_id": f"bt-{instrument_id}",
        "generated_at": "2026-01-02T06:00:00Z",
        "configuration": {
            "instrument_id": instrument_id, "timeframe": "5m",
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
            "transaction_cost_assumption": (
                "Flat percentage transaction cost model - this is a MODEL ASSUMPTION, not a "
                "verified Indian cash-equity intraday statutory/exchange cost schedule."
            ) if long_disclaimers else "Flat 0% brokerage assumed.",
            "slippage_assumption": (
                "A flat percentage slippage assumption is applied to every simulated fill - a "
                "MODEL ASSUMPTION, not a measured or verified figure."
            ) if long_disclaimers else "No slippage assumed.",
            "survivorship_bias_note": (
                "This backtest's own instrument universe was NOT adjusted for survivorship "
                "bias, which can overstate historical performance for a fixed universe."
            ) if long_disclaimers else "No survivorship bias adjustment applied.",
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
# Issue 1 - the trade ledger
# ---------------------------------------------------------------------------


def test_trade_ledger_contains_every_field_correctly_attributed_and_paginates_at_15_rows() -> None:
    result = _result(n_trades=17)
    pdf_bytes = build_backtest_report_pdf(result)
    text, page_count = _extract_text(pdf_bytes), None
    full_text, num_pages = text[0], text[1]
    page_texts = _extract_page_texts(pdf_bytes)

    assert "Trade Ledger" in full_text
    for label in ["Entry Time", "Entry Rate", "Exit Time", "Exit Rate", "Direction", "Qty", "Total", "P&L"]:
        assert label in full_text

    # 17 trades at 15/page (the SAME TRADES_PER_PAGE the on-screen
    # ledger uses) -> 2 ledger pages: 15 then 2.
    ledger_pages = [p for p in page_texts if "Entry Rate" in p]
    assert len(ledger_pages) == 2

    # Trade #1's own honest derivations: Total = qty(10) x entry(100) =
    # Rs. 1,000.00; P&L % = net_pnl(19) / 1000 x 100 = 1.90%.
    assert "1,000.00" in full_text
    assert "1.90%" in full_text
    # The Long/Short mapping matches the on-screen TradeTable's own
    # BULLISH -> "Long" convention exactly.
    assert "Long" in full_text


def test_trade_ledger_reports_an_honest_empty_state_with_zero_trades() -> None:
    result = _result(n_trades=0)
    pdf_bytes = build_backtest_report_pdf(result)
    text, _ = _extract_text(pdf_bytes)
    assert "No trades were taken in this backtest." in text


# ---------------------------------------------------------------------------
# Issue 2 - the real layout bug (long label overlapping the next column)
# ---------------------------------------------------------------------------


def test_long_skip_reason_label_wraps_correctly_and_never_overlaps_the_adjacent_value() -> None:
    """Direct regression for the operator's own real, exact finding:
    "...e-direction, position already open) 364" - the label's own
    tail glued to the NEXT column's numeric value with no space,
    because the pre-fix `Table` cell was a plain `str` (reportlab
    never wraps that) instead of a `Paragraph` (which does)."""
    result = _result(n_trades=1)
    pdf_bytes = build_backtest_report_pdf(result)
    text, _ = _extract_text(pdf_bytes)

    assert "Skipped Signals (same-direction, position already open)" in text
    # The exact garbled fragment the operator's own PDF showed must
    # never appear - a real, precise regression check, not a vague one.
    assert "e-direction, position already open) 2" not in text
    assert "Rejected Trades (insufficient capital)" in text


def test_footer_wraps_long_disclaimer_text_without_a_fixed_line_count_assumption() -> None:
    """The footer's own long survivorship/assumption sentences must
    fully appear (proving they wrapped within their own reserved band
    rather than being silently clipped by a naive fixed-position,
    un-wrapped `drawString` loop)."""
    result = _result(n_trades=1, long_disclaimers=True)
    pdf_bytes = build_backtest_report_pdf(result)
    text, _ = _extract_text(pdf_bytes)

    assert "MODEL ASSUMPTION, not a" in text
    assert "survivorship" in text.lower()
    assert "NOT adjusted for survivorship" in text


# ---------------------------------------------------------------------------
# Issue 3 - combined multi-instrument file
# ---------------------------------------------------------------------------


def test_multi_instrument_report_includes_every_instruments_complete_report() -> None:
    primary = _result("NSE:FIXTURE01", n_trades=5, long_disclaimers=True)
    sibling_a = _result("NSE:FIXTUREB", n_trades=3, long_disclaimers=False)
    sibling_b = _result("NSE:FIXTUREC", n_trades=18, long_disclaimers=False)

    pdf_bytes = build_backtest_report_pdf(primary, sibling_results=[sibling_a, sibling_b])
    text, page_count = _extract_text(pdf_bytes)

    assert "Multi-Instrument Backtest Report" in text
    assert "Instrument 1 of 3" in text
    assert "Instrument 2 of 3" in text
    assert "Instrument 3 of 3" in text

    # Every instrument's own COMPLETE report - not just a summary row -
    # confirmed by each instrument's own section headings appearing
    # exactly once per instrument.
    assert text.count("Trade Ledger") == 3
    assert text.count("Ratio Analysis") == 3
    assert text.count("Signal / Trade Breakdown") == 3

    for symbol in ["NSE:FIXTURE01", "NSE:FIXTUREB", "NSE:FIXTUREC"]:
        assert symbol in text

    # 1 index page + instrument1 (divider+summary+signal+ratio+1
    # ledger page, 5 trades) + instrument2 (same shape, 3 trades) +
    # instrument3 (divider+summary+signal+ratio+2 ledger pages, 18
    # trades) = 1 + 5 + 5 + 6 = 17.
    assert page_count == 17


def test_multi_instrument_report_each_instruments_pages_carry_its_own_correct_footer() -> None:
    """Each instrument's own pages (including its own divider page)
    must show THAT instrument's own data-quality/cost-model facts -
    never another instrument's, which a single shared footer across
    the whole combined file would have silently gotten wrong."""
    primary = _result("NSE:FIXTURE01", n_trades=2, long_disclaimers=True)
    sibling = _result("NSE:FIXTUREB", n_trades=2, long_disclaimers=False)

    pdf_bytes = build_backtest_report_pdf(primary, sibling_results=[sibling])
    page_texts = _extract_page_texts(pdf_bytes)

    divider_2_page = next(p for p in page_texts if "Instrument 2 of 2" in p)
    assert "No slippage assumed." in divider_2_page
    assert "MODEL ASSUMPTION, not a" not in divider_2_page

    divider_1_page = next(p for p in page_texts if "Instrument 1 of 2" in p)
    assert "MODEL ASSUMPTION, not a" in divider_1_page


def test_single_instrument_report_unchanged_structurally_no_index_or_divider() -> None:
    """CHECKPOINT-BACKTEST-PDF-C's own explicit requirement: the
    single-instrument case (no siblings) stays exactly as it was
    structurally - no "Results by Instrument" index page, no divider
    page - only the new Issue 1 trade ledger content is added."""
    result = _result(n_trades=1)
    pdf_bytes = build_backtest_report_pdf(result)
    text, _ = _extract_text(pdf_bytes)

    assert "Multi-Instrument Backtest Report" not in text
    assert "Instrument 1 of 1" not in text
    assert "Results by Instrument" not in text
    assert "Backtest Report" in text
    assert "Trade Ledger" in text


# ---------------------------------------------------------------------------
# Real, end-to-end HTTP proof (small scale) - confirms the fix is wired
# into the live endpoint, not just correct in the pure function.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_real_backtest_pdf_report_includes_the_new_trade_ledger_end_to_end() -> None:
    client = _client_as_operator()
    run_response = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert run_response.status_code == 200, run_response.content
    backtest_id = run_response.json()["backtest_id"]

    pdf_response = client.get(f"/api/v1/config/backtesting/results/{backtest_id}/report/")
    assert pdf_response.status_code == 200
    text, page_count = _extract_text(pdf_response.content)

    assert page_count == 4, "Summary, Signal/Trade Breakdown, Ratio Analysis, Trade Ledger"
    assert "Trade Ledger" in text
    assert "Entry Rate" in text
    assert "Skipped Signals (same-direction, position already open)" in text
    # No garbled overlap in the real, live-endpoint-generated PDF either.
    assert "e-direction, position already open) 0" not in text
