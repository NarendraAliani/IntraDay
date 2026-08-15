# tests/unit/application/reporting/test_communication_delivery_report.py
#
# Checkpoint 37 Part 8: proves the report aggregates REAL rows honestly
# - including the "zero data" case, which must render as zero, not a
# fabricated example.
from __future__ import annotations

from datetime import UTC, datetime

from intraday.application.reporting.communication_delivery_report import (
    CommunicationDeliveryRow,
    build_communication_delivery_report,
)
from intraday.application.reporting.contracts import ReportStatus, ReportType

NOW = datetime(2026, 1, 5, 5, 0, tzinfo=UTC)


def _row(**overrides: object) -> CommunicationDeliveryRow:
    defaults: dict[str, object] = dict(  # noqa: C408
        signal_id="sig-1",
        channel="TELEGRAM",
        provider="telegram",
        template_id="VALIDATED_SIGNAL",
        delivery_status="SENT",
        created_at=NOW,
    )
    defaults.update(overrides)
    return CommunicationDeliveryRow(**defaults)  # type: ignore[arg-type]


def test_empty_rows_produce_an_honest_zero_report() -> None:
    report = build_communication_delivery_report(rows=(), generated_by="test")
    assert report.total_attempts == 0
    assert report.sent_count == 0
    assert report.distinct_signals_communicated == 0
    assert report.metadata.report_type is ReportType.COMMUNICATION_DELIVERY_REPORT
    assert report.metadata.report_status is ReportStatus.AVAILABLE


def test_aggregates_by_status_channel_and_template() -> None:
    rows = (
        _row(signal_id="sig-1", delivery_status="SENT", channel="TELEGRAM"),
        _row(signal_id="sig-1", delivery_status="SENT", channel="DISCORD"),
        _row(signal_id="sig-2", delivery_status="FAILED", channel="TELEGRAM"),
        _row(
            signal_id="sig-2",
            delivery_status="SKIPPED_DUPLICATE",
            channel="TELEGRAM",
            template_id="ORDER_FILLED",
        ),
    )
    report = build_communication_delivery_report(rows=rows, generated_by="test")

    assert report.total_attempts == 4
    assert report.sent_count == 2
    assert report.failed_count == 1
    assert report.skipped_duplicate_count == 1
    assert report.distinct_signals_communicated == 1  # only sig-1 has a SENT row
    assert report.by_channel == {"TELEGRAM": 3, "DISCORD": 1}
    assert report.by_template == {"VALIDATED_SIGNAL": 3, "ORDER_FILLED": 1}
