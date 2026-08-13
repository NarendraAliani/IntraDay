# File: src/intraday/signal_intelligence/feature_engine/errors.py
#
# Checkpoint 15: feature-computation error types. Kept in the bounded
# context (not `domain/`) since they describe a computation-input
# violation, not a value-object construction violation — the same
# distinction `domain/market_data/quality.py`'s errors draw for bar
# *series* rules vs. `Bar.__post_init__`'s own single-bar rules.
from __future__ import annotations


class InvalidLookbackError(ValueError):
    """Raised when a feature's lookback period is not a positive integer."""


class MixedInstrumentSeriesError(ValueError):
    """Raised when a bar series passed to a feature computation contains
    bars from more than one instrument — a feature series must remain
    tied to the single instrument its input came from (Checkpoint 15
    §12)."""


class MixedTimeframeSeriesError(ValueError):
    """Raised when a bar series passed to a feature computation mixes
    more than one timeframe — a feature calculation must never silently
    blend, e.g., 1-minute and 5-minute bars (Checkpoint 15 §11)."""
