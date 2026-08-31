# tests/unit/infrastructure/market_data_providers/dhan/test_historical_provider.py
#
# Unit coverage for `DhanHistoricalBarProvider` - the real adapter that
# satisfies `HistoricalDataPreparationService`'s `HistoricalBarProvider`
# Protocol. Never makes a real network call - `historical_client`'s own
# `fetch_daily_candles`/`fetch_intraday_candles` are monkeypatched at
# the module the provider actually calls them from.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from intraday.application.services.instrument_master import InstrumentMasterEntry
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.market_data_providers.dhan import historical_provider
from intraday.infrastructure.market_data_providers.dhan.historical_client import (
    DhanHistoricalCandle,
)
from intraday.infrastructure.market_data_providers.dhan.historical_provider import (
    DhanHistoricalBarProvider,
    DhanHistoricalBarProviderUnavailableError,
)

RELIANCE_ID = make_instrument_id(Exchange.NSE, "RELIANCE")


class _FakeInstrumentMaster:
    def __init__(self, entries: tuple[InstrumentMasterEntry, ...]) -> None:
        self._entries = entries

    def list_instruments(self, exchange: Exchange) -> tuple[InstrumentMasterEntry, ...]:
        return self._entries


def _provider(entries: tuple[InstrumentMasterEntry, ...]) -> DhanHistoricalBarProvider:
    return DhanHistoricalBarProvider(
        client_id="fake-client-id",
        access_token="fake-token",
        instrument_master=_FakeInstrumentMaster(entries),
    )


def test_fetch_resolves_security_id_and_delegates_to_the_daily_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def _fake_fetch_daily_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        calls.append(kwargs)
        return (
            DhanHistoricalCandle(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1000,
            ),
        )

    monkeypatch.setattr(historical_provider, "fetch_daily_candles", _fake_fetch_daily_candles)

    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    bars = provider.fetch(
        RELIANCE_ID,
        Timeframe.DAY,
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 2, tzinfo=UTC),
    )

    assert len(bars) == 1
    assert bars[0].instrument_id == RELIANCE_ID
    assert calls[0]["security_id"] == 2885
    assert calls[0]["exchange_segment"] == "NSE_EQ"


def test_fetch_delegates_to_the_intraday_client_for_a_minute_timeframe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        calls.append(kwargs)
        return ()

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)

    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    provider.fetch(
        RELIANCE_ID,
        Timeframe.FIVE_MINUTE,
        datetime(2024, 1, 1, 9, 15, tzinfo=UTC),
        datetime(2024, 1, 1, 15, 30, tzinfo=UTC),
    )

    assert calls[0]["interval_minutes"] == 5


def test_fetch_widens_the_dhan_request_window_on_the_lower_boundary_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 66.8: `start`/`end` passed into `fetch()` are the
    CANONICAL RESEARCH WINDOW - the caller's expected bar-CLOSE
    timestamps (see `HistoricalDataCoverageService._expected_timestamps` -
    `market_open + timeframe_duration` is the FIRST expected close). The
    PROVIDER REQUEST ENVELOPE actually sent to Dhan widens only the LOWER
    boundary by one bar-duration (66.6 proved this recovers the first
    expected candle). 66.7 had symmetrically widened the upper boundary
    too, on an inference that its own controlled diagnostic then
    disproved (widening `to_time` changed nothing about Dhan's response);
    66.8 removed that dead widening, so `to_time` is now sent as the
    unwidened canonical `end` - see `_provider_request_envelope`'s
    docstring for the full history."""
    calls: list[dict[str, object]] = []

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        calls.append(kwargs)
        return ()

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)

    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    start = datetime(2024, 1, 1, 3, 50, tzinfo=UTC)  # 09:20 IST - first expected 5m close
    end = datetime(2024, 1, 1, 9, 45, tzinfo=UTC)  # 15:15 IST - last expected close
    provider.fetch(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)

    assert calls[0]["from_time"] == start - timedelta(minutes=5)
    assert calls[0]["to_time"] == end


def test_fetch_post_filter_still_bounds_returned_bars_to_the_requested_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 67.1: raw Dhan intraday timestamps are OPEN-of-interval
    (67.0's proven finding) and are canonicalized (+one bar-duration) to
    a CLOSE timestamp BEFORE this post-filter runs. The widened
    envelope's leading raw candle (`start - one bar`) canonicalizes to
    EXACTLY `start` and must now be RETAINED - that is the whole point
    of the lower-widening (66.6) combined with 67.1's canonicalization
    fix: it recovers the first canonical bar that a raw/unshifted filter
    would have discarded. A raw candle far past any canonicalized value
    in range must still be excluded - the filter is not simply
    disabled."""

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        return (
            DhanHistoricalCandle(  # one bar-duration BEFORE start -> canonicalizes to exactly start
                timestamp=datetime(2024, 1, 1, 3, 45, tzinfo=UTC),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            ),
            DhanHistoricalCandle(  # far past the canonical end even after the +5m shift
                timestamp=datetime(2024, 1, 1, 23, 50, tzinfo=UTC),
                open=2,
                high=2,
                low=2,
                close=2,
                volume=2,
            ),
        )

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)

    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    start = datetime(2024, 1, 1, 3, 50, tzinfo=UTC)
    end = datetime(2024, 1, 1, 9, 45, tzinfo=UTC)
    bars = provider.fetch(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)

    assert len(bars) == 1
    assert bars[0].timestamp == start


def test_fetch_post_filter_excludes_a_candle_past_the_canonical_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 67.1: the raw candle that canonicalizes to EXACTLY the
    canonical `end` is Dhan's `end - one bar` raw timestamp (since
    canonical = raw + one bar) - it must be retained. A raw candle one
    bar later than that (which canonicalizes to `end + one bar`) must be
    excluded - the post-filter is defense-in-depth against any candle
    Dhan returns past the canonical window, evaluated on the
    canonicalized timestamp, never the raw one."""

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        return (
            DhanHistoricalCandle(  # end - one bar (raw) -> canonicalizes to exactly `end`
                timestamp=datetime(2024, 1, 1, 9, 40, tzinfo=UTC),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            ),
            DhanHistoricalCandle(  # end (raw) -> canonicalizes to `end + one bar`, past the window
                timestamp=datetime(2024, 1, 1, 9, 45, tzinfo=UTC),
                open=2,
                high=2,
                low=2,
                close=2,
                volume=2,
            ),
        )

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)

    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    start = datetime(2024, 1, 1, 3, 50, tzinfo=UTC)
    end = datetime(2024, 1, 1, 9, 45, tzinfo=UTC)
    bars = provider.fetch(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)

    assert len(bars) == 1
    assert bars[0].timestamp == end


def test_unknown_security_id_raises_unavailable_never_guesses() -> None:
    provider = _provider(())  # scrip master has no entry for RELIANCE at all
    with pytest.raises(DhanHistoricalBarProviderUnavailableError):
        provider.fetch(
            RELIANCE_ID,
            Timeframe.DAY,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
        )


def test_unsupported_intraday_timeframe_raises_unavailable_never_silently_rounds() -> None:
    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    with pytest.raises(DhanHistoricalBarProviderUnavailableError):
        provider.fetch(
            RELIANCE_ID,
            Timeframe.THREE_MINUTE,  # Dhan has no 3-minute interval
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
        )


def test_a_dhan_client_error_is_wrapped_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from intraday.infrastructure.market_data_providers.dhan.historical_client import (
        DhanHistoricalConnectionError,
    )

    def _raise(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        raise DhanHistoricalConnectionError("boom")

    monkeypatch.setattr(historical_provider, "fetch_daily_candles", _raise)

    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    with pytest.raises(DhanHistoricalBarProviderUnavailableError):
        provider.fetch(
            RELIANCE_ID,
            Timeframe.DAY,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
        )


def test_raw_0915_ist_candle_canonicalizes_to_0920_ist_close_for_5m(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 67.1 Part 6 test 1: raw Dhan 09:15 IST (03:45 UTC) is
    the OPEN of the first 5m interval of the session - it must
    canonicalize to the 09:20 IST (03:50 UTC) canonical CLOSE, and that
    canonical close is the caller's requested `start`, so it must be
    retained by the post-filter."""

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        return (
            DhanHistoricalCandle(
                timestamp=datetime(2024, 1, 1, 3, 45, tzinfo=UTC),  # 09:15 IST raw OPEN
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            ),
        )

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)
    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    start = datetime(2024, 1, 1, 3, 50, tzinfo=UTC)  # 09:20 IST
    end = datetime(2024, 1, 1, 9, 45, tzinfo=UTC)  # 15:15 IST
    bars = provider.fetch(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)

    assert len(bars) == 1
    assert bars[0].timestamp == datetime(2024, 1, 1, 3, 50, tzinfo=UTC)  # 09:20 IST canonical close


def test_raw_1510_ist_candle_canonicalizes_to_1515_ist_close_for_5m(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 67.1 Part 6 test 2: raw Dhan 15:10 IST is the OPEN of
    the LAST 5m interval of the session - it must canonicalize to
    15:15 IST, the session's canonical last close, and survive the
    post-filter at the canonical `end` boundary."""

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        return (
            DhanHistoricalCandle(
                timestamp=datetime(2024, 1, 1, 9, 40, tzinfo=UTC),  # 15:10 IST raw OPEN
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            ),
        )

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)
    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    start = datetime(2024, 1, 1, 3, 50, tzinfo=UTC)
    end = datetime(2024, 1, 1, 9, 45, tzinfo=UTC)  # 15:15 IST
    bars = provider.fetch(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)

    assert len(bars) == 1
    assert bars[0].timestamp == end


def test_canonical_filtering_retains_both_boundary_candles_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 67.1 Part 6 test 3: the raw 09:15 IST and 15:10 IST
    candles together - the two ends of a full session - must both
    survive canonicalization + filtering in the same `fetch()` call."""

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        return (
            DhanHistoricalCandle(
                timestamp=datetime(2024, 1, 1, 3, 45, tzinfo=UTC),  # 09:15 IST
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            ),
            DhanHistoricalCandle(
                timestamp=datetime(2024, 1, 1, 9, 40, tzinfo=UTC),  # 15:10 IST
                open=2,
                high=2,
                low=2,
                close=2,
                volume=2,
            ),
        )

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)
    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    start = datetime(2024, 1, 1, 3, 50, tzinfo=UTC)  # 09:20 IST
    end = datetime(2024, 1, 1, 9, 45, tzinfo=UTC)  # 15:15 IST
    bars = provider.fetch(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)

    assert [b.timestamp for b in bars] == [start, end]


def test_raw_timestamps_are_not_filtered_before_canonicalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 67.1 Part 6 test 4: a raw candle strictly BELOW the
    canonical `start` (and which would therefore have been wrongly
    discarded by a raw-timestamp filter applied before the OPEN->CLOSE
    shift) must still be retained once its CANONICAL timestamp lands
    inside `[start, end]` - proving the filter runs on the
    canonicalized value, not the raw one."""

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        return (
            DhanHistoricalCandle(
                # raw < start, but raw + 5m == start
                timestamp=datetime(2024, 1, 1, 3, 45, tzinfo=UTC),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            ),
        )

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)
    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    start = datetime(2024, 1, 1, 3, 50, tzinfo=UTC)
    end = datetime(2024, 1, 1, 9, 45, tzinfo=UTC)
    raw_timestamp = datetime(2024, 1, 1, 3, 45, tzinfo=UTC)
    assert raw_timestamp < start  # raw candle is outside [start, end] BEFORE canonicalization

    bars = provider.fetch(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)

    assert len(bars) == 1  # retained - its CANONICAL timestamp (start) is in range


def test_candles_outside_canonical_range_are_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 67.1 Part 6 test 5: a raw candle whose CANONICAL
    timestamp (after the +interval shift) still falls outside
    `[start, end]` must be excluded - canonicalization must not become a
    backdoor that disables the window filter entirely."""

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        return (
            DhanHistoricalCandle(
                timestamp=datetime(2024, 1, 1, 23, 59, tzinfo=UTC),  # nowhere near the window
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            ),
        )

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)
    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    start = datetime(2024, 1, 1, 3, 50, tzinfo=UTC)
    end = datetime(2024, 1, 1, 9, 45, tzinfo=UTC)
    bars = provider.fetch(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)

    assert bars == ()


def test_no_synthetic_candle_is_created_by_canonicalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 67.1 Part 6 test 6: canonicalization only ever
    TRANSFORMS a timestamp on a candle Dhan actually returned - it must
    never fabricate a bar to fill a gap. Zero raw candles in -> zero
    bars out."""

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        return ()

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)
    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    bars = provider.fetch(
        RELIANCE_ID,
        Timeframe.FIVE_MINUTE,
        datetime(2024, 1, 1, 3, 50, tzinfo=UTC),
        datetime(2024, 1, 1, 9, 45, tzinfo=UTC),
    )

    assert bars == ()


@pytest.mark.parametrize(
    ("timeframe", "interval_minutes"),
    [
        (Timeframe.ONE_MINUTE, 1),
        (Timeframe.FIVE_MINUTE, 5),
        (Timeframe.FIFTEEN_MINUTE, 15),
        (Timeframe.ONE_HOUR, 60),
    ],
)
def test_canonicalization_arithmetic_is_generic_across_every_intraday_interval(
    monkeypatch: pytest.MonkeyPatch, timeframe: Timeframe, interval_minutes: int
) -> None:
    """Checkpoint 67.1 Part 6 test 7: the raw->canonical `+interval`
    shift is derived purely from `interval_minutes` for every Dhan
    intraday interval this adapter supports - never hard-coded to 5m.
    This test exercises the arithmetic generically; per the checkpoint's
    explicit instruction it is NOT a claim that 1m/15m/1h were
    empirically validated against real Dhan data (only 5m was, in
    67.0) - only that the code path is interval-agnostic."""
    raw_timestamp = datetime(2024, 1, 1, 3, 45, tzinfo=UTC)

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        return (
            DhanHistoricalCandle(
                timestamp=raw_timestamp, open=1, high=1, low=1, close=1, volume=1
            ),
        )

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)
    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    expected_canonical = raw_timestamp + timedelta(minutes=interval_minutes)
    bars = provider.fetch(RELIANCE_ID, timeframe, expected_canonical, expected_canonical)

    assert len(bars) == 1
    assert bars[0].timestamp == expected_canonical


def test_provenance_is_real_dhan() -> None:
    """Checkpoint 65.23: `HistoricalDataPreparationService` reads this
    attribute (`getattr(self.provider, "provenance", PROVENANCE_UNKNOWN)`)
    to stamp `HistoricalBar.provenance` - a real Dhan fetch must never
    silently fall back to UNKNOWN just because this provider declared
    nothing, which is exactly the defect 65.22-R found and this fixes."""
    from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN

    provider = _provider(())
    assert provider.provenance == PROVENANCE_REAL_DHAN
