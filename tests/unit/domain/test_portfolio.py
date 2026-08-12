# tests/unit/domain/test_portfolio.py
#
# Unit tests for the ExposureEntry/PortfolioSnapshot contracts (Checkpoint 5).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.portfolio.contracts import ExposureEntry, PortfolioSnapshot
from intraday.domain.shared_kernel.contracts import Exchange, Side

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


def test_gross_exposure_sums_all_entries() -> None:
    snapshot = PortfolioSnapshot(
        as_of=NOW,
        exposures=(
            ExposureEntry(RELIANCE, Side.BUY, Decimal("10"), Decimal("100")),
            ExposureEntry(TCS, Side.SELL, Decimal("5"), Decimal("200")),
        ),
    )
    assert snapshot.gross_exposure == Decimal("2000")


def test_duplicate_instrument_in_snapshot_is_rejected() -> None:
    with pytest.raises(ValueError):
        PortfolioSnapshot(
            as_of=NOW,
            exposures=(
                ExposureEntry(RELIANCE, Side.BUY, Decimal("10"), Decimal("100")),
                ExposureEntry(RELIANCE, Side.SELL, Decimal("5"), Decimal("100")),
            ),
        )


def test_exposure_entry_rejects_non_positive_quantity() -> None:
    with pytest.raises(ValueError):
        ExposureEntry(RELIANCE, Side.BUY, Decimal("0"), Decimal("100"))
