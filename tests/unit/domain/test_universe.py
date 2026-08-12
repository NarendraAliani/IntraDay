# tests/unit/domain/test_universe.py
#
# Unit tests for the Universe contract (Checkpoint 5).
from __future__ import annotations

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Version
from intraday.domain.universe.contracts import Universe, UniverseMember, UniverseMembershipStatus

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")


def test_universe_contains_included_member() -> None:
    universe = Universe(
        universe_id="nifty50",
        version=Version(value="v1"),
        exchange=Exchange.NSE,
        members=(UniverseMember(RELIANCE, UniverseMembershipStatus.INCLUDED),),
    )
    assert universe.contains(RELIANCE) is True
    assert universe.contains(TCS) is False


def test_universe_excluded_member_is_not_contained() -> None:
    universe = Universe(
        universe_id="nifty50",
        version=Version(value="v1"),
        exchange=Exchange.NSE,
        members=(UniverseMember(RELIANCE, UniverseMembershipStatus.EXCLUDED),),
    )
    assert universe.contains(RELIANCE) is False


def test_universe_rejects_duplicate_members() -> None:
    with pytest.raises(ValueError):
        Universe(
            universe_id="nifty50",
            version=Version(value="v1"),
            exchange=Exchange.NSE,
            members=(
                UniverseMember(RELIANCE, UniverseMembershipStatus.INCLUDED),
                UniverseMember(RELIANCE, UniverseMembershipStatus.EXCLUDED),
            ),
        )


def test_universe_rejects_empty_id() -> None:
    with pytest.raises(ValueError):
        Universe(universe_id="  ", version=Version(value="v1"), exchange=Exchange.NSE)
