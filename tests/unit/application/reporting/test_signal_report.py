# tests/unit/application/reporting/test_signal_report.py
#
# Checkpoint 64.10: coverage for the new Signal Report aggregation -
# a fresh, real successor to signal_pipeline_report.py's outdated proxy
# now that SignalRecord (Checkpoint 62.x) genuinely exists.
from __future__ import annotations

from intraday.application.reporting.signal_report import SignalSummaryRow, build_signal_report


def test_empty_input_produces_an_honest_all_zero_report() -> None:
    report = build_signal_report(rows=(), generated_by="tester")

    assert report.total_signals == 0
    assert report.buy_count == 0
    assert report.sell_count == 0
    assert report.neutral_count == 0
    assert report.risk_accepted == 0
    assert report.risk_rejected == 0
    assert report.by_strategy == {}


def test_aggregates_direction_and_risk_counts_correctly() -> None:
    rows = (
        SignalSummaryRow("ema_crossover", "NSE:RELIANCE", "5m", "BULLISH", "APPROVED"),
        SignalSummaryRow("ema_crossover", "NSE:TCS", "5m", "BEARISH", "REJECTED"),
        SignalSummaryRow("sma_trend_filter", "NSE:RELIANCE", "15m", "NEUTRAL", "APPROVED"),
    )

    report = build_signal_report(rows=rows, generated_by="tester")

    assert report.total_signals == 3
    assert report.buy_count == 1
    assert report.sell_count == 1
    assert report.neutral_count == 1
    assert report.risk_accepted == 2
    assert report.risk_rejected == 1


def test_groups_by_strategy_stock_and_timeframe() -> None:
    rows = (
        SignalSummaryRow("ema_crossover", "NSE:RELIANCE", "5m", "BULLISH", "APPROVED"),
        SignalSummaryRow("ema_crossover", "NSE:RELIANCE", "5m", "BULLISH", "APPROVED"),
        SignalSummaryRow("sma_trend_filter", "NSE:TCS", "15m", "BEARISH", "REJECTED"),
    )

    report = build_signal_report(rows=rows, generated_by="tester")

    assert report.by_strategy == {"ema_crossover": 2, "sma_trend_filter": 1}
    assert report.by_stock == {"NSE:RELIANCE": 2, "NSE:TCS": 1}
    assert report.by_timeframe == {"5m": 2, "15m": 1}


def test_metadata_reflects_the_real_signal_count() -> None:
    rows = (SignalSummaryRow("ema_crossover", "NSE:RELIANCE", "5m", "BULLISH", "APPROVED"),)

    report = build_signal_report(rows=rows, generated_by="tester")

    assert "1 signal" in report.metadata.data_identity
    assert report.metadata.generated_by == "tester"
    assert report.metadata.report_status.value == "AVAILABLE"
