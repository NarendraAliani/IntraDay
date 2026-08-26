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
from intraday.domain.market_data.quality import CasWindowStatus
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


# ---------------------------------------------------------------------
# Checkpoint 64.88: the CAS-AWARE per-timestamp data-quality vocabulary
# this report can now express, alongside (never replacing) the
# TRADING_GRADE_BAR six-condition checklist above. Named EXACTLY as the
# checkpoint directive requires: `TRUE_MISSING_DATA`,
# `EXPECTED_CAS_NON_CONTINUOUS`, `PROVIDER_DATA_PRESENT`,
# `PROVIDER_BEHAVIOR_UNKNOWN`. Deliberately a small, closed vocabulary
# rather than a sprawling new taxonomy - each value answers exactly one
# question ("was a continuous-trading bar timestamp genuinely absent,
# expected-CAS-absent, present, or genuinely unresolved") and composes
# with `quality.CasWindowStatus` rather than re-deriving session state.
class CasDataQualityLabel(str, Enum):
    """One expected-continuous-trading-timestamp's data-quality verdict,
    CAS-aware. See `classify_cas_data_quality` for how a caller derives
    this - never assigned by hand."""

    TRUE_MISSING_DATA = "TRUE_MISSING_DATA"
    """The timestamp fell inside ordinary CONTINUOUS TRADING (or a
    CATEGORY_II_NON_CAS session, which has no CAS at all) and no bar
    was observed for it. A genuine gap - the ONLY value this checklist
    ever reports as an actionable data-quality defect."""

    EXPECTED_CAS_NON_CONTINUOUS = "EXPECTED_CAS_NON_CONTINUOUS"
    """The timestamp/window falls inside `MarketSessionState.CAS`.
    Absence of an ordinary continuous-trading bar here is EXPECTED, per
    the checkpoint's critical principle - never reported as missing
    data."""

    PROVIDER_DATA_PRESENT = "PROVIDER_DATA_PRESENT"
    """A continuous-trading bar (or, for a CAS-window observation,
    SOME provider observation) was actually present for the
    timestamp/window in question - nothing to flag."""

    PROVIDER_BEHAVIOR_UNKNOWN = "PROVIDER_BEHAVIOR_UNKNOWN"
    """The window is CAS-adjacent (`CasWindowStatus.
    PROVIDER_BEHAVIOR_UNKNOWN` - i.e. `POST_CAS_TRANSITION`) and this
    report deliberately does NOT claim to know whether CAS-window data
    was complete, partial, or absent - no verified Dhan CAS-behavior
    contract exists yet. Distinct from `TRUE_MISSING_DATA`: this value
    is honest uncertainty, not a claimed defect."""


def classify_cas_data_quality(
    *, cas_window_status: CasWindowStatus, is_missing_continuous_bar: bool
) -> CasDataQualityLabel:
    """Derives the `CasDataQualityLabel` for one expected continuous-
    trading bar timestamp. `cas_window_status` comes from
    `quality.classify_cas_window_status`; `is_missing_continuous_bar`
    comes from `quality.missing_continuous_bar_timestamps`
    (`timestamp not in missing_continuous_bar_timestamps(...)` for
    `PROVIDER_DATA_PRESENT`). Pure lookup, no I/O."""
    if cas_window_status is CasWindowStatus.EXPECTED_NON_CONTINUOUS:
        return CasDataQualityLabel.EXPECTED_CAS_NON_CONTINUOUS
    if cas_window_status is CasWindowStatus.PROVIDER_BEHAVIOR_UNKNOWN:
        return CasDataQualityLabel.PROVIDER_BEHAVIOR_UNKNOWN
    return (
        CasDataQualityLabel.TRUE_MISSING_DATA
        if is_missing_continuous_bar
        else CasDataQualityLabel.PROVIDER_DATA_PRESENT
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
