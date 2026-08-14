# File: src/intraday/signal_intelligence/theoretical_outcome/contracts.py
#
# Checkpoint 21: the output shape of the first Theoretical Outcome rule
# - `TheoreticalOutcome`, measuring the maximum favorable/adverse price
# excursion (MFE/MAE) a `DirectionalIndication` (Checkpoint 18)
# experienced over an explicit future observation window.
#
# ---------------------------------------------------------------------------
# What this answers, and what it deliberately does NOT (Checkpoint 21 §1, §3)
# ---------------------------------------------------------------------------
#
#     THEORETICAL OUTCOME = what price objectively did
#     STRATEGY             = what a trader decides to do about it
#
# This contract reports MFE/MAE - objective price-path measurements -
# and never a profitability/win/loss/target-hit/stop-hit claim. No
# entry rule, stop-loss rule, target rule, position size, order
# execution, or expectancy calculation exists anywhere in this bounded
# context (Checkpoint 21 §20, §30 - conditional expectancy explicitly
# deferred, see the architecture doc's own section on why).
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, Version, ensure_utc
from intraday.signal_intelligence.signal_generation.contracts import (
    DirectionalIndication,
    SignalDirection,
)

# The outcome-measurement RULE's own name/version - distinct from
# `DirectionalIndication`'s and `VerificationResult`'s own definition
# fields (each bounded context's rule is independently named/versioned).
# Same flat name+`Version` convention as every other contract in this
# codebase.
OUTCOME_DEFINITION_NAME = "mfe_mae_price_excursion"
OUTCOME_DEFINITION_VERSION = Version(value="v1")


class ObservationCompleteness(enum.Enum):
    """How much of the requested `horizon_bars` observation window was
    actually available (Checkpoint 21 §14-15) - orthogonal to whether
    MFE/MAE could be computed at all (see `TheoreticalOutcome.mfe`/`mae`
    being `None` for NEUTRAL indications, a separate concept from data
    availability)."""

    COMPLETE = "COMPLETE"  # exactly (or more than) horizon_bars future bars were available
    PARTIAL = "PARTIAL"  # 1..horizon_bars-1 future bars were available
    NO_DATA = "NO_DATA"  # zero future bars were available


@dataclass(frozen=True, slots=True)
class TheoreticalOutcome:
    """The MFE/MAE measurement for one `DirectionalIndication` over
    `horizon_bars` future bars.

    `mfe`/`mae` are `None` exactly when `direction is SignalDirection.NEUTRAL`
    (Checkpoint 21 §13 - a NEUTRAL indication made no directional
    prediction, so "favorable"/"adverse" are not defined concepts for
    it - never silently reported as `0`, which would be a real,
    different measurement). They are also `None` when
    `completeness is ObservationCompleteness.NO_DATA` (Checkpoint 21
    §14 - missing data must remain distinguishable from a genuine zero
    excursion).

    Carries full provenance: the entire source `indication` is embedded
    directly, mirroring `VerificationResult`/`SignalLifecycle`'s own
    convention.

    Identity (Checkpoint 21 §23) is structural - `(outcome_definition_name,
    outcome_definition_version, instrument_id, timeframe, signal_timestamp,
    horizon_bars)` - the same convention every prior signal-intelligence
    contract in this codebase already established. No random UUID.
    """

    outcome_definition_name: str
    outcome_definition_version: Version
    instrument_id: InstrumentId
    timeframe: Timeframe
    signal_timestamp: datetime
    horizon_bars: int
    direction: SignalDirection
    reference_price: Decimal
    mfe: Decimal | None
    mae: Decimal | None
    bars_observed: int
    completeness: ObservationCompleteness
    indication: DirectionalIndication

    def __post_init__(self) -> None:
        ensure_utc(self.signal_timestamp, field_name="TheoreticalOutcome.signal_timestamp")
        if not self.outcome_definition_name.strip():
            raise ValueError("TheoreticalOutcome.outcome_definition_name must be non-empty")
        if self.horizon_bars <= 0:
            raise ValueError("TheoreticalOutcome.horizon_bars must be positive")
        if not isinstance(self.reference_price, Decimal):
            raise TypeError("TheoreticalOutcome.reference_price must be a Decimal")
        if self.reference_price <= 0:
            raise ValueError("TheoreticalOutcome.reference_price must be positive")
        if self.bars_observed < 0:
            raise ValueError("TheoreticalOutcome.bars_observed must not be negative")
        if self.mfe is not None and not isinstance(self.mfe, Decimal):
            raise TypeError("TheoreticalOutcome.mfe must be a Decimal when provided")
        if self.mae is not None and not isinstance(self.mae, Decimal):
            raise TypeError("TheoreticalOutcome.mae must be a Decimal when provided")
        if self.mfe is not None and self.mfe < 0:
            raise ValueError("TheoreticalOutcome.mfe must never be negative")
        if self.mae is not None and self.mae > 0:
            raise ValueError("TheoreticalOutcome.mae must never be positive")
        if self.completeness is ObservationCompleteness.NO_DATA and (
            self.mfe is not None or self.mae is not None
        ):
            raise ValueError("TheoreticalOutcome.mfe/mae must be None when completeness is NO_DATA")
