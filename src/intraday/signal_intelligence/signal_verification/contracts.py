# File: src/intraday/signal_intelligence/signal_verification/contracts.py
#
# Checkpoint 19: the output shape of the first Signal Verification rule
# - `VerificationResult`, evaluating a `DirectionalIndication`
# (Checkpoint 18) against actual subsequent price movement.
#
# ---------------------------------------------------------------------------
# Relationship to the bounded context's own Checkpoint-1 README
# ---------------------------------------------------------------------------
#
# `signal_intelligence/signal_verification/README.md` (Checkpoint 1)
# names this bounded context's FUTURE, full responsibility: "verifies
# realized signal outcomes against theoretical expectation... compares
# `domain/signal`'s original prediction against
# `signal_intelligence/theoretical_outcome`'s idealized MFE/MAE/
# conditional expectancy." That responsibility depends on `domain/signal`
# (the strategy-level `Signal`, still unbuilt - Checkpoint 18 explained
# why) AND on `theoretical_outcome` (MFE/MAE/path analysis - explicitly
# out of THIS checkpoint's scope per the brief, §14). Checkpoint 19 is
# therefore, like Checkpoint 18, an intentionally smaller, earlier-stage
# building block: does actual subsequent price movement SUPPORT the
# directional call a `DirectionalIndication` already made? No MFE/MAE,
# no path analysis, no strategy - a single, deterministic, single-point
# price comparison.
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

# The verification RULE's own name/version - distinct from
# `DirectionalIndication`'s own `definition_name`/`definition_version`
# (which identifies the RULE THAT PRODUCED the indication, not the rule
# that evaluates it afterward). Follows the exact same flat
# name+`Version` convention as `FeatureValue`/`DirectionalIndication`.
VERIFICATION_DEFINITION_NAME = "single_point_price_movement"
VERIFICATION_DEFINITION_VERSION = Version(value="v1")


class VerificationOutcome(enum.Enum):
    """Whether subsequent price movement supported the directional call
    a `DirectionalIndication` made (Checkpoint 19 §4) - deliberately NOT
    BUY/SELL/PROFIT/LOSS, which belong to future strategy/execution
    semantics, not an observation-only verification result."""

    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """The outcome of evaluating one `DirectionalIndication` against a
    single future observation, `horizon_bars` bars after the signal.

    Carries full provenance (Checkpoint 19 §17): the entire source
    `indication` is embedded directly (which itself embeds its own
    SMA/EMA/ATR `FeatureValue`s - Checkpoint 18), so a `VerificationResult`
    is independently reproducible and auditable without a second lookup.

    Identity (Checkpoint 19 §16) is structural, not a random UUID -
    `(verification_definition_name, verification_definition_version,
    instrument_id, timeframe, signal_timestamp, horizon_bars)` - the
    same convention `FeatureValue`/`DirectionalIndication` already
    established.
    """

    verification_definition_name: str
    verification_definition_version: Version
    instrument_id: InstrumentId
    timeframe: Timeframe
    signal_timestamp: datetime
    horizon_bars: int
    direction: SignalDirection
    reference_price: Decimal
    observed_price: Decimal | None
    evaluation_timestamp: datetime | None
    outcome: VerificationOutcome
    indication: DirectionalIndication

    def __post_init__(self) -> None:
        ensure_utc(self.signal_timestamp, field_name="VerificationResult.signal_timestamp")
        if self.evaluation_timestamp is not None:
            ensure_utc(
                self.evaluation_timestamp, field_name="VerificationResult.evaluation_timestamp"
            )
        if not self.verification_definition_name.strip():
            raise ValueError("VerificationResult.verification_definition_name must be non-empty")
        if self.horizon_bars <= 0:
            raise ValueError("VerificationResult.horizon_bars must be positive")
        if not isinstance(self.reference_price, Decimal):
            raise TypeError("VerificationResult.reference_price must be a Decimal")
        if self.reference_price <= 0:
            raise ValueError("VerificationResult.reference_price must be positive")
        if self.observed_price is not None and not isinstance(self.observed_price, Decimal):
            raise TypeError("VerificationResult.observed_price must be a Decimal when provided")
        if self.observed_price is not None and self.observed_price <= 0:
            raise ValueError("VerificationResult.observed_price must be positive when provided")
        # INCONCLUSIVE is the only outcome allowed without an observed
        # price/evaluation timestamp - SUPPORTED/NOT_SUPPORTED always
        # come from a real, completed observation.
        if self.outcome is not VerificationOutcome.INCONCLUSIVE and (
            self.observed_price is None or self.evaluation_timestamp is None
        ):
            raise ValueError(
                "VerificationResult.observed_price and evaluation_timestamp are "
                "required unless outcome is INCONCLUSIVE"
            )
