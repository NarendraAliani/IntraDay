# File: src/intraday/application/reporting/signal_report.py
#
# Checkpoint 64.10: the REAL Signal Report - Report 1 of the mandated
# five. Deliberately built as a NEW, small aggregation over
# `SignalRecord` rows (via `SignalSummaryRow`, a plain projected tuple
# - never a raw Django model, keeping this module infrastructure-free
# per Contract 6) rather than reusing `signal_pipeline_report.py`
# verbatim: that module's own docstring documents it as a proxy built
# BEFORE a real Signal persistence table existed ("no dedicated Signal
# persistence table exists yet... 'signals generated/validated' is
# honestly derived from VALIDATED_SIGNAL communication events") - a
# limitation Checkpoint 62.x's `SignalRecord` (and Checkpoint 64.9's
# Signal Operations Center enrichment) has since closed. This module
# is the report that limitation's own "future_data_dependencies" note
# asked for, now that the real ledger exists - not a duplicate engine,
# but the natural successor once the underlying gap was closed.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from intraday.application.reporting.contracts import ReportMetadata, ReportStatus, ReportType


@dataclass(frozen=True, slots=True)
class SignalSummaryRow:
    """One `SignalRecord`, already projected to the fields this report
    needs - never the full Django model."""

    strategy_id: str
    instrument_id: str
    timeframe: str
    direction: str
    risk_status: str


@dataclass(frozen=True, slots=True)
class SignalReport:
    metadata: ReportMetadata
    total_signals: int
    buy_count: int
    sell_count: int
    neutral_count: int
    risk_accepted: int
    risk_rejected: int
    by_strategy: dict[str, int] = field(default_factory=dict)
    by_stock: dict[str, int] = field(default_factory=dict)
    by_timeframe: dict[str, int] = field(default_factory=dict)


def build_signal_report(*, rows: tuple[SignalSummaryRow, ...], generated_by: str) -> SignalReport:
    """Pure aggregation over REAL, persisted signal rows - an empty
    `rows` tuple produces an honest all-zero report, never a fabricated
    example. `direction` is the strategy's own `StrategyDirection`
    value (`"BULLISH"`/`"BEARISH"`/`"NEUTRAL"`) - mapped to BUY/SELL/
    NEUTRAL for the report's vocabulary, matching the brief's own
    request, never a new direction concept."""
    buy = sum(1 for r in rows if r.direction == "BULLISH")
    sell = sum(1 for r in rows if r.direction == "BEARISH")
    neutral = sum(1 for r in rows if r.direction not in ("BULLISH", "BEARISH"))
    accepted = sum(1 for r in rows if r.risk_status == "APPROVED")
    rejected = sum(1 for r in rows if r.risk_status == "REJECTED")

    by_strategy: dict[str, int] = {}
    by_stock: dict[str, int] = {}
    by_timeframe: dict[str, int] = {}
    for row in rows:
        by_strategy[row.strategy_id] = by_strategy.get(row.strategy_id, 0) + 1
        by_stock[row.instrument_id] = by_stock.get(row.instrument_id, 0) + 1
        by_timeframe[row.timeframe] = by_timeframe.get(row.timeframe, 0) + 1

    generated_at = datetime.now(tz=UTC)
    metadata = ReportMetadata(
        report_id=f"signal-report-{generated_at.date().isoformat()}",
        report_type=ReportType.SIGNAL_REPORT,
        title="Signal Report",
        generated_at=generated_at,
        generated_by=generated_by,
        data_source="SignalRecord (Checkpoint 62.x, enriched Checkpoint 64.9)",
        data_identity=f"{len(rows)} signal(s)",
        strategy_identity=None,
        timeframe=None,
        instrument_universe=(),
        trust_level=None,
        quality_status=None,
        report_status=ReportStatus.AVAILABLE,
        version="v1",
        period_start=None,
        period_end=None,
    )

    return SignalReport(
        metadata=metadata,
        total_signals=len(rows),
        buy_count=buy,
        sell_count=sell,
        neutral_count=neutral,
        risk_accepted=accepted,
        risk_rejected=rejected,
        by_strategy=by_strategy,
        by_stock=by_stock,
        by_timeframe=by_timeframe,
    )


__all__ = ["SignalReport", "SignalSummaryRow", "build_signal_report"]
