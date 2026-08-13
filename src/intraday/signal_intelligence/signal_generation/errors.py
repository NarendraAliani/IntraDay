# File: src/intraday/signal_intelligence/signal_generation/errors.py
#
# Checkpoint 18: signal-generation input-validation error types. Kept in
# the bounded context (not `domain/`), mirroring
# `signal_intelligence/feature_engine/errors.py`'s own precedent — these
# describe a computation-input violation, not a value-object construction
# violation.
from __future__ import annotations


class MisalignedFeatureInstrumentError(ValueError):
    """Raised when the price bar and the SMA/EMA/ATR feature values
    passed to `generate_directional_indication` do not all belong to the
    same instrument."""


class MisalignedFeatureTimeframeError(ValueError):
    """Raised when the price bar and the SMA/EMA/ATR feature values do
    not all share the same timeframe."""


class MisalignedFeatureTimestampError(ValueError):
    """Raised when the price bar and the SMA/EMA/ATR feature values do
    not all share the same observation timestamp — the core temporal-
    alignment rule (Checkpoint 18 §8): a directional indication may only
    be formed from feature values that describe the exact same instant,
    never a mix of "the latest SMA we happen to have" and "the latest EMA
    we happen to have" at possibly different times."""


class WrongFeatureTypeError(ValueError):
    """Raised when a `FeatureValue` passed in the `sma`/`ema`/`atr`
    parameter slot does not actually look like that feature (its
    `feature_name` does not start with the expected prefix, e.g. an EMA
    value passed where an SMA value was expected). Defense in depth,
    mirroring the same category of check `feature_engine`'s own
    computations perform for instrument/timeframe consistency."""


class InvalidAtrValueError(ValueError):
    """Raised when the supplied ATR `FeatureValue.value` is negative — a
    True-Range-derived average can never legitimately be negative
    (Checkpoint 18 §17); a negative value indicates the caller passed a
    corrupted or wrong feature value, not a legitimate market state."""


class DuplicateFeatureObservationError(ValueError):
    """Raised when a feature series passed to
    `generate_directional_indications` contains two values with the same
    timestamp — silently keeping "whichever one happened to come last"
    would be exactly the silent-data-loss this project's series-
    validation functions (e.g. `ensure_chronological`) refuse to do."""


class OutOfOrderFeatureObservationError(ValueError):
    """Raised when a feature series passed to
    `generate_directional_indications` is not strictly increasing by
    timestamp."""
