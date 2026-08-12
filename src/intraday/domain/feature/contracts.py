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
