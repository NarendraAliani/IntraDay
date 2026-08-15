# File: src/intraday/application/reporting/communication_delivery_report.py
#
# Checkpoint 37 Part 8: "was this signal communicated?" as a REAL
# report, not a placeholder catalogue entry. Deliberately takes the raw
# ledger rows as a plain, application-layer-friendly tuple of dicts
# (never a Django queryset/model - Contract 6, application must not
# depend on infrastructure) so this module stays infrastructure-free;
# `infrastructure/api/reports_views.py` (or an equivalent future view)
# is responsible for querying `CommunicationLedgerRecord` and passing
# the result in.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from intraday.application.reporting.contracts import ReportMetadata, ReportStatus, ReportType


@dataclass(frozen=True, slots=True)
class CommunicationDeliveryRow:
    """One ledger row, already projected to the fields this report
    needs - never the full Django record (keeps this module
    infrastructure-free)."""

    signal_id: str
    channel: str
    provider: str
    template_id: str
    delivery_status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CommunicationDeliveryReport:
    metadata: ReportMetadata
    total_attempts: int
    sent_count: int
    failed_count: int
    skipped_duplicate_count: int
    skipped_not_configured_count: int
    distinct_signals_communicated: int
    by_channel: dict[str, int]
    by_template: dict[str, int]


def build_communication_delivery_report(
    *, rows: tuple[CommunicationDeliveryRow, ...], generated_by: str
) -> CommunicationDeliveryReport:
    """Pure aggregation over REAL rows - an empty `rows` tuple produces
    an honest all-zero report, never a fabricated example. This is the
    one call site that answers Part 7's own question: "was this signal
    communicated?" in aggregate, across every channel and template."""
    sent = sum(1 for r in rows if r.delivery_status == "SENT")
    failed = sum(1 for r in rows if r.delivery_status == "FAILED")
    skipped_duplicate = sum(1 for r in rows if r.delivery_status == "SKIPPED_DUPLICATE")
    skipped_not_configured = sum(1 for r in rows if r.delivery_status == "SKIPPED_NOT_CONFIGURED")

    by_channel: dict[str, int] = {}
    by_template: dict[str, int] = {}
    for row in rows:
        by_channel[row.channel] = by_channel.get(row.channel, 0) + 1
        by_template[row.template_id] = by_template.get(row.template_id, 0) + 1

    generated_at = datetime.now(tz=UTC)
    metadata = ReportMetadata(
        report_id=f"communication-delivery-{generated_at.date().isoformat()}",
        report_type=ReportType.COMMUNICATION_DELIVERY_REPORT,
        title="Communication Delivery Report",
        generated_at=generated_at,
        generated_by=generated_by,
        data_source="CommunicationLedgerRecord (Checkpoint 37 Part 7)",
        data_identity=f"{len(rows)} delivery attempt(s)",
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

    return CommunicationDeliveryReport(
        metadata=metadata,
        total_attempts=len(rows),
        sent_count=sent,
        failed_count=failed,
        skipped_duplicate_count=skipped_duplicate,
        skipped_not_configured_count=skipped_not_configured,
        distinct_signals_communicated=len(
            {r.signal_id for r in rows if r.delivery_status == "SENT"}
        ),
        by_channel=by_channel,
        by_template=by_template,
    )
