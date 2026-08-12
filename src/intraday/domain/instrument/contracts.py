# File: src/intraday/domain/instrument/contracts.py
#
# Canonical instrument-identity contract (Checkpoint 5). Identifies a
# tradable (or reference-only) instrument in a broker-neutral,
# technology-neutral way — no Dhan terminology, tokens, or scrip codes
# appear here (Checkpoint 3 §6, Checkpoint 5 Section 8).
from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId


class InstrumentType(enum.Enum):
    """Deliberately minimal: EQUITY is the only tradable type. INDEX exists
    ONLY for market-context/regime-detection reference (Rule 2) and is
    never tradable — see `Instrument.is_tradable` below. No FUTURE/OPTION
    member exists anywhere in this enum, by design: the project is
    permanently scoped to Indian cash equities, intraday only (Checkpoint 1
    Section 2; re-validated at Checkpoint 5 Sections 20-21). Do not add a
    derivative instrument type here without an explicit, approved
    architecture change — none is anticipated.
    """

    EQUITY = "EQUITY"
    INDEX = "INDEX"  # reference/context only, e.g. NIFTY/SENSEX — never tradable


class TradingStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


@dataclass(frozen=True, slots=True)
class Instrument:
    """Canonical identity of a tradable (or reference) instrument.

    `instrument_id` is domain-owned and broker-neutral — derived from
    (exchange, symbol) via `make_instrument_id` below, never from a
    broker's internal token/scrip code. Broker-specific token mapping is
    an `infrastructure/brokers`/`infrastructure/market_data_providers`
    adapter concern (Checkpoint 3 TECHNOLOGY_MAPPING.md §6), not
    represented here.
    """

    instrument_id: InstrumentId
    symbol: str
    exchange: Exchange
    instrument_type: InstrumentType
    trading_status: TradingStatus
    price_tick_size: Decimal
    lot_size: int = 1

    def __post_init__(self) -> None:
        if not self.symbol or not self.symbol.strip():
            raise ValueError("Instrument.symbol must be non-empty")
        if not isinstance(self.price_tick_size, Decimal):
            raise TypeError("Instrument.price_tick_size must be a Decimal")
        if self.price_tick_size <= 0:
            raise ValueError("Instrument.price_tick_size must be positive")
        if self.lot_size <= 0:
            raise ValueError("Instrument.lot_size must be positive")

    @property
    def is_tradable(self) -> bool:
        """Only EQUITY instruments with ACTIVE status are tradable. INDEX
        instruments (e.g. NIFTY, SENSEX) are never tradable, regardless of
        status — this enforces Rule 2 structurally, not merely by
        convention or documentation."""
        return (
            self.instrument_type is InstrumentType.EQUITY
            and self.trading_status is TradingStatus.ACTIVE
        )


def make_instrument_id(exchange: Exchange, symbol: str) -> InstrumentId:
    """Deterministic instrument_id derivation, so the same (exchange,
    symbol) pair always produces the same domain identity regardless of
    which adapter or checkpoint constructs it."""
    return InstrumentId(f"{exchange.value}:{symbol.strip().upper()}")
