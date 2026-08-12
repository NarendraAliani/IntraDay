# File: src/intraday/domain/shared_kernel/contracts.py
#
# Shared-kernel value objects and primitives (Checkpoint 5). These are the
# ONLY primitives referenced by two or more bounded contexts, per the
# minimum-viable-shared-kernel rule established at Checkpoint 2/3 (see
# docs/architecture/DOMAIN_BOUNDARIES.md "Minimum Viable Shared Kernel").
# Every value object here is technology-neutral, immutable, Decimal-based
# where money/quantity is involved, and UTC-enforced where time is
# involved. This module imports nothing outside the Python standard
# library, per Checkpoint 5 Section 4.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import NewType

# --- Identifiers -------------------------------------------------------------
# Plain str-based identifiers rather than opaque UUIDs: most identities in
# this domain are naturally derivable/human-legible (e.g. an instrument_id
# derived deterministically from exchange+symbol, a strategy_id as a slug)
# rather than surrogate keys with no independent meaning. Adopting UUID
# everywhere would be implementation convenience, not a domain requirement.
InstrumentId = NewType("InstrumentId", str)
StrategyId = NewType("StrategyId", str)
SignalId = NewType("SignalId", str)
OrderId = NewType("OrderId", str)
PositionId = NewType("PositionId", str)
TradeId = NewType("TradeId", str)


@dataclass(frozen=True, slots=True)
class Version:
    """Generic version/lineage identifier.

    Added to the shared kernel at Checkpoint 3 in place of a full
    `domain/experiment` contract: only a version *stamp* — not the full
    Experiment aggregate — is needed by two or more bounded contexts
    (e.g. `StrategyVersion` below, and `research/experiments`'s lineage
    fields). Deliberately opaque: callers supply whatever versioning
    scheme they use (semver string, git SHA, ISO timestamp, incrementing
    integer as a string) — this contract does not prescribe one.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValueError("Version.value must be a non-empty string")


class Exchange(enum.Enum):
    """Indian cash-equity exchanges this platform trades on (Rule 2: the
    project's scope is permanently Indian cash equities only)."""

    NSE = "NSE"
    BSE = "BSE"


class Side(enum.Enum):
    """Buy/sell direction, shared verbatim by Signal, Order, and Position —
    the same two-value vocabulary must mean the same thing at every point
    across the risk chokepoint (Checkpoint 2 Signal/Order/Position/Trade
    model, Rule 5.2)."""

    BUY = "BUY"
    SELL = "SELL"


class Timeframe(enum.Enum):
    """Canonical intraday timeframes used across market data, features, and
    signals — a shared vocabulary so "a 5-minute bar" means the same thing
    in research, signal_intelligence, and trading_engine alike (Rule 5.5
    parity). No timeframe longer than one trading day exists here, by
    design — this project is intraday-only (Rule 5.4)."""

    TICK = "TICK"
    ONE_MINUTE = "1m"
    THREE_MINUTE = "3m"
    FIVE_MINUTE = "5m"
    FIFTEEN_MINUTE = "15m"
    THIRTY_MINUTE = "30m"
    ONE_HOUR = "1h"
    DAY = "1d"


@dataclass(frozen=True, slots=True)
class Price:
    """A price in INR, represented as an exact `Decimal` — never `float`,
    per Checkpoint 3 §18 (financial precision standards). This value
    object exists for the (currently few) call sites that want a
    self-validating price wrapper rather than a bare `Decimal` field;
    most contracts below use bare `Decimal` fields directly for
    simplicity, validated in each contract's own `__post_init__`.
    """

    amount: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("Price.amount must be a Decimal, not float or int")
        if self.amount < 0:
            raise ValueError(f"Price.amount must not be negative, got {self.amount}")


@dataclass(frozen=True, slots=True)
class Quantity:
    """A tradable quantity, `Decimal`-based to allow fractional quantities
    should a future instrument type require them, even though whole-share
    cash-equity trades are the norm today. See `Price` above regarding
    when this wrapper vs. a bare `Decimal` field is used."""

    amount: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("Quantity.amount must be a Decimal, not float or int")
        if self.amount <= 0:
            raise ValueError(f"Quantity.amount must be positive, got {self.amount}")


def ensure_utc(value: datetime, *, field_name: str = "timestamp") -> datetime:
    """Enforce the canonical time architecture (Checkpoint 3 §19): every
    domain timestamp must be timezone-aware and in UTC. Naive datetimes or
    non-UTC offsets are rejected outright rather than silently converted,
    forcing the UTC conversion to happen explicitly at the ingestion
    boundary (infrastructure/market_data_providers, infrastructure/brokers)
    where it belongs — the domain layer must never guess a timezone.
    """
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware (got a naive datetime)")
    if value.utcoffset() != UTC.utcoffset(None):
        raise ValueError(f"{field_name} must be in UTC (got offset {value.utcoffset()})")
    return value
