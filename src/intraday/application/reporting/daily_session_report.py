# File: src/intraday/application/reporting/daily_session_report.py
#
# Checkpoint 64.10: the Daily Session Report - "what happened today?"
# without inspecting multiple screens, built by aggregating REAL rows
# from the pre-existing signal/communication/paper/worker-status
# ledgers - never a second, competing "session" persistence table. A
# "session" here is identified by a calendar date range over
# `signal_timestamp`/`created_at` (documented, disclosed limitation -
# see this report's own `ReportCatalogueEntry` in `contracts.py`: no
# dedicated Session row exists, so a genuine multi-session-per-day
# scenario is not yet distinguishable). This module stays
# infrastructure-free (Contract 6) - every input is a plain, already-
# projected row tuple; `infrastructure/api/reports_views.py` performs
# the real queries and passes the results in.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from intraday.application.reporting.communication_delivery_report import (
    CommunicationDeliveryRow,
)
from intraday.application.reporting.contracts import ReportMetadata, ReportStatus, ReportType
from intraday.application.reporting.signal_report import SignalSummaryRow


@dataclass(frozen=True, slots=True)
class PaperOrderSummaryRow:
    """One `PaperOrderRecord`, already projected."""

    status: str


@dataclass(frozen=True, slots=True)
class ChannelCommunicationSummary:
    """Checkpoint 64.16 §8: per-channel counts, derived from the SAME
    `communication_rows` this report already receives - never a second
    communication-accounting path. `pending` is every row for this
    channel that is neither a terminal SENT nor a terminal FAILED
    outcome (SKIPPED_DUPLICATE/SKIPPED_NOT_CONFIGURED/RETRYING/PENDING,
    whichever real `delivery_status` values exist) - computed as
    `total - sent - failed` so it can never drift from the channel's
    own row count even if a new non-terminal status is added later."""

    sent: int
    failed: int
    pending: int


@dataclass(frozen=True, slots=True)
class SystemHealthSummary:
    """A snapshot of `WorkerRuntimeStatus` at report time - `None` when
    the worker has never run this session (honestly absent, not a
    fabricated zero-everything row)."""

    watchdog_state: str
    reconnect_count: int
    consecutive_failures: int


@dataclass(frozen=True, slots=True)
class DailySessionReport:
    metadata: ReportMetadata
    session_date: date
    strategies: tuple[str, ...]
    universe: tuple[str, ...]
    timeframes: tuple[str, ...]
    total_signals: int
    risk_accepted: int
    risk_rejected: int
    paper_orders_total: int
    paper_orders_filled: int
    paper_orders_rejected: int
    communication_total: int
    communication_sent: int
    communication_failed: int
    communication_skipped: int
    telegram: ChannelCommunicationSummary
    discord: ChannelCommunicationSummary
    system_health: SystemHealthSummary | None
    realized_pnl_total: Decimal | None
    """`None` when no real position data was supplied by the caller -
    never fabricated as `Decimal("0")`, which would be indistinguishable
    from "genuinely broke even.\""""


def build_daily_session_report(
    *,
    session_date: date,
    signal_rows: tuple[SignalSummaryRow, ...],
    paper_order_rows: tuple[PaperOrderSummaryRow, ...],
    communication_rows: tuple[CommunicationDeliveryRow, ...],
    system_health: SystemHealthSummary | None,
    realized_pnl_total: Decimal | None,
    generated_by: str,
) -> DailySessionReport:
    """Pure aggregation over REAL, persisted rows for one calendar
    session - an empty input set produces an honest all-zero report
    (a real, legitimate outcome: no scanner activity that day), never a
    fabricated example."""
    strategies = tuple(sorted({r.strategy_id for r in signal_rows}))
    universe = tuple(sorted({r.instrument_id for r in signal_rows}))
    timeframes = tuple(sorted({r.timeframe for r in signal_rows}))

    risk_accepted = sum(1 for r in signal_rows if r.risk_status == "APPROVED")
    risk_rejected = sum(1 for r in signal_rows if r.risk_status == "REJECTED")

    orders_filled = sum(1 for r in paper_order_rows if r.status == "FILLED")
    orders_rejected = sum(1 for r in paper_order_rows if r.status == "REJECTED")

    comm_sent = sum(1 for r in communication_rows if r.delivery_status == "SENT")
    comm_failed = sum(1 for r in communication_rows if r.delivery_status == "FAILED")
    comm_skipped = sum(
        1
        for r in communication_rows
        if r.delivery_status in ("SKIPPED_DUPLICATE", "SKIPPED_NOT_CONFIGURED")
    )

    def _channel_summary(channel: str) -> ChannelCommunicationSummary:
        rows = [r for r in communication_rows if r.channel == channel]
        sent = sum(1 for r in rows if r.delivery_status == "SENT")
        failed = sum(1 for r in rows if r.delivery_status == "FAILED")
        return ChannelCommunicationSummary(
            sent=sent, failed=failed, pending=len(rows) - sent - failed
        )

    telegram_summary = _channel_summary("TELEGRAM")
    discord_summary = _channel_summary("DISCORD")

    generated_at = datetime.now(tz=UTC)
    metadata = ReportMetadata(
        report_id=f"daily-session-{session_date.isoformat()}",
        report_type=ReportType.DAILY_SESSION_REPORT,
        title=f"Daily Session Report - {session_date.isoformat()}",
        generated_at=generated_at,
        generated_by=generated_by,
        data_source=(
            "SignalRecord + PaperOrderRecord + CommunicationLedgerRecord + "
            "WorkerRuntimeStatus (all pre-existing ledgers)"
        ),
        data_identity=(
            f"{len(signal_rows)} signal(s), {len(paper_order_rows)} paper order(s), "
            f"{len(communication_rows)} communication attempt(s)"
        ),
        strategy_identity=None,
        timeframe=None,
        instrument_universe=(),
        trust_level=None,
        quality_status=None,
        report_status=ReportStatus.AVAILABLE,
        version="v1",
        period_start=session_date,
        period_end=session_date,
    )

    return DailySessionReport(
        metadata=metadata,
        session_date=session_date,
        strategies=strategies,
        universe=universe,
        timeframes=timeframes,
        total_signals=len(signal_rows),
        risk_accepted=risk_accepted,
        risk_rejected=risk_rejected,
        paper_orders_total=len(paper_order_rows),
        paper_orders_filled=orders_filled,
        paper_orders_rejected=orders_rejected,
        communication_total=len(communication_rows),
        communication_sent=comm_sent,
        communication_failed=comm_failed,
        communication_skipped=comm_skipped,
        telegram=telegram_summary,
        discord=discord_summary,
        system_health=system_health,
        realized_pnl_total=realized_pnl_total,
    )


__all__ = [
    "ChannelCommunicationSummary",
    "DailySessionReport",
    "PaperOrderSummaryRow",
    "SystemHealthSummary",
    "build_daily_session_report",
]
