# File: src/intraday/application/services/adhoc_screening.py
#
# CHECKPOINT-SCANNER-A, Phase A of SCANNER_BUILDER_ROADMAP.md: pure
# condition-evaluation logic for a discretionary, MANUAL screening
# rule. NO UI, NO new API endpoint, NO new persistence — exactly this
# checkpoint's own stated scope.
#
# ARCHITECTURE BOUNDARY, enforced mechanically (see
# tests/unit/architecture/test_adhoc_screening_boundary.py), not just
# declared: this module NEVER imports `Strategy`, `StrategyRegistry`,
# `StrategyExecutionCoordinator`, `run_active_loop_tick`, `PaperBroker`,
# or `ScannerConfiguration`, and it produces a `ScreeningMatch`
# (domain.screening.contracts) — never a `Signal`, never an `Order`,
# never anything that reaches `PaperBroker`. It reuses
# `compute_feature_series` (relocated this checkpoint to
# `signal_intelligence.feature_engine.dispatch` — see that module's own
# header for why) exactly as `application.services.strategy_execution`
# does, but composes it toward a MATCH/NO-MATCH table, never a trading
# decision.
#
# `AdhocScreeningService.screen()` takes bars as an input parameter
# (`bars_by_instrument`) rather than fetching them itself — Phase B's
# own concern is wiring a real data source (`HistoricalBar` for
# "Historical" mode, `AggregatedBarObservation` for "Live" mode, per
# SCANNER_BUILDER_ROADMAP.md Part 1 finding 4) behind this same
# interface; this phase stays fixture-testable with zero DB access.
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from intraday.domain.feature.contracts import CategoricalFeatureValue, FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.screening.contracts import (
    CATEGORICAL_COMPATIBLE_OPERATORS,
    ComparisonOperator,
    RuleCombinator,
    ScreeningMatch,
    ScreeningRule,
)
from intraday.signal_intelligence.feature_engine.dispatch import compute_feature_series
from intraday.signal_intelligence.feature_engine.field_registry import resolve_feature_name

_RAW_FIELD_IDS = frozenset({"open", "high", "low", "close", "volume"})


def _is_registered_field_reference(name: str) -> bool:
    """True if `name` names a real, registered field (raw OHLCV or a
    parameterized derived feature, e.g. `"ema_20"`) - used to decide
    whether a `str` comparison target is a field-vs-field reference to
    resolve, or a literal categorical constant (e.g. `"BULL"`, which is
    never a registered field_id) to compare against as-is."""
    if name in _RAW_FIELD_IDS:
        return True
    return resolve_feature_name(name).field_id is not None


def _resolve_latest_value(field_id: str, bars: tuple[Bar, ...]) -> Decimal | str | None:
    """Resolves `field_id`'s most recent available value against `bars`
    — a raw OHLCV field is read straight off the last bar (matching
    `field_registry.py`'s own documented convention: "raw OHLCV fields
    are read straight off Bar, never computed"); anything else is
    dispatched through `compute_feature_series`, taking the LAST
    entry of its returned series (the most recent computed reading —
    several feature functions skip early, not-yet-warmed-up bars and
    return a series shorter than `bars` itself; the last entry is
    still the correct "current" reading to compare against).

    Returns `None` — never raises, never fabricates a value — when
    there is no data to resolve at all: an empty `bars` tuple, or a
    feature whose own warm-up requirement genuinely has not been met
    yet (its compute function returns an empty series). This is the
    "graceful handling of insufficient data" `evaluate_condition`
    relies on: missing DATA is a `None`/no-match outcome, never an
    exception - only a genuine TYPE mismatch (comparing a category to
    a number) raises, see `evaluate_condition`'s own docstring."""
    if not bars:
        return None
    if field_id in _RAW_FIELD_IDS:
        return getattr(bars[-1], field_id)
    values = compute_feature_series(field_id, bars)
    if not values:
        return None
    latest = values[-1]
    if isinstance(latest, FeatureValue):
        return latest.value
    if isinstance(latest, CategoricalFeatureValue):
        return latest.category
    raise TypeError(  # pragma: no cover - defensive, AnyFeatureValue has exactly these 2 members
        f"unexpected feature value type {type(latest)!r} for field_id {field_id!r}"
    )


_NUMERIC_COMPARISONS = {
    ComparisonOperator.GREATER_THAN: lambda left, right: left > right,
    ComparisonOperator.LESS_THAN: lambda left, right: left < right,
    ComparisonOperator.GREATER_THAN_OR_EQUAL: lambda left, right: left >= right,
    ComparisonOperator.LESS_THAN_OR_EQUAL: lambda left, right: left <= right,
    ComparisonOperator.EQUAL: lambda left, right: left == right,
}


def evaluate_condition(
    field_id: str,
    operator: ComparisonOperator,
    value: Decimal | str,
    bars: tuple[Bar, ...],
) -> bool:
    """Evaluates ONE condition (`field_id <operator> value`) against
    `bars`. Supports both scope cases the roadmap names:
      - field-vs-constant (`value` is a `Decimal`, e.g. `RSI(14) < 30`);
      - field-vs-field (`value` is a `str` field_id, resolved through
        the SAME `_resolve_latest_value` as the left side, e.g.
        `Close > EMA(20)` with `value="ema_20"`).

    Both sides are resolved to their LATEST available reading (see
    `_resolve_latest_value`'s own docstring) before comparing - never a
    full-series comparison, matching a "does this condition hold RIGHT
    NOW" screening question, not a historical-crossover one.

    When `value` is a `str`, it is resolved as a field-vs-field
    reference ONLY if it names a real, registered field_id
    (`_is_registered_field_reference`); otherwise it is treated as a
    literal CATEGORICAL constant compared as-is (e.g.
    `market_regime == "BULL"` - `"BULL"` is never a registered field_id,
    so it is never mistaken for one to resolve).

    GRACEFUL missing-data handling (a real Phase A testing
    requirement): if either side cannot be resolved at all (empty
    `bars`, or a not-yet-warmed-up indicator), this returns `False` -
    "does not currently match," never an exception. An indicator
    requiring more warm-up than the supplied bars provide is the
    expected, ordinary shape of this case, not an error condition.

    TYPE-MISMATCH handling (a genuine condition-authoring error, NOT a
    missing-data case - raised loudly, never silently swallowed into a
    `False`): if either side resolves to a categorical value (a `str`,
    e.g. `market_regime`'s "BULL"/"BEAR"/...), `operator` must be
    `EQUAL` (the only operator `>`/`<`/`>=`/`<=` cannot mean anything
    for a category - see `domain.screening.contracts.
    CATEGORICAL_COMPATIBLE_OPERATORS`), and BOTH sides must resolve to
    the same type (comparing a category to a numeric constant is
    always a condition-authoring mistake, e.g. accidentally writing
    `market_regime == 1` instead of a category name)."""
    left = _resolve_latest_value(field_id, bars)
    if isinstance(value, Decimal):
        right: Decimal | str | None = value
    elif _is_registered_field_reference(value):
        right = _resolve_latest_value(value, bars)
    else:
        right = value  # a literal categorical constant, e.g. "BULL"

    if left is None or right is None:
        return False

    left_is_categorical = isinstance(left, str)
    right_is_categorical = isinstance(right, str)

    if left_is_categorical or right_is_categorical:
        if operator not in CATEGORICAL_COMPATIBLE_OPERATORS:
            raise ValueError(
                f"operator {operator.value!r} is not valid for a categorical field "
                f"(field_id={field_id!r}) - only {sorted(o.value for o in CATEGORICAL_COMPATIBLE_OPERATORS)} "
                "are meaningful for a category."
            )
        if left_is_categorical != right_is_categorical:
            raise ValueError(
                f"type mismatch comparing field_id={field_id!r} (resolved "
                f"{'categorical' if left_is_categorical else 'numeric'}) against "
                f"{value!r} (resolved {'categorical' if right_is_categorical else 'numeric'}) "
                "- a category can only be compared to another category."
            )
        return left == right

    return _NUMERIC_COMPARISONS[operator](left, right)


@dataclass(frozen=True, slots=True)
class AdhocScreeningService:
    """The thin orchestrator: evaluate every condition in a
    `ScreeningRule`, per instrument, combine via the rule's own
    `RuleCombinator`, and return the instruments that matched -
    NEVER a `Signal`, NEVER touching `Strategy`/`PaperBroker`/
    `ScannerConfiguration` (mechanically proven, see this module's own
    header comment)."""

    def screen(
        self,
        rule: ScreeningRule,
        instrument_ids: tuple[str, ...],
        timeframe: object,
        bars_by_instrument: dict[str, tuple[Bar, ...]],
    ) -> tuple[ScreeningMatch, ...]:
        """`timeframe` is accepted but not itself consulted by this
        pure evaluation step (`bars_by_instrument` already carries
        whatever timeframe's bars the caller resolved) - kept as an
        explicit parameter per this checkpoint's own specified
        signature, so Phase B's real data-fetch wiring (which DOES need
        to know the timeframe to fetch the right bars) can be added
        behind this same call shape without changing it again."""
        matches: list[ScreeningMatch] = []
        for instrument_id in instrument_ids:
            bars = bars_by_instrument.get(instrument_id, ())
            results: list[bool] = []
            details: list[str] = []
            for condition in rule.conditions:
                result = evaluate_condition(
                    condition.field_id, condition.operator, condition.comparison, bars
                )
                results.append(result)
                details.append(
                    f"{condition.field_id} {condition.operator.value} {condition.comparison}: {result}"
                )
            matched = all(results) if rule.combinator is RuleCombinator.AND else any(results)
            if matched:
                matches.append(
                    ScreeningMatch(
                        instrument_id=instrument_id, matched_condition_details=tuple(details)
                    )
                )
        return tuple(matches)


__all__ = ["evaluate_condition", "AdhocScreeningService"]
