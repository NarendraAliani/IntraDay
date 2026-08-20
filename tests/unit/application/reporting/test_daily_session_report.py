# tests/unit/application/reporting/test_daily_session_report.py
#
# Checkpoint 64.10: coverage for the Daily Session Report - "what
# happened today?" aggregated from real, pre-existing ledgers.
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from intraday.application.reporting.communication_delivery_report import CommunicationDeliveryRow
from intraday.application.reporting.daily_session_report import (
    PaperOrderSummaryRow,
    SystemHealthSummary,
    build_daily_session_report,
)
from intraday.application.reporting.signal_report import SignalSummaryRow

SESSION_DATE = date(2026, 8, 19)


def test_empty_session_produces_an_honest_all_zero_report() -> None:
    report = build_daily_session_report(
        session_date=SESSION_DATE,
        signal_rows=(),
        paper_order_rows=(),
        communication_rows=(),
        system_health=None,
        realized_pnl_total=None,
        generated_by="tester",
    )

    assert report.total_signals == 0
    assert report.paper_orders_total == 0
    assert report.communication_total == 0
    assert report.system_health is None
    assert report.realized_pnl_total is None
    assert report.strategies == ()


def test_aggregates_a_real_mixed_session() -> None:
    signal_rows = (
        SignalSummaryRow("atr_volatility_breakout", "NSE:RELIANCE", "5m", "BULLISH", "APPROVED"),
        SignalSummaryRow("atr_volatility_breakout", "NSE:TCS", "5m", "BULLISH", "REJECTED"),
    )
    paper_order_rows = (
        PaperOrderSummaryRow(status="FILLED"),
        PaperOrderSummaryRow(status="REJECTED"),
    )
    when = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    communication_rows = (
        CommunicationDeliveryRow("sig-1", "TELEGRAM", "telegram", "VALIDATED_SIGNAL", "SENT", when),
        CommunicationDeliveryRow("sig-1", "DISCORD", "discord", "VALIDATED_SIGNAL", "FAILED", when),
    )
    system_health = SystemHealthSummary(
        watchdog_state="HEALTHY", reconnect_count=2, consecutive_failures=0
    )

    report = build_daily_session_report(
        session_date=SESSION_DATE,
        signal_rows=signal_rows,
        paper_order_rows=paper_order_rows,
        communication_rows=communication_rows,
        system_health=system_health,
        realized_pnl_total=Decimal("1250.50"),
        generated_by="tester",
    )

    assert report.total_signals == 2
    assert report.risk_accepted == 1
    assert report.risk_rejected == 1
    assert report.paper_orders_total == 2
    assert report.paper_orders_filled == 1
    assert report.paper_orders_rejected == 1
    assert report.communication_total == 2
    assert report.communication_sent == 1
    assert report.communication_failed == 1
    assert report.strategies == ("atr_volatility_breakout",)
    assert report.universe == ("NSE:RELIANCE", "NSE:TCS")
    assert report.system_health is not None
    assert report.system_health.reconnect_count == 2
    assert report.realized_pnl_total == Decimal("1250.50")


def test_metadata_period_matches_the_session_date() -> None:
    report = build_daily_session_report(
        session_date=SESSION_DATE,
        signal_rows=(),
        paper_order_rows=(),
        communication_rows=(),
        system_health=None,
        realized_pnl_total=None,
        generated_by="tester",
    )

    assert report.metadata.period_start == SESSION_DATE
    assert report.metadata.period_end == SESSION_DATE
    assert report.metadata.report_type.value == "DAILY_SESSION_REPORT"
