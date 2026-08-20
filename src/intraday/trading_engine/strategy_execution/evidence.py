# File: src/intraday/trading_engine/strategy_execution/evidence.py
#
# Checkpoint 64.18 §5-9: the generic "why did the strategy generate this
# signal" contract. `StrategySignal.evidence` (Checkpoint 26,
# `contracts.py`) already carries every strategy's REAL, already-
# computed `FeatureValue` tuple (fast/slow EMA, SMA, ATR) - this module
# adds NOTHING to that computation. It only maps those already-real
# values (plus the signal's own already-computed `price`/`direction`,
# never a new calculation) into a generic, human-readable, versioned
# shape a persistence layer/API/frontend can render WITHOUT any
# strategy-specific branching (§6's explicit "no EMA-specific database
# logic, no ATR-specific frontend logic").
from __future__ import annotations

from dataclasses import dataclass

from intraday.trading_engine.strategy_execution.contracts import StrategyDirection, StrategySignal

SIGNAL_EVIDENCE_SCHEMA_VERSION = "1"
"""Checkpoint 64.18 §11: bumped only if the FIELD SHAPE itself changes
in a way that would make an already-persisted `SignalEvidenceRecord`
ambiguous to render - a historical record's own stored `schema_version`
is what the reader trusts, never this module's current constant, so an
older record always stays readable even after this changes."""


@dataclass(frozen=True, slots=True)
class SignalEvidenceField:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class SignalEvidence:
    schema_version: str
    strategy_id: str
    fields: tuple[SignalEvidenceField, ...]


def _direction_label(direction: StrategyDirection) -> str:
    return {
        StrategyDirection.BULLISH: "Bullish",
        StrategyDirection.BEARISH: "Bearish",
        StrategyDirection.NEUTRAL: "Neutral",
    }[direction]


def describe_ema_crossover_evidence(signal: StrategySignal) -> SignalEvidence:
    """`signal.evidence` is `(fast, slow)` in that exact order (see
    `EmaCrossoverStrategy.evaluate()`'s own `evidence=(fast, slow)`) -
    read positionally, never recomputed."""
    fast_value = signal.evidence[0].value if len(signal.evidence) > 0 else None
    slow_value = signal.evidence[1].value if len(signal.evidence) > 1 else None
    fields = (
        SignalEvidenceField(
            label="Fast EMA", value=f"{fast_value}" if fast_value is not None else "Not provided"
        ),
        SignalEvidenceField(
            label="Slow EMA", value=f"{slow_value}" if slow_value is not None else "Not provided"
        ),
        SignalEvidenceField(label="Price", value=f"{signal.price}"),
        SignalEvidenceField(label="Crossover", value=_direction_label(signal.direction)),
    )
    return SignalEvidence(
        schema_version=SIGNAL_EVIDENCE_SCHEMA_VERSION, strategy_id=signal.strategy_id, fields=fields
    )


def describe_sma_trend_filter_evidence(signal: StrategySignal) -> SignalEvidence:
    """`signal.evidence` is `(sma,)` (see `SmaTrendFilterStrategy.
    evaluate()`'s own `evidence=(sma,)`). `Distance %` is a plain,
    already-known arithmetic PRESENTATION of two already-computed
    values (price, sma) - not a new strategy decision, matching §9's
    "no recomputation of the decision" (the DIRECTION itself is read
    verbatim from `signal.direction`, never re-derived here)."""
    sma_value = signal.evidence[0].value if signal.evidence else None
    distance_label = "Not provided"
    if sma_value is not None and sma_value != 0:
        distance_percent = (signal.price - sma_value) / sma_value * 100
        distance_label = f"{distance_percent:.2f}%"
    fields = (
        SignalEvidenceField(
            label="SMA", value=f"{sma_value}" if sma_value is not None else "Not provided"
        ),
        SignalEvidenceField(label="Price", value=f"{signal.price}"),
        SignalEvidenceField(label="Distance %", value=distance_label),
        SignalEvidenceField(label="Direction", value=_direction_label(signal.direction)),
    )
    return SignalEvidence(
        schema_version=SIGNAL_EVIDENCE_SCHEMA_VERSION, strategy_id=signal.strategy_id, fields=fields
    )


def describe_atr_volatility_breakout_evidence(signal: StrategySignal) -> SignalEvidence:
    """`signal.evidence` is `(atr,)` (see `AtrVolatilityBreakoutStrategy.
    evaluate()`'s own `evidence=(atr,)`)."""
    atr_value = signal.evidence[0].value if signal.evidence else None
    fields = (
        SignalEvidenceField(
            label="ATR", value=f"{atr_value}" if atr_value is not None else "Not provided"
        ),
        SignalEvidenceField(label="Price", value=f"{signal.price}"),
        SignalEvidenceField(label="Breakout", value=_direction_label(signal.direction)),
    )
    return SignalEvidence(
        schema_version=SIGNAL_EVIDENCE_SCHEMA_VERSION, strategy_id=signal.strategy_id, fields=fields
    )


def describe_test_momentum_evidence(signal: StrategySignal) -> SignalEvidence:
    """Checkpoint 64.20 §8/§9: NON_PRODUCTION - the proof-of-extensibility
    `TestMomentumStrategy`'s own evidence describer. `signal.evidence` is
    `(ema,)` (same single-feature shape as SMA's own describer above).
    Exists to prove that adding evidence support for a NEW strategy is
    exactly ONE registration entry below, never a change to
    `build_signal_evidence()`'s own dispatch logic."""
    ema_value = signal.evidence[0].value if signal.evidence else None
    fields = (
        SignalEvidenceField(
            label="EMA", value=f"{ema_value}" if ema_value is not None else "Not provided"
        ),
        SignalEvidenceField(label="Price", value=f"{signal.price}"),
        SignalEvidenceField(label="Momentum", value=_direction_label(signal.direction)),
    )
    return SignalEvidence(
        schema_version=SIGNAL_EVIDENCE_SCHEMA_VERSION, strategy_id=signal.strategy_id, fields=fields
    )


_DESCRIBERS = {
    "ema_crossover": describe_ema_crossover_evidence,
    "sma_trend_filter": describe_sma_trend_filter_evidence,
    "atr_volatility_breakout": describe_atr_volatility_breakout_evidence,
    # Checkpoint 64.20 §8/§9: the ONE registration line the proof-of-
    # extensibility test strategy needed here - never a change to any
    # engine's own logic. `test_momentum` is NEVER in
    # `build_default_registry()` (verified by a dedicated test), so this
    # entry is dormant/unreachable in production - it only fires when
    # the dedicated extensibility test constructs its own local registry.
    "test_momentum": describe_test_momentum_evidence,
}


def build_signal_evidence(signal: StrategySignal) -> SignalEvidence | None:
    """The ONE dispatch point - never a chain of `if strategy_id ==
    ...` branches duplicated in the persistence/API/frontend layers.
    Returns `None` for a strategy with no registered describer, an
    honest absence rather than a fabricated empty evidence record."""
    describer = _DESCRIBERS.get(signal.strategy_id)
    return describer(signal) if describer is not None else None


__all__ = [
    "SIGNAL_EVIDENCE_SCHEMA_VERSION",
    "SignalEvidence",
    "SignalEvidenceField",
    "build_signal_evidence",
    "describe_atr_volatility_breakout_evidence",
    "describe_ema_crossover_evidence",
    "describe_sma_trend_filter_evidence",
    "describe_test_momentum_evidence",
]
