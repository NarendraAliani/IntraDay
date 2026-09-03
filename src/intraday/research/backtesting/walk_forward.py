# File: src/intraday/research/backtesting/walk_forward.py
#
# Checkpoint 68.2: walk-forward / out-of-sample splitting and
# aggregation logic, built exactly to the scope approved in
# CHECKPOINT_68.1_SUMMARY.md §C/§D - a pure, callable orchestration
# layer around the EXISTING, UNMODIFIED `engine.run_backtest()`. This
# module contains NO simulation logic of its own: it only computes date
# boundaries from real bar timestamps and calls `run_backtest()` once
# per (in-sample, out-of-sample) slice per fold, then aggregates the
# returned `BacktestResult` objects. `engine.py` is imported but never
# edited - see CHECKPOINT_68.2_SUMMARY.md §C for the `git diff` proof.
#
# NO API ENDPOINT, NO DJANGO MODEL, NO PERSISTENCE in this checkpoint -
# a script/test-callable function only, per 68.1 §B5/§C's own explicit
# scoping. NO real HistoricalBar data is touched here - callers supply
# `bars` directly (synthetic fixtures in this checkpoint's own tests;
# real bars only once the canonicalization migration produces
# research-eligible rows, per 68.1 §D).
#
# SCALE NOTE (deviation from 68.1 §C's literal wording, documented in
# CHECKPOINT_68.2_SUMMARY.md): 68.1 describes fold windows in "days".
# This project is intraday-only (`Timeframe` has no unit longer than
# `DAY` - shared_kernel/contracts.py) and bars are as fine as 1-minute,
# so "day" here means a DISTINCT CALENDAR DATE observed among the bar
# timestamps (`bar.timestamp.date()`, UTC - matching `Bar.timestamp`'s
# own UTC-close-time convention), never a fixed bar-count or a
# hardcoded trading-calendar assumption. This is the literal
# implementation of 68.1 §B5's own instruction: "computes fold
# boundaries from the actual bar timestamps (not a hardcoded calendar
# assumption)."
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.research.backtesting import Strategy, StrategyConfigurationValues
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    BacktestResult,
    DataQualityDisclosure,
)
from intraday.research.backtesting.cost_model import CostModel
from intraday.research.backtesting.engine import FeatureSeriesComputer, run_backtest
from intraday.research.backtesting.errors import InsufficientHistoricalDataError


class InsufficientDataForWalkForwardError(ValueError):
    """Raised when the supplied bars cannot support even one walk-
    forward fold of the requested `min_oos_days`/`min_folds` shape.
    Mirrors `engine.errors.InsufficientHistoricalDataError`'s own
    naming convention (`Insufficient<Noun>Error`, a `ValueError`
    subclass) - a dedicated type, not a reuse of that error, because
    the two conditions are different: `InsufficientHistoricalDataError`
    means "zero bars at all"; this means "bars exist but do not span
    enough distinct calendar days to build the requested fold shape."
    """


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    """One (in-sample, out-of-sample) date-range pair, plus the bar
    counts on each side - matches CHECKPOINT_68.1_SUMMARY.md §C's
    dataclass exactly."""

    in_sample_start: datetime
    in_sample_end: datetime
    out_of_sample_start: datetime
    out_of_sample_end: datetime
    in_sample_bar_count: int
    out_of_sample_bar_count: int


def _distinct_calendar_dates(bars: tuple[Bar, ...]) -> tuple[date, ...]:
    seen: dict[date, None] = {}
    for bar in bars:
        seen[bar.timestamp.date()] = None
    return tuple(seen.keys())


def compute_walk_forward_folds(
    bars: tuple[Bar, ...],
    *,
    min_oos_days: int,
    min_folds: int,
) -> tuple[WalkForwardFold, ...]:
    """Pure function, no I/O. Derives fold boundaries from the REAL
    distinct calendar dates present in `bars` (see module docstring's
    "SCALE NOTE") - never a hardcoded calendar assumption, never a
    fixed bar-count-per-day assumption.

    Produces exactly `min_folds` folds (the minimum requested count,
    not an attempt to maximize fold count from the available data -
    documented deviation from 68.1 §C, see CHECKPOINT_68.2_SUMMARY.md),
    each with an out-of-sample window spanning exactly `min_oos_days`
    distinct calendar dates, and an ANCHORED/EXPANDING in-sample window
    (68.1 §B1's recommended primary strategy) that includes every
    distinct date strictly before its own out-of-sample window's first
    date - so fold N's in-sample window includes fold N-1's
    out-of-sample dates too, exactly as an anchored/expanding design
    requires.

    Raises `InsufficientDataForWalkForwardError` when the data cannot
    support even `min_folds` folds of `min_oos_days` each (with at
    least one distinct date left over for the very first fold's
    in-sample window) - never silently produces a misleadingly small
    fold.
    """
    if min_oos_days < 1:
        raise ValueError("min_oos_days must be >= 1")
    if min_folds < 1:
        raise ValueError("min_folds must be >= 1")

    dates = sorted(_distinct_calendar_dates(bars))
    total_days = len(dates)
    required_days = min_folds * min_oos_days + 1  # +1: at least one IS-only date
    if total_days < required_days:
        raise InsufficientDataForWalkForwardError(
            f"cannot build {min_folds} walk-forward fold(s) of {min_oos_days} "
            f"out-of-sample day(s) each: only {total_days} distinct calendar "
            f"date(s) available in the supplied bars, {required_days} required "
            "(min_folds * min_oos_days + 1 in-sample date)"
        )

    initial_in_sample_days = total_days - (min_folds * min_oos_days)

    bars_by_date: dict[date, list[Bar]] = {}
    for bar in bars:
        bars_by_date.setdefault(bar.timestamp.date(), []).append(bar)

    folds: list[WalkForwardFold] = []
    in_sample_end_idx = initial_in_sample_days  # exclusive index into `dates`
    for _ in range(min_folds):
        in_sample_dates = dates[:in_sample_end_idx]
        oos_dates = dates[in_sample_end_idx : in_sample_end_idx + min_oos_days]

        in_sample_bars = [b for d in in_sample_dates for b in bars_by_date[d]]
        oos_bars = [b for d in oos_dates for b in bars_by_date[d]]

        folds.append(
            WalkForwardFold(
                in_sample_start=in_sample_bars[0].timestamp,
                in_sample_end=in_sample_bars[-1].timestamp,
                out_of_sample_start=oos_bars[0].timestamp,
                out_of_sample_end=oos_bars[-1].timestamp,
                in_sample_bar_count=len(in_sample_bars),
                out_of_sample_bar_count=len(oos_bars),
            )
        )
        in_sample_end_idx += min_oos_days

    return tuple(folds)


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """Matches CHECKPOINT_68.1_SUMMARY.md §C's dataclass exactly."""

    folds: tuple[WalkForwardFold, ...]
    in_sample_results: tuple[BacktestResult, ...]
    out_of_sample_results: tuple[BacktestResult, ...]
    aggregate_oos_return: Decimal
    """Mean of each fold's out-of-sample `BacktestMetrics.
    return_percent` - the headline walk-forward number (68.1 §B3: the
    in-sample number is never the headline result)."""
    aggregate_oos_win_rate: Decimal
    """Mean of each fold's out-of-sample `BacktestMetrics.
    win_rate_percent`."""
    mean_degradation_ratio: Decimal | None
    """Mean, across folds, of (out-of-sample return_percent / in-sample
    return_percent) - 68.1 §B3's "single number that most directly
    answers does performance survive contact with unseen data." A fold
    whose in-sample `return_percent` is exactly 0 is EXCLUDED from this
    mean (the ratio is undefined, never reported as infinity or a
    fabricated 0 - matching `BacktestMetrics.profit_factor`'s own
    established "None when undefined" convention elsewhere in this
    module). `None` only when EVERY fold's in-sample return was 0 (no
    fold contributes a defined ratio)."""
    data_sufficiency_note: str
    """68.1 §B3's mandatory plain-language disclosure of fold count and
    per-fold bar/day counts - never silently omitted."""


def run_walk_forward_backtest(
    bars: tuple[Bar, ...],
    strategy: Strategy,
    strategy_config: StrategyConfigurationValues,
    backtest_config_template: BacktestConfiguration,
    compute_feature_series: FeatureSeriesComputer,
    *,
    data_quality: DataQualityDisclosure,
    generated_at: datetime,
    cost_model: CostModel | None = None,
    min_oos_days: int = 5,
    min_folds: int = 1,
) -> WalkForwardResult:
    """Calls `compute_walk_forward_folds()`, then calls the EXISTING,
    UNMODIFIED `engine.run_backtest()` twice per fold (once for the
    in-sample bar slice, once for the out-of-sample bar slice) -
    matching 68.1 §C exactly. `run_backtest()` itself is imported and
    called verbatim; this function never edits its behavior, monkey-
    patches it, or duplicates its simulation logic.

    `backtest_config_template` supplies every field `run_backtest()`
    needs EXCEPT `start`/`end`, which are replaced per-fold, per-side
    with that side's own real bar-timestamp range (via
    `dataclasses.replace()` - `BacktestConfiguration` is frozen, so a
    new instance is required per call, never a mutation of the
    template).
    """
    folds = compute_walk_forward_folds(bars, min_oos_days=min_oos_days, min_folds=min_folds)

    bars_by_date: dict[date, list[Bar]] = {}
    for bar in bars:
        bars_by_date.setdefault(bar.timestamp.date(), []).append(bar)

    in_sample_results: list[BacktestResult] = []
    out_of_sample_results: list[BacktestResult] = []

    for fold in folds:
        is_bars = tuple(
            b for b in bars if fold.in_sample_start <= b.timestamp <= fold.in_sample_end
        )
        oos_bars = tuple(
            b
            for b in bars
            if fold.out_of_sample_start <= b.timestamp <= fold.out_of_sample_end
        )

        is_config = replace(
            backtest_config_template,
            start=fold.in_sample_start,
            end=fold.in_sample_end,
        )
        oos_config = replace(
            backtest_config_template,
            start=fold.out_of_sample_start,
            end=fold.out_of_sample_end,
        )

        is_result = run_backtest(
            is_bars,
            strategy,
            strategy_config,
            is_config,
            compute_feature_series,
            data_quality=data_quality,
            generated_at=generated_at,
            cost_model=cost_model,
        )
        try:
            oos_result = run_backtest(
                oos_bars,
                strategy,
                strategy_config,
                oos_config,
                compute_feature_series,
                data_quality=data_quality,
                generated_at=generated_at,
                cost_model=cost_model,
            )
        except InsufficientHistoricalDataError:
            # A fold's own OOS slice being empty is a
            # compute_walk_forward_folds() bug, not an expected runtime
            # path (every fold's oos window is built from real bars
            # above) - re-raised, never swallowed, so it surfaces
            # loudly rather than silently degrading the aggregate.
            raise

        in_sample_results.append(is_result)
        out_of_sample_results.append(oos_result)

    aggregate_oos_return = _mean(r.metrics.return_percent for r in out_of_sample_results)
    aggregate_oos_win_rate = _mean(r.metrics.win_rate_percent for r in out_of_sample_results)

    degradation_ratios: list[Decimal] = []
    for is_result, oos_result in zip(in_sample_results, out_of_sample_results, strict=True):
        is_return = is_result.metrics.return_percent
        if is_return != 0:
            degradation_ratios.append(oos_result.metrics.return_percent / is_return)
    mean_degradation_ratio = _mean(degradation_ratios) if degradation_ratios else None

    note_lines = [
        f"{len(folds)} walk-forward fold(s) computed "
        f"(min_folds={min_folds}, min_oos_days={min_oos_days})."
    ]
    for idx, fold in enumerate(folds, start=1):
        note_lines.append(
            f"Fold {idx}: in-sample {fold.in_sample_start.date()}..{fold.in_sample_end.date()} "
            f"({fold.in_sample_bar_count} bars); out-of-sample "
            f"{fold.out_of_sample_start.date()}..{fold.out_of_sample_end.date()} "
            f"({fold.out_of_sample_bar_count} bars)."
        )
    if len(folds) < 3:
        note_lines.append(
            "Fold count is small (<3) - this result must not be presented with the "
            "same confidence as a hypothetical multi-fold (5-10) walk-forward run "
            "(CHECKPOINT_68.1_SUMMARY.md §B3)."
        )
    data_sufficiency_note = " ".join(note_lines)

    return WalkForwardResult(
        folds=folds,
        in_sample_results=tuple(in_sample_results),
        out_of_sample_results=tuple(out_of_sample_results),
        aggregate_oos_return=aggregate_oos_return,
        aggregate_oos_win_rate=aggregate_oos_win_rate,
        mean_degradation_ratio=mean_degradation_ratio,
        data_sufficiency_note=data_sufficiency_note,
    )


def _mean(values: "list[Decimal] | filter") -> Decimal:
    values = list(values)
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))
