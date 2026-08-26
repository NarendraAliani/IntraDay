# File: src/intraday/infrastructure/persistence/research_correlation.py
#
# Checkpoint 64.89: HISTORICAL FEATURE -> SIGNAL -> TRADE -> OUTCOME
# RESEARCH layer.
#
# WHAT THIS IS: a READ-ONLY research projection built entirely on top of
# the traceability infrastructure Checkpoints 64.81-64.83 already built
# (`DjangoCorrelationRepository.build_signal_traces()` /
# `SignalRecord.scan_run_id` / `.strategy_version_identifier` /
# `PaperTradeRecord.signal_id` / `SignalEvidenceRecord`). It creates NO
# table, NO migration, and NO second source of truth for signals, trades,
# outcomes, or feature values - every value handled here is read verbatim
# from the same rows the correlation API already exposes.
#
# WHAT THIS IS NOT:
#   - NOT a new indicator engine. Feature identity is resolved through the
#     EXISTING `field_registry.resolve_feature_name()` (Checkpoint 64.81),
#     never recomputed.
#   - NOT a proprietary-strategy-math implementation. Nothing here
#     computes RSI/ADX/etc; it only reads the `feature_name`/`value` a
#     strategy already chose to record as `SignalEvidenceRecord` evidence.
#   - NOT a strategy-decision engine. Every function below is descriptive
#     (association/expectancy/win-rate over RECORDED outcomes), never
#     causal, and nothing here writes a threshold or a parameter back into
#     any strategy configuration.
#
# LAYERING: this module lives in `infrastructure.persistence`, not
# `application.services`, because it reads through
# `DjangoCorrelationRepository` (an infrastructure/persistence concrete
# type) directly - `.importlinter` contract 6 forbids
# `application.services`/`application.contracts` from importing
# `intraday.infrastructure` at all, so the research projection sits next
# to the repository it wraps, exactly where `correlation_repository.py`
# itself already lives.
#
# STATISTICAL HONESTY RULE (the one this module exists to enforce): a
# metric is computed ONLY when `observation_count >= MIN_SAMPLE_SIZE`.
# Below that, every function returns `SampleStatus.INSUFFICIENT_SAMPLE`
# (or `NO_DATA` for zero observations) and NO mean/median/win-rate/
# expectancy/profit-factor field is populated with a manufactured number.
#
# MIN_SAMPLE_SIZE = 20 is a deliberately simple, documented, defensible
# floor - not a statistical framework. It is not derived from a power
# calculation (that would itself be a fabricated precision this
# checkpoint refuses to manufacture for an evidence-only research pass);
# it is the smallest count below which a mean/win-rate is obviously
# dominated by single-observation noise. No repository statistical
# framework predates this module, so no existing methodology was
# available to reuse (see `taskReport.md`, "Statistical Methodology").
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from intraday.domain.session.calendar import INDIA_STANDARD_TIME
from intraday.infrastructure.persistence.correlation_repository import (
    CorrelationTraceView,
    DjangoCorrelationRepository,
)
from intraday.infrastructure.persistence.models import SignalRecord
from intraday.signal_intelligence.feature_engine.field_registry import (
    resolve_feature_name,
)

MIN_SAMPLE_SIZE = 20


class SampleStatus(str, Enum):
    OK = "OK"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    NO_DATA = "NO_DATA"


def _status_for(n: int) -> SampleStatus:
    if n == 0:
        return SampleStatus.NO_DATA
    if n < MIN_SAMPLE_SIZE:
        return SampleStatus.INSUFFICIENT_SAMPLE
    return SampleStatus.OK


# ---------------------------------------------------------------------------
# Stage 1: traceability coverage
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceabilityCoverage:
    """Answers the FIRST RESEARCH QUESTION the checkpoint directive
    requires before any correlation is attempted: how much of the
    recorded chain is actually traceable, stage by stage.

    Every `*_coverage_pct` is `None` when `total_signals == 0` - a
    genuinely undefined percentage, never reported as `0.0` (which would
    misleadingly imply "zero out of a real population" rather than "no
    population to measure")."""

    total_signals: int
    signals_with_evidence: int
    signals_with_orders: int
    signals_with_trades: int
    signals_with_realized_outcome: int
    """Signals whose linked trade(s) carry a non-null `realized_pnl` -
    i.e. the round trip has actually closed."""
    evidence_coverage_pct: float | None
    order_coverage_pct: float | None
    trade_coverage_pct: float | None
    outcome_coverage_pct: float | None


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(100.0 * numerator / denominator, 2)


def compute_traceability_coverage(
    repository: DjangoCorrelationRepository | None = None,
) -> TraceabilityCoverage:
    """Reads every `SignalRecord` and its trace via the EXISTING bulk
    `build_signal_traces()` (fixed query count regardless of row count -
    see `correlation_repository.py`'s own N+1 protection). No new query
    pattern is introduced."""
    repo = repository or DjangoCorrelationRepository()
    records = list(SignalRecord.objects.all().order_by("signal_timestamp"))
    traces = repo.build_signal_traces(records)

    total = len(traces)
    with_evidence = sum(1 for t in traces if len(t.evidence) > 0)
    with_orders = sum(1 for t in traces if len(t.orders) > 0)
    with_trades = sum(1 for t in traces if len(t.trades) > 0)
    with_outcome = sum(1 for t in traces if t.realized_pnl is not None)

    return TraceabilityCoverage(
        total_signals=total,
        signals_with_evidence=with_evidence,
        signals_with_orders=with_orders,
        signals_with_trades=with_trades,
        signals_with_realized_outcome=with_outcome,
        evidence_coverage_pct=_pct(with_evidence, total),
        order_coverage_pct=_pct(with_orders, total),
        trade_coverage_pct=_pct(with_trades, total),
        outcome_coverage_pct=_pct(with_outcome, total),
    )


# ---------------------------------------------------------------------------
# Research observation: the minimum trustworthy row the directive asks for
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResearchObservation:
    """One row of the research dataset. Every field is either read
    verbatim from a stored, signal_id-traceable record, or `None` - never
    invented. `feature_values` only contains evidence rows that resolved
    to a canonical `field_id` via `field_registry.resolve_feature_name()`;
    unresolved evidence is dropped from analysis (not fabricated into a
    guessed feature) but the signal itself is still represented."""

    signal_id: str
    strategy_id: str
    strategy_version_identifier: str | None
    instrument_id: str
    signal_timestamp: dt.datetime
    direction: str
    feature_values: dict[str, Decimal]
    """`field_id -> value`, from evidence resolved through the canonical
    registry only."""
    realized_pnl: Decimal | None
    """`None` = no linked trade with a closed outcome. Never fabricated
    as `0`."""
    has_trade: bool


def build_research_observations(
    repository: DjangoCorrelationRepository | None = None,
) -> tuple[ResearchObservation, ...]:
    """Builds the research dataset directly from
    `DjangoCorrelationRepository.build_signal_traces()` - the SAME read
    model the correlation API serves. No parallel query path, no second
    source of truth."""
    repo = repository or DjangoCorrelationRepository()
    records = list(SignalRecord.objects.all().order_by("signal_timestamp"))
    traces = repo.build_signal_traces(records)
    return tuple(_observation_from_trace(t) for t in traces)


def _observation_from_trace(trace: CorrelationTraceView) -> ResearchObservation:
    feature_values: dict[str, Decimal] = {}
    for row in trace.evidence:
        name = row.feature_name
        if not name:
            continue
        resolved = resolve_feature_name(name)
        if resolved.field_id is None:
            continue
        try:
            feature_values[resolved.field_id] = Decimal(str(row.value))
        except (ValueError, ArithmeticError):
            # A non-numeric evidence value (e.g. a text label) is
            # honestly excluded from numeric analysis, never coerced.
            continue

    return ResearchObservation(
        signal_id=trace.signal_id,
        strategy_id=trace.strategy_id,
        strategy_version_identifier=trace.strategy_version_identifier,
        instrument_id=trace.instrument_id,
        signal_timestamp=trace.signal_timestamp,
        direction=trace.direction,
        feature_values=feature_values,
        realized_pnl=trace.realized_pnl,
        has_trade=len(trace.trades) > 0,
    )


# ---------------------------------------------------------------------------
# Feature -> outcome analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FeatureOutcomeResult:
    field_id: str
    observation_count: int
    """Signals carrying this feature AND a realized outcome - the only
    population this result is computed over."""
    status: SampleStatus
    mean_outcome: Decimal | None
    median_outcome: Decimal | None
    win_rate: float | None
    loss_rate: float | None
    expectancy: Decimal | None
    """Equal to `mean_outcome` under this simple methodology - kept as a
    separate named field because the directive asks for it explicitly and
    a future methodology may diverge the two."""
    profit_factor: float | None
    """`gross_profit / gross_loss`. `None` when `gross_loss == 0` (would
    be an undefined or infinite ratio, never reported as a number)."""


def _descriptive_stats(pnls: list[Decimal]) -> tuple[Decimal, Decimal, float, float, Decimal, float | None]:
    n = len(pnls)
    ordered = sorted(pnls)
    mean = sum(pnls, Decimal("0")) / n
    mid = n // 2
    median = ordered[mid] if n % 2 == 1 else (ordered[mid - 1] + ordered[mid]) / 2
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = round(100.0 * len(wins) / n, 2)
    loss_rate = round(100.0 * len(losses) / n, 2)
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = -sum(losses, Decimal("0"))
    profit_factor = float(gross_profit / gross_loss) if gross_loss != 0 else None
    return mean, median, win_rate, loss_rate, mean, profit_factor


def feature_outcome_analysis(
    observations: tuple[ResearchObservation, ...],
) -> tuple[FeatureOutcomeResult, ...]:
    """One result per canonical `field_id` that appears in ANY
    observation's evidence. Only observations with BOTH that feature AND
    a realized outcome contribute to the sample - a signal without a
    closed trade cannot support a win-rate/expectancy claim and is
    honestly excluded rather than treated as a loss or a zero."""
    by_field: dict[str, list[Decimal]] = defaultdict(list)
    for obs in observations:
        if obs.realized_pnl is None:
            continue
        for field_id, value in obs.feature_values.items():
            by_field[field_id].append(obs.realized_pnl)

    results: list[FeatureOutcomeResult] = []
    for field_id in sorted(by_field):
        pnls = by_field[field_id]
        n = len(pnls)
        status = _status_for(n)
        if status is SampleStatus.OK:
            mean, median, win_rate, loss_rate, expectancy, pf = _descriptive_stats(pnls)
        else:
            mean = median = expectancy = None
            win_rate = loss_rate = pf = None
        results.append(
            FeatureOutcomeResult(
                field_id=field_id,
                observation_count=n,
                status=status,
                mean_outcome=mean,
                median_outcome=median,
                win_rate=win_rate,
                loss_rate=loss_rate,
                expectancy=expectancy,
                profit_factor=pf,
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# Feature interaction (pairs)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FeatureInteractionResult:
    field_id_a: str
    field_id_b: str
    observation_count: int
    status: SampleStatus
    mean_outcome: Decimal | None


def feature_interaction_analysis(
    observations: tuple[ResearchObservation, ...],
) -> tuple[FeatureInteractionResult, ...]:
    """Co-occurrence only - a signal's evidence carries BOTH features AND
    a realized outcome. No weight is assigned, no feature is dropped.
    This is observation, never a feature-selection decision."""
    by_pair: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    for obs in observations:
        if obs.realized_pnl is None:
            continue
        fields = sorted(obs.feature_values)
        for i in range(len(fields)):
            for j in range(i + 1, len(fields)):
                by_pair[(fields[i], fields[j])].append(obs.realized_pnl)

    results: list[FeatureInteractionResult] = []
    for (a, b) in sorted(by_pair):
        pnls = by_pair[(a, b)]
        n = len(pnls)
        status = _status_for(n)
        mean = sum(pnls, Decimal("0")) / n if status is SampleStatus.OK else None
        results.append(FeatureInteractionResult(a, b, n, status, mean))
    return tuple(results)


# ---------------------------------------------------------------------------
# Symbol robustness
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SymbolOutcomeResult:
    instrument_id: str
    observation_count: int
    status: SampleStatus
    mean_outcome: Decimal | None
    win_rate: float | None


def symbol_robustness_analysis(
    observations: tuple[ResearchObservation, ...],
) -> tuple[SymbolOutcomeResult, ...]:
    by_symbol: dict[str, list[Decimal]] = defaultdict(list)
    for obs in observations:
        if obs.realized_pnl is not None:
            by_symbol[obs.instrument_id].append(obs.realized_pnl)

    results = []
    for symbol in sorted(by_symbol):
        pnls = by_symbol[symbol]
        n = len(pnls)
        status = _status_for(n)
        if status is SampleStatus.OK:
            mean = sum(pnls, Decimal("0")) / n
            win_rate = round(100.0 * len([p for p in pnls if p > 0]) / n, 2)
        else:
            mean = None
            win_rate = None
        results.append(SymbolOutcomeResult(symbol, n, status, mean, win_rate))
    return tuple(results)


# ---------------------------------------------------------------------------
# Time-of-day (observation only - no window optimisation)
# ---------------------------------------------------------------------------


class TimeOfDayBucket(str, Enum):
    OPENING = "OPENING"  # 09:15-10:00 IST
    MID_SESSION = "MID_SESSION"  # 10:00-14:30 IST
    CLOSING = "CLOSING"  # 14:30-15:30 IST
    OUTSIDE_SESSION = "OUTSIDE_SESSION"


def _bucket_for(timestamp: dt.datetime) -> TimeOfDayBucket:
    """`signal_timestamp` is stored timezone-aware (see `SignalRecord`),
    but not necessarily in IST - it must be converted, never read as a
    naive wall-clock time, or a UTC-stored timestamp would be bucketed
    against IST session boundaries by coincidence rather than by fact."""
    t = timestamp.astimezone(INDIA_STANDARD_TIME).time()
    if dt.time(9, 15) <= t < dt.time(10, 0):
        return TimeOfDayBucket.OPENING
    if dt.time(10, 0) <= t < dt.time(14, 30):
        return TimeOfDayBucket.MID_SESSION
    if dt.time(14, 30) <= t < dt.time(15, 30):
        return TimeOfDayBucket.CLOSING
    return TimeOfDayBucket.OUTSIDE_SESSION


@dataclass(frozen=True, slots=True)
class TimeOfDayResult:
    bucket: TimeOfDayBucket
    observation_count: int
    status: SampleStatus
    mean_outcome: Decimal | None
    win_rate: float | None


def time_of_day_analysis(
    observations: tuple[ResearchObservation, ...],
) -> tuple[TimeOfDayResult, ...]:
    """Buckets use the signal's OWN stored `signal_timestamp` (assumed
    IST, matching the rest of the platform's session-time conventions -
    see `domain.session.calendar`). Purely observational: no window is
    selected, tuned, or promoted here."""
    by_bucket: dict[TimeOfDayBucket, list[Decimal]] = defaultdict(list)
    for obs in observations:
        if obs.realized_pnl is not None:
            by_bucket[_bucket_for(obs.signal_timestamp)].append(obs.realized_pnl)

    results = []
    for bucket in TimeOfDayBucket:
        pnls = by_bucket.get(bucket, [])
        n = len(pnls)
        status = _status_for(n)
        if status is SampleStatus.OK:
            mean = sum(pnls, Decimal("0")) / n
            win_rate = round(100.0 * len([p for p in pnls if p > 0]) / n, 2)
        else:
            mean = None
            win_rate = None
        results.append(TimeOfDayResult(bucket, n, status, mean, win_rate))
    return tuple(results)


__all__ = [
    "MIN_SAMPLE_SIZE",
    "SampleStatus",
    "TraceabilityCoverage",
    "compute_traceability_coverage",
    "ResearchObservation",
    "build_research_observations",
    "FeatureOutcomeResult",
    "feature_outcome_analysis",
    "FeatureInteractionResult",
    "feature_interaction_analysis",
    "SymbolOutcomeResult",
    "symbol_robustness_analysis",
    "TimeOfDayBucket",
    "TimeOfDayResult",
    "time_of_day_analysis",
]
