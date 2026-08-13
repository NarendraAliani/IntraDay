# File: src/intraday/signal_intelligence/signal_generation/contracts.py
#
# Checkpoint 18: the output shape of the first Signal Generation rule -
# `DirectionalIndication`, NOT `domain.signal.Signal`.
#
# ---------------------------------------------------------------------------
# Why this is not domain.signal.Signal (Checkpoint 18 §4 - a real
# architectural finding, not an assumption)
# ---------------------------------------------------------------------------
#
# `domain/signal/contracts.py`'s `Signal` (Checkpoint 5) is a STRATEGY-
# level candidate trading decision: it requires `strategy_id`,
# `strategy_version`, `theoretical_entry`, `theoretical_stop_loss`,
# `theoretical_targets`. This checkpoint's brief explicitly forbids
# inventing stop-loss/target/position-sizing values (§6) - and there is
# no strategy yet for a `strategy_id` to reference
# (`trading_engine/strategy_execution` does not exist as executable code
# until a later checkpoint; confirmed by this bounded context's own
# Checkpoint-1 README, which already named the FUTURE responsibility as
# "converts STRATEGY OUTPUT into canonical Signal objects" - depending on
# `domain/strategy`, not yet meaningful).
#
# Constructing a `domain.signal.Signal` today would therefore require
# fabricating a `strategy_id` and price levels this checkpoint has no
# authority to invent - exactly the kind of dishonest placeholder value
# this project has refused to produce at every prior checkpoint (e.g.
# Checkpoint 17's refusal to invent a previous-close for ATR's first
# bar). `DirectionalIndication` is a deliberately smaller, EARLIER-STAGE
# building block: "does the current feature state look bullish, bearish,
# or neutral?" - answerable purely from features, with no strategy
# attached yet. A future strategy/signal-verification layer will consume
# `DirectionalIndication`s (among other inputs) to eventually produce a
# real `domain.signal.Signal`.
#
# ---------------------------------------------------------------------------
# Why this lives here, not in domain/ (Checkpoint 18 §4)
# ---------------------------------------------------------------------------
#
# The project's own minimum-viable-shared-kernel rule (Checkpoint 2 §3.1,
# re-applied at every checkpoint since): a concept is added to `domain/`
# only when at least two bounded contexts need the IDENTICAL contract -
# never speculatively. Today, only `signal_intelligence/signal_generation`
# itself produces or consumes `DirectionalIndication` - no second bounded
# context (e.g. a future `research/backtesting` replay, or a future
# `signal_intelligence/signal_verification`) has a confirmed need for it
# yet. This exactly mirrors why `SimpleMovingAverageDefinition`/
# `ExponentialMovingAverageDefinition`/`AverageTrueRangeDefinition`
# (Checkpoints 15-17) live in `signal_intelligence/feature_engine`, not
# `domain/feature` - only `FeatureValue` itself (the genuinely
# cross-context OUTPUT, pre-approved at Checkpoint 5 for Rule 5.5 parity)
# lives in `domain/`. Promoting `DirectionalIndication` to `domain/signal`
# is a natural, deliberate future step once a second real consumer
# exists - not a decision to make speculatively now.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, Version, ensure_utc

# The signal-generation RULE's own name/version - identifies WHICH
# interpretation logic produced a `DirectionalIndication`, distinct from
# which SMA/EMA/ATR periods were used (that is already fully carried by
# each embedded `FeatureValue`'s own `feature_name`, e.g. "sma_20" - not
# duplicated here, following `FeatureValue`'s own precedent of flat
# `feature_name`/`feature_version` fields rather than a nested identity
# object).
DIRECTIONAL_INDICATION_DEFINITION_NAME = "sma_ema_atr_directional"
DIRECTIONAL_INDICATION_DEFINITION_VERSION = Version(value="v1")


class SignalDirection(enum.Enum):
    """Explicit three-state directional read (Checkpoint 18 §5) -
    deliberately NOT `domain.shared_kernel.Side` (BUY/SELL only, an
    order-facing two-state concept) and deliberately NOT a boolean
    `is_buy`/`is_sell` flag, which cannot represent "no clear directional
    condition" without an ambiguous sentinel."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True, slots=True)
class DirectionalIndication:
    """One directional read of the market at a single instant - NOT a
    trading signal in the `domain.signal.Signal` sense (see module
    docstring). Carries full provenance (Checkpoint 18 §12): the exact
    `FeatureValue`s that produced it are embedded directly, not just
    referenced by name, so the indication is independently reproducible
    and auditable without a second lookup.

    Identity (Checkpoint 18 §10) is structural, not a random UUID -
    `(definition_name, definition_version, instrument_id, timeframe,
    timestamp)` - mirroring `FeatureValue`'s own identity convention
    exactly, for the same reason: deterministic reproducibility. Two
    calls with identical inputs produce an identical
    `DirectionalIndication`.
    """

    definition_name: str
    definition_version: Version
    instrument_id: InstrumentId
    timeframe: Timeframe
    timestamp: datetime
    direction: SignalDirection
    price: Decimal
    sma: FeatureValue
    ema: FeatureValue
    atr: FeatureValue

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp, field_name="DirectionalIndication.timestamp")
        if not self.definition_name.strip():
            raise ValueError("DirectionalIndication.definition_name must be non-empty")
        if not isinstance(self.price, Decimal):
            raise TypeError("DirectionalIndication.price must be a Decimal")
        if self.price <= 0:
            raise ValueError("DirectionalIndication.price must be positive")
