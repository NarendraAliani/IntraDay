# File: src/intraday/domain/market_data/contracts.py
#
# Canonical market-data contracts (Checkpoint 5): Bar and Quote. Shared
# identically across backtest, paper, and live per Rule 5.5 — no provider-
# or broker-specific fields exist here. No provider adapter, WebSocket
# ingestion, or Dhan market-data call is implemented at this checkpoint
# (Checkpoint 5 Section 7).
#
# Checkpoint 14 extends `Bar` with `adjustment` (raw vs. corporate-action-
# adjusted prices — see `PriceAdjustment` below) — a genuine, justified
# extension of a locked Checkpoint 5 contract (same precedent as
# Checkpoint 7 extending `RiskLimits`): every bar's prices ARE either raw
# or adjusted, so this is a property of the bar itself, not a wrapper
# concern layered on top by application/infrastructure. No corporate-
# action ADJUSTMENT ENGINE is introduced — only the explicit label a
# future one will need to set correctly (Checkpoint 14 §10).
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, ensure_utc


class MarketDataQuality(enum.Enum):
    """Data-quality flag, allowing `control_plane/market_data_health` (a
    later checkpoint) to distinguish trustworthy data from stale/suspect
    data without silently dropping it at the domain boundary."""

    OK = "OK"
    STALE = "STALE"
    SUSPECT = "SUSPECT"


class PriceAdjustment(enum.Enum):
    """Whether a Bar's OHLC prices are exchange-raw or corporate-action-
    adjusted (splits/bonuses/dividends). Checkpoint 14 §10: prices are
    NEVER silently adjusted — this label must be set explicitly and
    truthfully by whatever produced the bar (a provider adapter for RAW,
    a future corporate-action processor for ADJUSTED). No adjustment
    computation exists anywhere in this codebase yet; `ADJUSTED` is not
    reachable until that future component exists and sets it."""

    RAW = "RAW"
    ADJUSTED = "ADJUSTED"


@dataclass(frozen=True, slots=True)
class Bar:
    """A single OHLCV bar for one instrument, one timeframe, one instant.

    This is the canonical shape both `data/historical_data` (durable
    archive) and `data/market_data` (live) instances share — only their
    storage lifecycle differs (Checkpoint 2 §6 data-ownership model),
    never this schema.

    `timestamp` is the bar's CLOSE time, UTC (Checkpoint 5's own original
    decision, re-confirmed at Checkpoint 14 §6 rather than left
    ambiguous): a 09:15-09:20 IST five-minute bar is stamped 09:20 IST
    (03:50 UTC), matching how OHLCV data is conventionally reported by
    Indian market-data vendors and how a strategy consuming "the bar that
    just closed" naturally reasons about it — the bar is not actionable
    until its close instant. `ensure_utc` (shared_kernel) enforces that no
    naive or non-UTC datetime can reach this field; IST wall-clock
    conversion happens only at the presentation boundary, never here.
    """

    instrument_id: InstrumentId
    timeframe: Timeframe
    timestamp: datetime  # bar close time, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quality: MarketDataQuality = MarketDataQuality.OK
    adjustment: PriceAdjustment = PriceAdjustment.RAW

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp, field_name="Bar.timestamp")
        for field_name, value in (
            ("open", self.open),
            ("high", self.high),
            ("low", self.low),
            ("close", self.close),
        ):
            if not isinstance(value, Decimal):
                raise TypeError(f"Bar.{field_name} must be a Decimal")
            if value <= 0:
                raise ValueError(f"Bar.{field_name} must be positive, got {value}")
        if self.volume < 0:
            raise ValueError(f"Bar.volume must not be negative, got {self.volume}")
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError(
                "Bar OHLC values are inconsistent: open and close must lie within [low, high]"
            )


@dataclass(frozen=True, slots=True)
class Quote:
    """A point-in-time tick/quote snapshot. `bid`/`ask` are optional
    because not every provider supplies full depth — `last_price` is the
    only mandatory price field."""

    instrument_id: InstrumentId
    timestamp: datetime
    last_price: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_quantity: Decimal | None = None
    ask_quantity: Decimal | None = None
    source: str = ""
    quality: MarketDataQuality = MarketDataQuality.OK

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp, field_name="Quote.timestamp")
        if self.last_price <= 0:
            raise ValueError("Quote.last_price must be positive")
        if self.bid is not None and self.bid <= 0:
            raise ValueError("Quote.bid must be positive when provided")
        if self.ask is not None and self.ask <= 0:
            raise ValueError("Quote.ask must be positive when provided")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("Quote.bid must not exceed Quote.ask")
