# File: src/intraday/domain/portfolio/contracts.py
#
# Canonical portfolio/account-exposure contracts (Checkpoint 5). Needed
# identically by live portfolio_management and backtest P&L simulation
# (Checkpoint 2 shared-kernel justification) — broker-neutral, no
# broker-specific account fields. No account synchronization or broker
# position-fetching is implemented here (Checkpoint 5 Section 14).
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import InstrumentId, Side, ensure_utc


@dataclass(frozen=True, slots=True)
class ExposureEntry:
    """Current exposure to one instrument within a portfolio snapshot."""

    instrument_id: InstrumentId
    direction: Side
    quantity: Decimal
    average_price: Decimal

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("ExposureEntry.quantity must be positive")
        if self.average_price <= 0:
            raise ValueError("ExposureEntry.average_price must be positive")


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """A point-in-time view of aggregate intraday exposure across
    instruments. Intraday only — there is no concept of exposure carried
    forward across sessions (Rule 5.4); a new session starts with an empty
    snapshot."""

    as_of: datetime
    exposures: tuple[ExposureEntry, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        ensure_utc(self.as_of, field_name="PortfolioSnapshot.as_of")
        seen: set[InstrumentId] = set()
        for exposure in self.exposures:
            if exposure.instrument_id in seen:
                raise ValueError(
                    "PortfolioSnapshot.exposures contains a duplicate instrument_id: "
                    f"{exposure.instrument_id}"
                )
            seen.add(exposure.instrument_id)

    @property
    def gross_exposure(self) -> Decimal:
        """Sum of quantity * average_price across all entries, regardless
        of direction — a simple aggregate, not a risk calculation."""
        total = Decimal("0")
        for exposure in self.exposures:
            total += exposure.quantity * exposure.average_price
        return total
