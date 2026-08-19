# File: src/intraday/trading_engine/strategy_execution/contracts.py
#
# Checkpoint 26: the strategy-execution contracts this bounded context's
# own Checkpoint-1 README already named as its responsibility ("converts
# STRATEGY OUTPUT into canonical Signal objects") - built now that a real
# need (multiple executable strategies) exists.
#
# `StrategySignal` deliberately does NOT touch or duplicate
# `signal_intelligence.signal_generation.contracts.DirectionalIndication`.
# That type is the fixed-shape output of exactly one specific rule
# (`generate_directional_indication` - hard-coded sma/ema/atr fields,
# fixed `DIRECTIONAL_INDICATION_DEFINITION_NAME`) and cannot represent an
# arbitrary strategy's evidence. `StrategySignal` generalizes what
# `DirectionalIndication` fixes in place - a three-state direction plus
# `FeatureValue` evidence - and adds exactly what no existing type
# carries: strategy/version/configuration attribution. This is the
# evolution `DirectionalIndication`'s own Checkpoint 18 docstring
# predicted ("future strategy layer will consume DirectionalIndications...
# to produce a real domain.signal.Signal"), not a second competing
# signal model. It still does not become `domain.signal.Signal` - no
# stop-loss/target/position-size authority is claimed here, extending
# Checkpoint 18's own reasoning rather than overriding it.
#
# `StrategyDirection` below is DELIBERATELY NOT an import of
# `signal_intelligence.signal_generation.contracts.SignalDirection`,
# even though the two are semantically identical (BULLISH/BEARISH/
# NEUTRAL). Two hard constraints rule out reuse: (1) `.importlinter`
# contract 4 ("Bounded-context independence") forbids
# `intraday.trading_engine` from importing `intraday.signal_intelligence`
# at all - re-verified live during this checkpoint's own Part 2 audit,
# which caught an earlier draft of this file violating exactly this
# rule; (2) `domain.shared_kernel` is locked to its originally-approved
# 14 contracts (Checkpoint 3), so promoting `SignalDirection` there is
# not available either. A small, structurally parallel enum, owned by
# this bounded context, is the only option the existing architecture
# rules leave open - not an oversight, a consequence of those rules
# being enforced rather than relaxed for convenience.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, ensure_utc
from intraday.trading_engine.strategy_execution.errors import (
    InvalidParameterValueError,
    MissingRequiredParameterError,
    UnknownFieldReferenceError,
    UnknownParameterError,
)


class StrategyDirection(str, Enum):
    """Trading_engine's own directional vocabulary - see the module
    docstring above for exactly why this cannot import
    `signal_generation.SignalDirection` instead."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class ParameterType(str, Enum):
    """The generic value shapes the dynamic schema renderer must support
    (Checkpoint 26 Part 5/6) - deliberately small and closed, matching
    only what the three initial strategies actually need. A new type is
    added only when a real strategy needs it, not speculatively."""

    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    ENUM = "ENUM"
    FIELD_REFERENCE = "FIELD_REFERENCE"
    TIMEFRAME = "TIMEFRAME"


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    """One configurable parameter slot in a strategy's schema. Generic -
    the frontend renders a form control purely from this metadata
    (Part 13's "NOT strategy-specific hardcoded forms" requirement); no
    per-strategy widget code exists anywhere in this checkpoint."""

    parameter_id: str
    label: str
    parameter_type: ParameterType
    required: bool
    default: object | None = None
    minimum: Decimal | int | None = None
    maximum: Decimal | int | None = None
    allowed_values: tuple[str, ...] = ()
    field_category: str | None = None
    depends_on: tuple[str, ...] = ()
    help_text: str = ""

    def __post_init__(self) -> None:
        if not self.parameter_id.strip():
            raise ValueError("ParameterDefinition.parameter_id must be non-empty")
        if self.parameter_type == ParameterType.ENUM and not self.allowed_values:
            raise ValueError(
                f"ParameterDefinition {self.parameter_id!r}: ENUM requires allowed_values"
            )


@dataclass(frozen=True, slots=True)
class StrategyParameterSchema:
    """The full, ordered set of parameters one strategy accepts. Order is
    the declared display order for the frontend (deterministic - Part 14)."""

    strategy_id: str
    parameters: tuple[ParameterDefinition, ...]

    def get(self, parameter_id: str) -> ParameterDefinition | None:
        for p in self.parameters:
            if p.parameter_id == parameter_id:
                return p
        return None


@dataclass(frozen=True, slots=True)
class StrategyConfigurationValues:
    """Validated configuration VALUES for one strategy version - the type
    `application/config_schema/strategy.py`'s own prior-checkpoint comment
    explicitly deferred ("Inventing a generic 'parameters' schema now
    would be exactly the mistake..."). Distinct from and layered on top
    of (never replacing) `domain.strategy.contracts.StrategyVersion`,
    which remains the version-IDENTITY record; this carries the actual
    values that identity's `configuration_version` label points at."""

    strategy_id: str
    specification_version: str
    code_version: str
    configuration_version: str
    values: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "strategy_id",
            "specification_version",
            "code_version",
            "configuration_version",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"StrategyConfigurationValues.{name} must be non-empty")


def coerce_configuration_values(
    schema: StrategyParameterSchema, values: dict[str, object]
) -> dict[str, object]:
    """A REAL bug this fixes, found from a live report: `validate_configuration`
    below requires a DECIMAL-typed parameter to be an actual Python
    `Decimal` INSTANCE, but JSON has no native Decimal type at all - a
    value arriving over the API as `"0.02"` (or as a JSON number, which
    `json` would decode as `float`, not `Decimal`) can NEVER satisfy
    that `isinstance(value, Decimal)` check by any client-side encoding
    choice. This is the ONE place that gap is closed - every caller
    that accepts configuration values from outside the process
    (`BacktestingService.run()`, `StrategyConfigurationService.
    save_configuration()`) must call this BEFORE `validate_configuration()`,
    never construct/validate raw API values directly.

    Only DECIMAL-typed parameters are touched (`Decimal(str(value))` -
    routing through `str()` first avoids `Decimal(float)`'s well-known
    binary-floating-point-precision surprises, e.g. `Decimal(0.02) ==
    Decimal('0.0200000000000000004440892...')`). INTEGER values are
    left untouched: a JSON number without a decimal point already
    decodes to a native Python `int`, which `validate_configuration`
    already accepts directly - no coercion gap exists there. Any value
    that cannot be parsed as a Decimal raises `InvalidParameterValueError`
    immediately, with the exact same message shape
    `_validate_single_value` already uses elsewhere, rather than
    silently passing through a bad value for the isinstance check
    below to reject less informatively."""
    coerced = dict(values)
    for param in schema.parameters:
        if param.parameter_type != ParameterType.DECIMAL:
            continue
        if param.parameter_id not in coerced:
            continue
        value = coerced[param.parameter_id]
        if isinstance(value, Decimal):
            continue
        try:
            coerced[param.parameter_id] = Decimal(str(value))
        except Exception as exc:  # noqa: BLE001 - decimal.InvalidOperation and friends, all invalid input
            raise InvalidParameterValueError(
                f"strategy {schema.strategy_id!r}: parameter {param.parameter_id!r} "
                f"is not a Decimal: {value!r}"
            ) from exc
    return coerced


def validate_configuration(
    schema: StrategyParameterSchema, values: dict[str, object], *, known_field_ids: frozenset[str]
) -> None:
    """Validates raw configuration values against a strategy's schema.
    Reused identically by the application-layer service and by tests -
    a single validation path, never duplicated per-strategy."""
    declared_ids = {p.parameter_id for p in schema.parameters}
    for supplied_id in values:
        if supplied_id not in declared_ids:
            raise UnknownParameterError(
                f"strategy {schema.strategy_id!r}: unknown parameter {supplied_id!r}"
            )

    for param in schema.parameters:
        if param.parameter_id not in values:
            if param.required and param.default is None:
                raise MissingRequiredParameterError(
                    f"strategy {schema.strategy_id!r}: missing required parameter "
                    f"{param.parameter_id!r}"
                )
            continue

        value = values[param.parameter_id]
        _validate_single_value(schema.strategy_id, param, value, known_field_ids=known_field_ids)


def _validate_single_value(
    strategy_id: str,
    param: ParameterDefinition,
    value: object,
    *,
    known_field_ids: frozenset[str],
) -> None:
    if param.parameter_type == ParameterType.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidParameterValueError(
                f"strategy {strategy_id!r}: parameter {param.parameter_id!r} must be an int"
            )
        _check_range(strategy_id, param, value)
    elif param.parameter_type == ParameterType.DECIMAL:
        if not isinstance(value, Decimal):
            raise InvalidParameterValueError(
                f"strategy {strategy_id!r}: parameter {param.parameter_id!r} must be a Decimal"
            )
        _check_range(strategy_id, param, value)
    elif param.parameter_type == ParameterType.ENUM:
        if value not in param.allowed_values:
            raise InvalidParameterValueError(
                f"strategy {strategy_id!r}: parameter {param.parameter_id!r} value {value!r} "
                f"not in {param.allowed_values!r}"
            )
    elif param.parameter_type == ParameterType.TIMEFRAME:
        if not isinstance(value, Timeframe):
            raise InvalidParameterValueError(
                f"strategy {strategy_id!r}: parameter {param.parameter_id!r} must be a Timeframe"
            )
    elif param.parameter_type == ParameterType.FIELD_REFERENCE:
        if not isinstance(value, str) or value not in known_field_ids:
            raise UnknownFieldReferenceError(
                f"strategy {strategy_id!r}: parameter {param.parameter_id!r} references "
                f"unknown field {value!r}"
            )


def require_int(values: dict[str, object], parameter_id: str) -> int:
    """Typed accessor for an INTEGER-typed configuration value - used by
    strategy implementations after `validate_configuration()` has
    already confirmed the value's type, so this never raises in
    practice; it exists purely so mypy's strict mode does not need
    `int(some_object)` (unsupported by `int`'s own overloads) scattered
    across every strategy module."""
    value = values[parameter_id]
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidParameterValueError(f"parameter {parameter_id!r} is not an int: {value!r}")
    return value


def require_decimal(values: dict[str, object], parameter_id: str) -> Decimal:
    """Typed accessor for a DECIMAL-typed configuration value - see
    `require_int`'s docstring for why this exists."""
    value = values[parameter_id]
    if not isinstance(value, Decimal):
        raise InvalidParameterValueError(f"parameter {parameter_id!r} is not a Decimal: {value!r}")
    return value


def _check_range(strategy_id: str, param: ParameterDefinition, value: int | Decimal) -> None:
    if param.minimum is not None and value < param.minimum:
        raise InvalidParameterValueError(
            f"strategy {strategy_id!r}: parameter {param.parameter_id!r} value {value!r} "
            f"below minimum {param.minimum!r}"
        )
    if param.maximum is not None and value > param.maximum:
        raise InvalidParameterValueError(
            f"strategy {strategy_id!r}: parameter {param.parameter_id!r} value {value!r} "
            f"above maximum {param.maximum!r}"
        )


@dataclass(frozen=True, slots=True)
class StrategySignal:
    """A canonical strategy-attributed directional signal - the type
    described in this module's own header. Reuses `FeatureValue`
    (domain.feature) and this module's own `StrategyDirection` rather
    than inventing further parallel vocabulary; adds strategy/version/
    configuration attribution that no existing type carries."""

    strategy_id: str
    specification_version: str
    code_version: str
    configuration_version: str
    instrument_id: InstrumentId
    timeframe: Timeframe
    timestamp: datetime
    direction: StrategyDirection
    price: Decimal
    evidence: tuple[FeatureValue, ...] = ()

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp, field_name="StrategySignal.timestamp")
        if not self.strategy_id.strip():
            raise ValueError("StrategySignal.strategy_id must be non-empty")
        for feature_value in self.evidence:
            if feature_value.instrument_id != self.instrument_id:
                raise ValueError("StrategySignal.evidence instrument_id mismatch")
            if feature_value.timeframe != self.timeframe:
                raise ValueError("StrategySignal.evidence timeframe mismatch")
            if feature_value.timestamp != self.timestamp:
                raise ValueError("StrategySignal.evidence timestamp mismatch")


@dataclass(frozen=True, slots=True)
class TradePlan:
    """Checkpoint 64.7: the canonical, SOLE owner of entry/stop-loss/
    target/trailing-stop values (the architecture decision made in
    Checkpoint 64.6's report). Deliberately NOT a field on
    `StrategySignal` - a directional-only strategy (e.g.
    `ema_crossover`) produces a signal with no `TradePlan` at all
    (`build_trade_plan()` returning `None` is a normal, expected
    outcome, not an error). Every field below is independently
    nullable - a strategy may produce a partial plan (e.g. an entry and
    a stop loss but no targets) - NEVER fabricated to fill a gap.
    Everything downstream (`RiskDecision`, `PaperOrder`, `Position`,
    `SignalCommunicationContext`) REFERENCES a plan by `signal_id`
    rather than duplicating these fields - see
    `infrastructure/persistence/trade_plan_repository.py` for the one
    persisted copy."""

    strategy_id: str
    code_version: str
    generated_at: datetime
    calculation_method: str
    """A human-readable description of exactly how these values were
    derived (e.g. "ATR(14) volatility-based: entry=breakout close,
    stop_loss=entry-1.0xATR, target_1=entry+1.5xATR...") - this IS the
    per-plan "source/calculation/version" record the brief requires;
    `code_version` above is the "version," `generated_at` is the
    "timestamp," and this field is the "source/calculation" for every
    value in the plan (one calculation covers the whole plan, since
    every level here is derived from the same strategy evaluation, not
    independently sourced)."""
    entry_price: Decimal | None = None
    stop_loss: Decimal | None = None
    target_1: Decimal | None = None
    target_2: Decimal | None = None
    target_3: Decimal | None = None
    trailing_stop_loss: Decimal | None = None

    def targets(self) -> tuple[Decimal, ...]:
        """Only the targets that were actually produced - never pads
        with a fabricated value to reach 3."""
        return tuple(t for t in (self.target_1, self.target_2, self.target_3) if t is not None)
