# File: src/intraday/application/reporting/signal_pipeline_report.py
#
# Checkpoint 38 Part 16: the report that proves the active loop is
# working - reconciling SIGNALS GENERATED/VALIDATED/COMMUNICATED against
# EXECUTION APPROVED/BLOCKED and ORDERS SUBMITTED/FILLED/REJECTED, all
# from REAL persisted rows (CommunicationLedgerRecord +
# PaperOrderRecord), never fabricated. No Signal persistence table
# exists in this project (a genuine, named gap - see
# ACTIVE_PRODUCT_GAP_REGISTER.md) - "signals generated/validated" is
# derived from VALIDATED_SIGNAL communication events instead, which is
# an honest proxy (every signal that reaches communication was, by
# construction, both generated and validated - see
# `PaperSignalExecutionService`, Checkpoint 36/37) but NOT a claim that
# a dedicated signal ledger exists.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from intraday.application.reporting.contracts import ReportMetadata, ReportStatus, ReportType


@dataclass(frozen=True, slots=True)
class SignalPipelineRow:
    """One communication-ledger row, already projected (never a raw
    Django model - keeps this module infrastructure-free, Contract 6)."""

    signal_id: str
    template_id: str
    delivery_status: str


@dataclass(frozen=True, slots=True)
class OrderOutcomeRow:
    """One paper-order row, already projected - only orders carrying a
    non-blank `signal_id` (Checkpoint 36 Part 6 lineage) are counted as
    strategy-generated for this report; manually-submitted orders are
    deliberately excluded, never conflated with signal-driven ones."""

    signal_id: str
    status: str


@dataclass(frozen=True, slots=True)
class SignalPipelineReport:
    metadata: ReportMetadata
    signals_generated: int
    signals_communicated: int
    execution_blocked: int
    execution_approved: int
    orders_submitted: int
    orders_filled: int
    orders_rejected: int
    orders_partially_filled: int
    orders_pending: int


def build_signal_pipeline_report(
    *,
    communication_rows: tuple[SignalPipelineRow, ...],
    order_rows: tuple[OrderOutcomeRow, ...],
    generated_by: str,
) -> SignalPipelineReport:
    """Pure aggregation - empty inputs produce an honest all-zero
    report. `signals_generated`/`signals_communicated` come from
    DISTINCT `signal_id`s (a signal fires ONE `VALIDATED_SIGNAL` event,
    but may fan out to multiple providers/channels - counting rows
    directly would double-count)."""
    validated_signal_rows = [r for r in communication_rows if r.template_id == "VALIDATED_SIGNAL"]
    signals_generated = len({r.signal_id for r in validated_signal_rows})
    signals_communicated = len(
        {r.signal_id for r in validated_signal_rows if r.delivery_status == "SENT"}
    )

    blocked_rows = [
        r for r in communication_rows if r.template_id == "VALIDATED_SIGNAL_EXECUTION_BLOCKED"
    ]
    execution_blocked = len({r.signal_id for r in blocked_rows})

    signal_driven_orders = [r for r in order_rows if r.signal_id]
    execution_approved = len({r.signal_id for r in signal_driven_orders})
    orders_submitted = len(signal_driven_orders)
    orders_filled = sum(1 for r in signal_driven_orders if r.status == "FILLED")
    orders_rejected = sum(1 for r in signal_driven_orders if r.status == "REJECTED")
    orders_partially_filled = sum(1 for r in signal_driven_orders if r.status == "PARTIALLY_FILLED")
    orders_pending = orders_submitted - orders_filled - orders_rejected - orders_partially_filled

    generated_at = datetime.now(tz=UTC)
    metadata = ReportMetadata(
        report_id=f"signal-pipeline-{generated_at.date().isoformat()}",
        report_type=ReportType.SIGNAL_REPORT,
        title="Signal Pipeline Report",
        generated_at=generated_at,
        generated_by=generated_by,
        data_source="CommunicationLedgerRecord + PaperOrderRecord (Checkpoint 38)",
        data_identity=f"{len(communication_rows)} communication row(s), "
        f"{len(order_rows)} order row(s)",
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

    return SignalPipelineReport(
        metadata=metadata,
        signals_generated=signals_generated,
        signals_communicated=signals_communicated,
        execution_blocked=execution_blocked,
        execution_approved=execution_approved,
        orders_submitted=orders_submitted,
        orders_filled=orders_filled,
        orders_rejected=orders_rejected,
        orders_partially_filled=orders_partially_filled,
        orders_pending=orders_pending,
    )
