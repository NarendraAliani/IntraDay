# File: src/intraday/domain/feature/contracts.py
#
# Canonical calculated-feature contract (Checkpoint 5). Represents the
# OUTPUT of a feature computation — never the computation itself. No
# indicator math (EMA, MACD, Bollinger Bands, ATR, VWAP, Supertrend, RSI,
# etc.) exists anywhere in this file or this checkpoint (Checkpoint 5
# Section 10); that belongs to signal_intelligence/feature_engine in a
# later checkpoint.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, Version, ensure_utc


@dataclass(frozen=True, slots=True)
class FeatureValue:
    """A single computed feature value at one instant.

    `feature_name` + `feature_version` together identify *what* was
    computed (e.g. name "ema_20", version "v1") — this contract does not
    know or care *how* it was computed. Consumed identically by
    `signal_intelligence` (live) and `research` (offline/backtest), which
    is why it lives in the shared kernel rather than either bounded
    context alone (Rule 5.5 parity).
    """

    feature_name: str
    feature_version: Version
    instrument_id: InstrumentId
    timeframe: Timeframe
    timestamp: datetime
    value: Decimal

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp, field_name="FeatureValue.timestamp")
        if not self.feature_name.strip():
            raise ValueError("FeatureValue.feature_name must be non-empty")
        if not isinstance(self.value, Decimal):
            raise TypeError("FeatureValue.value must be a Decimal")


# ---------------------------------------------------------------------------
# Checkpoint 65.07 addition - CategoricalFeatureValue.
#
# 65.06 established (and correctly stopped on) a genuine architectural gap:
# `FeatureValue.value` is Decimal-only, and no categorical/enum feature
# precedent exists anywhere in the platform. This is the SMALLEST SAFE
# extension that gives a categorical state (e.g. a future market_regime)
# a correct, type-safe home - WITHOUT touching `FeatureValue` above at all
# and WITHOUT forcing categorical semantics into arbitrary numeric ranking
# (Decimal category codes were explicitly rejected - see taskReport.md's
# Checkpoint 65.07 "Architecture Options Evaluated" section).
#
# `CategoricalFeatureValue` is a SIBLING type, not a subclass and not a
# variant field on `FeatureValue` - Part C of the 65.07 directive requires
# the existing `FeatureValue.value: Decimal` contract to remain exactly as
# type-safe as it was; a sibling dataclass is the only option that adds a
# categorical representation without widening `FeatureValue.value` to
# `Decimal | str` or `Any`.
#
# Shared provenance (Part D): `feature_name`, `feature_version`,
# `instrument_id`, `timeframe`, `timestamp` are IDENTICAL in name and type
# to `FeatureValue`'s own fields - a categorical feature is exactly as
# traceable through the platform as a numeric one. Only the value slot
# differs: `value: Decimal` here becomes `category: str`.
#
# Categorical value representation (Part E): `category` is validated as a
# non-empty, stripped string here - the same minimal discipline
# `FeatureValue.feature_name` already applies. A CLOSED VOCABULARY (e.g. an
# enum of BULL/BEAR/SIDEWAYS for a future `market_regime`) is intentionally
# NOT enforced at this generic contract level - that enforcement belongs to
# whichever concrete categorical feature's OWN definition/compute module
# validates its specific vocabulary (the same layering `FeatureValue`
# itself already uses: this contract doesn't know the valid *range* of a
# numeric feature either, e.g. RSI's [0, 100], each feature module owns
# that). Building a generic "CategoricalFeatureRegistry"/vocabulary-
# enforcement engine here would be exactly the over-generalization Part E
# forbids for a checkpoint whose only job is proving the contract shape.
#
# Unavailable semantics (Part F): there is no "UNAVAILABLE" category and no
# sentinel value on this type. The existing feature-engine convention
# (see e.g. `relative_volume.py`/`rebound_candidate.py`) is "no output at
# that timestamp" - a feature with no value simply produces no
# `FeatureValue`/`CategoricalFeatureValue` for that timestamp, rather than
# a synthetic "missing" state living inside the value itself. That
# convention is followed here unchanged - not reinvented.
@dataclass(frozen=True, slots=True)
class CategoricalFeatureValue:
    """A single computed CATEGORICAL feature value at one instant - the
    categorical sibling of `FeatureValue`. See the Checkpoint 65.07 module
    comment above for the full design rationale (why a sibling type, why
    `category: str` rather than a Decimal code, why no vocabulary
    enforcement lives here, why there is no distinct "unavailable"
    category).

    Carries the SAME provenance fields as `FeatureValue`
    (`feature_name`/`feature_version`/`instrument_id`/`timeframe`/
    `timestamp`) so categorical and numeric features remain equally
    traceable. `category` is the categorical output itself - e.g. a
    future `market_regime` feature's "BULL"/"BEAR"/"SIDEWAYS" (NOT
    implemented or registered this checkpoint - see taskReport.md).

    Deliberately NOT interchangeable with `FeatureValue`: no shared base
    class, no `value` field, no implicit conversion. A consumer that wants
    to accept either must do so explicitly (e.g. `isinstance` or a
    `FeatureValue | CategoricalFeatureValue` union), never by duck-typing
    a common `.value` attribute the two types do not share.
    """

    feature_name: str
    feature_version: Version
    instrument_id: InstrumentId
    timeframe: Timeframe
    timestamp: datetime
    category: str

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp, field_name="CategoricalFeatureValue.timestamp")
        if not self.feature_name.strip():
            raise ValueError("CategoricalFeatureValue.feature_name must be non-empty")
        if not isinstance(self.category, str):
            raise TypeError("CategoricalFeatureValue.category must be a str")
        if not self.category.strip():
            raise ValueError("CategoricalFeatureValue.category must be non-empty")


# Union of both feature-output shapes - the type a generic consumer (e.g.
# the strategy-execution dispatcher's return type) can widen to without
# collapsing either member's own type safety. Introduced for Part H
# (dispatcher infrastructure) - no dispatch logic for any categorical
# feature is added this checkpoint; this is purely the type-level seam a
# future categorical feature's dispatch branch will return through.
AnyFeatureValue = FeatureValue | CategoricalFeatureValue
