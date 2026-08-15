# tests/unit/application/reporting/test_signal_pipeline_report.py
#
# Checkpoint 38 Part 16: proves the funnel reconciles honestly against
# real rows - the exact worked example the checkpoint itself gave
# (signals generated/validated/communicated vs execution approved/
# blocked vs orders submitted/filled/rejected).
from __future__ import annotations

from intraday.application.reporting.contracts import ReportStatus, ReportType
from intraday.application.reporting.signal_pipeline_report import (
    OrderOutcomeRow,
    SignalPipelineRow,
    build_signal_pipeline_report,
)


def test_empty_inputs_produce_an_honest_zero_report() -> None:
    report = build_signal_pipeline_report(communication_rows=(), order_rows=(), generated_by="test")
    assert report.signals_generated == 0
    assert report.orders_submitted == 0
    assert report.metadata.report_type is ReportType.SIGNAL_REPORT
    assert report.metadata.report_status is ReportStatus.AVAILABLE


def test_funnel_reconciles_generated_validated_communicated_and_execution() -> None:
    communication_rows = (
        # 3 distinct signals fired VALIDATED_SIGNAL, all SENT.
        SignalPipelineRow("sig-1", "VALIDATED_SIGNAL", "SENT"),
        SignalPipelineRow("sig-2", "VALIDATED_SIGNAL", "SENT"),
        SignalPipelineRow("sig-3", "VALIDATED_SIGNAL", "SENT"),
        # sig-1 fanned out to a 2nd provider - must not double-count.
        SignalPipelineRow("sig-1", "VALIDATED_SIGNAL", "SENT"),
        # sig-2 was blocked at execution.
        SignalPipelineRow("sig-2", "VALIDATED_SIGNAL_EXECUTION_BLOCKED", "SENT"),
    )
    order_rows = (
        # sig-1 and sig-3 reached the broker; sig-2 never did (blocked).
        OrderOutcomeRow("sig-1", "FILLED"),
        OrderOutcomeRow("sig-3", "REJECTED"),
        # a manually-submitted order (blank signal_id) must be excluded.
        OrderOutcomeRow("", "FILLED"),
    )

    report = build_signal_pipeline_report(
        communication_rows=communication_rows, order_rows=order_rows, generated_by="test"
    )

    assert report.signals_generated == 3  # sig-1, sig-2, sig-3 - deduplicated
    assert report.signals_communicated == 3
    assert report.execution_blocked == 1  # sig-2
    assert report.execution_approved == 2  # sig-1, sig-3 reached the broker
    assert report.orders_submitted == 2  # manual order excluded
    assert report.orders_filled == 1
    assert report.orders_rejected == 1
    assert report.orders_pending == 0


def test_manually_submitted_orders_are_never_counted_as_signal_driven() -> None:
    order_rows = (OrderOutcomeRow("", "FILLED"), OrderOutcomeRow("", "PARTIALLY_FILLED"))
    report = build_signal_pipeline_report(
        communication_rows=(), order_rows=order_rows, generated_by="test"
    )
    assert report.orders_submitted == 0
    assert report.execution_approved == 0
