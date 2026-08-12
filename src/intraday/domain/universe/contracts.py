# File: src/intraday/domain/universe/contracts.py
#
# Canonical tradable-universe contract (Checkpoint 5). Represents an
# already-decided, versioned membership list — screening/selection
# ALGORITHMS that decide membership are explicitly out of scope here
# (Checkpoint 5 Section 9) and belong to a later research checkpoint.
from __future__ import annotations

import enum
from dataclasses import dataclass, field

from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Version


class UniverseMembershipStatus(enum.Enum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


@dataclass(frozen=True, slots=True)
class UniverseMember:
    instrument_id: InstrumentId
    status: UniverseMembershipStatus


@dataclass(frozen=True, slots=True)
class Universe:
    """A versioned, point-in-time definition of the tradable universe.

    Consumed identically by research (backtest universe selection) and
    trading_engine (live eligibility checks at the risk chokepoint) — this
    is Checkpoint 2's shared-kernel justification for keeping `universe` in
    `domain/` rather than inside a single bounded context: both live and
    backtest code must agree on exactly which instruments were tradable at
    a given `version` (Rule 5.5 parity).
    """

    universe_id: str
    version: Version
    exchange: Exchange
    members: tuple[UniverseMember, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.universe_id.strip():
            raise ValueError("Universe.universe_id must be non-empty")
        seen: set[InstrumentId] = set()
        for member in self.members:
            if member.instrument_id in seen:
                raise ValueError(
                    f"Universe.members contains a duplicate instrument_id: {member.instrument_id}"
                )
            seen.add(member.instrument_id)

    def contains(self, instrument_id: InstrumentId) -> bool:
        """True only if the instrument is an explicit, INCLUDED member of
        this universe version — absence is always treated as excluded."""
        return any(
            member.instrument_id == instrument_id
            and member.status is UniverseMembershipStatus.INCLUDED
            for member in self.members
        )
