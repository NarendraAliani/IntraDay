# src/intraday/application/reporting/market_data_quality_report.py
#
# Checkpoint 32 Part 10: structures Checkpoint 31's TRADING_GRADE_BAR
# findings (docs/research/TRADING_GRADE_BAR_VALIDATION.md) as queryable
# data instead of only prose - the six-condition classification, which
# conditions passed/failed/blocked, and the evidence behind each.
#
# This module does NOT re-verify anything against a live Dhan call -
# it structures the ALREADY-established Checkpoint 31 findings. A
# future checkpoint that re-runs live verification should update the
# `CONDITIONS` tuple below to reflect new evidence, never silently
# flip a condition's status without a corresponding new verification.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from intraday.application.reporting.contracts import ReportMetadata, ReportStatus, ReportType
from intraday.domain.market_data.aggregation import BarQualityGrade
from intraday.research.backtesting.contracts import DataQualityLabel


class ConditionStatus(str, Enum):
    """Per-condition status for the TRADING_GRADE_BAR six-condition
    checklist - distinct from `ReportStatus` (which describes the
    REPORT, not one line item within it)."""

    SATISFIED = "SATISFIED"
    PARTIALLY_SATISFIED = "PARTIALLY_SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class TradingGradeBarCondition:
    """One line item of the six-condition `TRADING_GRADE_BAR`
    acceptance definition (`docs/architecture/
    DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md`'s "Trading-Grade Bar -
    Proposed Acceptance Definition")."""

    ordinal: int
    description: str
    status: ConditionStatus
    evidence: str


# Checkpoint 31's real, evidence-based findings - not fabricated for
# this checkpoint. See docs/research/TRADING_GRADE_BAR_VALIDATION.md §4.
CONDITIONS: tuple[TradingGradeBarCondition, ...] = (
    TradingGradeBarCondition(
        ordinal=1,
        description="Same-day intraday availability verified",
        status=ConditionStatus.SATISFIED,
        evidence="Live POST /v2/charts/intraday call (HDFCBANK, 2026-08-14) "
        "returned 360 real same-day 1-minute candles.",
    ),
    TradingGradeBarCondition(
        ordinal=2,
        description="Exact timestamp/timezone verified",
        status=ConditionStatus.SATISFIED,
        evidence="First candle epoch 1786679100.0, interpreted as UTC, equals "
        "exactly 09:15:00 IST - this project's own market-open convention.",
    ),
    TradingGradeBarCondition(
        ordinal=3,
        description="Candle authority/provenance sufficiently trusted",
        status=ConditionStatus.NOT_SATISFIED,
        evidence="Only one independent (Google Finance) cross-check point "
        "performed; Dhan's documentation does not confirm exchange-"
        "authoritative vs. self-computed candles.",
    ),
    TradingGradeBarCondition(
        ordinal=4,
        description="WebSocket live ingestion implemented and validated",
        status=ConditionStatus.BLOCKED,
        evidence="No persistent-process infrastructure exists outside Docker "
        "(Docker permanently deferred). See docs/architecture/"
        "RUNTIME_ARCHITECTURE_DECISION.md (Checkpoint 32) for the design "
        "decision, not yet implemented.",
    ),
    TradingGradeBarCondition(
        ordinal=5,
        description="Historical/reconciliation gap recovery implemented and validated",
        status=ConditionStatus.BLOCKED,
        evidence="Contingent on condition 4 (no live tick stream exists to "
        "reconcile against yet).",
    ),
    TradingGradeBarCondition(
        ordinal=6,
        description="One full trading session independently validated against a "
        "trusted price source",
        status=ConditionStatus.NOT_SATISFIED,
        evidence="Only a single-instrument, single-timestamp comparison "
        "performed, not a full session.",
    ),
)


@dataclass(frozen=True, slots=True)
class MarketDataQualityReport:
    """The report content proper - `ReportMetadata` (shared envelope) +
    the six-condition breakdown + the current, unpromoted classification."""

    metadata: ReportMetadata
    current_classification: BarQualityGrade
    conditions: tuple[TradingGradeBarCondition, ...]
    conditions_passed: int
    conditions_failed: int
    conditions_blocked: int
    last_verified_at: datetime


def build_market_data_quality_report(*, generated_by: str) -> MarketDataQualityReport:
    """Never promotes `current_classification` beyond `SAMPLE_BAR` just
    because some conditions are satisfied - the classification only
    changes when ALL six conditions are `SATISFIED`, mirroring
    `BacktestTrustLevel`'s own "never auto-promote" discipline exactly
    (Part 17's explicit test requirement)."""
    passed = sum(1 for c in CONDITIONS if c.status is ConditionStatus.SATISFIED)
    blocked = sum(1 for c in CONDITIONS if c.status is ConditionStatus.BLOCKED)
    failed = len(CONDITIONS) - passed - blocked

    classification = (
        BarQualityGrade.TRADING_GRADE_BAR
        if passed == len(CONDITIONS)
        else BarQualityGrade.SAMPLE_BAR
    )

    generated_at = datetime.now(tz=UTC)
    metadata = ReportMetadata(
        report_id="market-data-quality-checkpoint-31",
        report_type=ReportType.MARKET_DATA_QUALITY_REPORT,
        title="Market Data Quality Report - TRADING_GRADE_BAR Status",
        generated_at=generated_at,
        generated_by=generated_by,
        data_source="dhan_charts_intraday_verification (Checkpoint 31)",
        data_identity="NSE:HDFCBANK:1m:2026-08-14 (verification sample)",
        strategy_identity=None,
        timeframe=None,
        instrument_universe=(),
        trust_level=None,
        quality_status=DataQualityLabel.SAMPLE_BAR,
        report_status=ReportStatus.AVAILABLE,
        version="1",
        period_start=None,
        period_end=None,
    )

    return MarketDataQualityReport(
        metadata=metadata,
        current_classification=classification,
        conditions=CONDITIONS,
        conditions_passed=passed,
        conditions_failed=failed,
        conditions_blocked=blocked,
        last_verified_at=generated_at,
    )
