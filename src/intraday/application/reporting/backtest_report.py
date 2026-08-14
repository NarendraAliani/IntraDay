# src/intraday/application/reporting/backtest_report.py
#
# Checkpoint 32 Part 9: maps an existing `BacktestResult` into the
# shared `ReportMetadata` contract - no new data is computed here, this
# is pure presentation-layer assembly over data `research.backtesting`
# already produced (Part 14's "do not create empty business-logic
# classes" - this module has exactly one real job: the mapping).
#
# Part 9's explicit requirement, enforced structurally here: a backtest
# report's `trust_level` is copied VERBATIM from `BacktestResult.trust_level`
# (always POC today) - this function has no code path that could ever
# raise it. Mathematical engine validation (Checkpoint 30), research
# quality, data quality (`quality_status`), profitability (the result's
# own P&L figures, not read by this module at all), and production
# readiness (`trust_level`) remain four separate concerns, never merged
# into one "passed" indicator - this mapper only ever copies existing
# fields, it does not compute a new composite verdict.
from __future__ import annotations

from intraday.application.reporting.contracts import ReportMetadata, ReportStatus, ReportType
from intraday.research.backtesting.contracts import BacktestResult


def build_backtest_report_metadata(result: BacktestResult, *, generated_by: str) -> ReportMetadata:
    """Builds the shared `ReportMetadata` envelope for one backtest
    report. Every field is copied from `result` - nothing here infers,
    upgrades, or overrides anything `research.backtesting` already
    decided (trust level, data quality, cost-model identity)."""
    config = result.configuration
    return ReportMetadata(
        report_id=result.backtest_id,
        report_type=ReportType.BACKTEST_REPORT,
        title=f"Backtest Report - {config.strategy_id} on {config.instrument_id}",
        generated_at=result.generated_at,
        generated_by=generated_by,
        data_source=result.data_quality.data_source,
        data_identity=(
            f"{config.instrument_id}:{config.timeframe.value}:"
            f"{config.start.isoformat()}..{config.end.isoformat()}"
        ),
        strategy_identity=(
            f"{config.strategy_id}:{config.specification_version}:"
            f"{config.code_version}:{config.configuration_version}"
        ),
        timeframe=config.timeframe,
        instrument_universe=(config.instrument_id,),
        trust_level=result.trust_level,
        quality_status=result.data_quality.data_quality,
        report_status=ReportStatus.AVAILABLE,
        version="1",
        period_start=config.start.date(),
        period_end=config.end.date(),
    )
