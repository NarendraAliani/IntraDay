# File: src/intraday/infrastructure/market_data_providers/fixtures.py
#
# Checkpoint 14: a deterministic, in-memory implementation of
# `application.repositories.HistoricalMarketDataRepository` — no live
# provider, no network call, no credentials, no Dhan SDK. Exists so the
# application layer (and any future consumer) can be exercised end-to-end
# against a real Protocol implementation without coupling this
# checkpoint's tests to external availability (Checkpoint 14 §14: "a
# fixture adapter is acceptable and preferable to coupling the checkpoint
# to external availability").
#
# The bars below are HAND-AUTHORED, deterministic, and synthetic — they
# are not real market data for any real instrument. `FIXTURE01` is a
# deliberately fictitious symbol so nobody mistakes this for real
# RELIANCE/TCS/etc. price history.
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe

SYNTHETIC_INSTRUMENT_ID: InstrumentId = make_instrument_id(Exchange.NSE, "FIXTURE01")

# Eight consecutive 5-minute bars covering 09:20-09:55 IST (03:50-04:25 UTC)
# on a synthetic session date — the first 40 minutes of a trading session,
# deliberately NOT the full day, so a `HistoricalMarketDataService.
# completeness()` check against a full-day session has real, non-empty
# missing intervals to report (see the application-service tests).
_FIXTURE_BARS: tuple[Bar, ...] = (
    Bar(
        instrument_id=SYNTHETIC_INSTRUMENT_ID,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=datetime(2026, 1, 2, 3, 50, tzinfo=UTC),
        open=Decimal("100.00"),
        high=Decimal("100.75"),
        low=Decimal("99.80"),
        close=Decimal("100.50"),
        volume=Decimal("12000"),
    ),
    Bar(
        instrument_id=SYNTHETIC_INSTRUMENT_ID,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=datetime(2026, 1, 2, 3, 55, tzinfo=UTC),
        open=Decimal("100.50"),
        high=Decimal("101.20"),
        low=Decimal("100.30"),
        close=Decimal("101.00"),
        volume=Decimal("11500"),
    ),
    Bar(
        instrument_id=SYNTHETIC_INSTRUMENT_ID,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=datetime(2026, 1, 2, 4, 0, tzinfo=UTC),
        open=Decimal("101.00"),
        high=Decimal("101.60"),
        low=Decimal("100.75"),
        close=Decimal("101.40"),
        volume=Decimal("10800"),
    ),
    Bar(
        instrument_id=SYNTHETIC_INSTRUMENT_ID,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=datetime(2026, 1, 2, 4, 5, tzinfo=UTC),
        open=Decimal("101.40"),
        high=Decimal("101.90"),
        low=Decimal("101.10"),
        close=Decimal("101.75"),
        volume=Decimal("9800"),
    ),
    Bar(
        instrument_id=SYNTHETIC_INSTRUMENT_ID,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=datetime(2026, 1, 2, 4, 10, tzinfo=UTC),
        open=Decimal("101.75"),
        high=Decimal("102.30"),
        low=Decimal("101.50"),
        close=Decimal("102.10"),
        volume=Decimal("10200"),
    ),
    Bar(
        instrument_id=SYNTHETIC_INSTRUMENT_ID,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=datetime(2026, 1, 2, 4, 15, tzinfo=UTC),
        open=Decimal("102.10"),
        high=Decimal("102.50"),
        low=Decimal("101.80"),
        close=Decimal("102.00"),
        volume=Decimal("9500"),
    ),
    Bar(
        instrument_id=SYNTHETIC_INSTRUMENT_ID,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=datetime(2026, 1, 2, 4, 20, tzinfo=UTC),
        open=Decimal("102.00"),
        high=Decimal("102.40"),
        low=Decimal("101.60"),
        close=Decimal("101.90"),
        volume=Decimal("8700"),
    ),
    Bar(
        instrument_id=SYNTHETIC_INSTRUMENT_ID,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=datetime(2026, 1, 2, 4, 25, tzinfo=UTC),
        open=Decimal("101.90"),
        high=Decimal("102.20"),
        low=Decimal("101.40"),
        close=Decimal("101.70"),
        volume=Decimal("9100"),
    ),
)

_DEFAULT_KEY = (SYNTHETIC_INSTRUMENT_ID, Timeframe.FIVE_MINUTE)


class FixtureHistoricalMarketDataRepository:
    """Deterministic, in-memory `HistoricalMarketDataRepository`
    implementation. Defaults to the synthetic fixture above; a caller
    (e.g. a test wanting to exercise duplicate/out-of-order handling) may
    inject its own `bars_by_key` instead — this class does not validate
    what it's given, by design, since that validation is
    `HistoricalMarketDataService`'s/`domain.market_data.quality`'s job,
    not the repository's (mirrors every other repository in this
    codebase: infrastructure stores and retrieves, it does not enforce
    business rules)."""

    def __init__(
        self,
        bars_by_key: Mapping[tuple[InstrumentId, Timeframe], tuple[Bar, ...]] | None = None,
    ) -> None:
        self._bars_by_key: Mapping[tuple[InstrumentId, Timeframe], tuple[Bar, ...]] = (
            bars_by_key if bars_by_key is not None else {_DEFAULT_KEY: _FIXTURE_BARS}
        )

    def get_bars(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        series = self._bars_by_key.get((instrument_id, timeframe), ())
        return tuple(bar for bar in series if start <= bar.timestamp <= end)


__all__ = ["SYNTHETIC_INSTRUMENT_ID", "FixtureHistoricalMarketDataRepository"]
