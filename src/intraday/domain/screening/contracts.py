# File: src/intraday/domain/screening/contracts.py
#
# CHECKPOINT-SCANNER-A, Phase A of SCANNER_BUILDER_ROADMAP.md: the
# canonical domain types for a discretionary, MANUAL screening rule —
# "pick a field, an operator, and a comparison target; combine multiple
# conditions with AND/OR; see which instruments match."
#
# Deliberately NOT `trading_engine.strategy_execution.contracts`'
# `ParameterDefinition`/signal-decision types, per the roadmap's own
# explicit instruction (Part 2 item 2). A screening condition is not a
# strategy parameter: it carries no `parameter_id`, no default, no
# schema-validation metadata a UI form needs — only what evaluating a
# comparison actually requires. And a screening MATCH is not a
# `Signal`: it is never `PENDING`/`VALIDATED`/`REJECTED`, never
# produces an `Order`, never reaches `PaperBroker` — this module (and
# every module built on it this checkpoint) imports nothing from
# `domain.signal`, `trading_engine.strategy_execution`, or
# `infrastructure.brokers.paper` at all (see
# tests/unit/architecture/test_adhoc_screening_boundary.py for the
# mechanically-enforced proof).
from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal


class ComparisonOperator(str, enum.Enum):
    """The closed set of comparisons a screening condition supports.
    Deliberately small — this is a manual exploration tool, not a
    general expression language (per the roadmap's own "no nested
    groups initially" scope)."""

    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN_OR_EQUAL = "<="
    EQUAL = "=="


# The set of operators that make sense against a CATEGORICAL field
# (e.g. `market_regime`, whose value is a string like "BULL", not a
# number) — only equality is meaningful for a category; asking whether
# one category is ">" another is a category error, not a missing-data
# case, so `evaluate_condition` raises for it rather than silently
# returning `False` (see that function's own docstring).
CATEGORICAL_COMPATIBLE_OPERATORS = frozenset({ComparisonOperator.EQUAL})


@dataclass(frozen=True, slots=True)
class ScreeningCondition:
    """ONE condition: `field_id <operator> comparison`.

    `field_id` is a canonical registry id, parameterized exactly the
    way `signal_intelligence.feature_engine.field_registry` already
    represents it (`"close"`, `"ema_20"`, `"rsi_14"`, `"market_regime_20_9_20"`,
    ...) — never re-validated or re-parsed here; that remains
    `field_registry`'s own, single responsibility.

    `comparison` is EITHER a fixed numeric threshold (`Decimal` — the
    field-vs-constant case, e.g. `RSI(14) < 30`) OR a `str`, which is
    interpreted as ONE of two things depending on what it actually
    names: if it resolves to a REGISTERED field_id (checked against
    `signal_intelligence.feature_engine.field_registry`, e.g.
    `"ema_20"`), it is the field-vs-field case (`Close > EMA(20)`,
    `comparison="ema_20"`); otherwise it is taken as a literal
    CATEGORICAL constant to compare a categorical field against (e.g.
    `market_regime == "BULL"`, `comparison="BULL"` — `"BULL"` is not a
    registered field_id, so it is never mistaken for one). See
    `evaluate_condition`'s own docstring for exactly how this
    resolution order is applied. This is a deliberately minimal,
    two-case-plus-fallback union rather than a wrapper/tagged type —
    the roadmap's own Phase A scope names exactly the field-vs-constant
    and field-vs-field cases; the categorical-constant fallback is the
    smallest addition that makes `market_regime`-style fields usable at
    all without a third dataclass variant."""

    field_id: str
    operator: ComparisonOperator
    comparison: Decimal | str

    def __post_init__(self) -> None:
        if not self.field_id.strip():
            raise ValueError("ScreeningCondition.field_id must be non-empty")
        if isinstance(self.comparison, str) and not self.comparison.strip():
            raise ValueError("ScreeningCondition.comparison, if a field_id, must be non-empty")


class RuleCombinator(str, enum.Enum):
    """How multiple conditions in one rule combine. No nested groups —
    exactly the roadmap's own stated Phase A scope ("single field vs.
    constant or field vs. field... combined with AND/OR, no nested
    groups initially")."""

    AND = "AND"
    OR = "OR"


@dataclass(frozen=True, slots=True)
class ScreeningRule:
    """A complete, evaluable screening rule — one or more conditions,
    combined uniformly by ONE combinator (never a per-pair mix of
    AND/OR without a group structure, which is exactly the nesting this
    phase explicitly defers)."""

    conditions: tuple[ScreeningCondition, ...]
    combinator: RuleCombinator

    def __post_init__(self) -> None:
        if not self.conditions:
            raise ValueError("ScreeningRule.conditions must be non-empty")


@dataclass(frozen=True, slots=True)
class ScreeningMatch:
    """ONE instrument that satisfied a `ScreeningRule` against its own
    bars. `matched_condition_details` is a human-readable trail (one
    entry per condition in the rule, in order) — e.g.
    `"close(1305.20) > ema_20(1298.40): True"` — so an operator can see
    WHY an instrument matched, not just THAT it did. This is
    deliberately NOT a `Signal`: no status, no strategy_id, no
    execution semantics of any kind — a screening match is a read-only
    observation the trader looks at themselves, exactly the roadmap's
    own "never a `Signal`" framing."""

    instrument_id: str
    matched_condition_details: tuple[str, ...]


__all__ = [
    "ComparisonOperator",
    "CATEGORICAL_COMPATIBLE_OPERATORS",
    "ScreeningCondition",
    "RuleCombinator",
    "ScreeningRule",
    "ScreeningMatch",
]
