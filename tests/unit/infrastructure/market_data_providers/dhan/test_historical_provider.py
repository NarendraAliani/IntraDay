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
# Checkpoint 67.6: a BSE-listed instrument, used ONLY to prove the
# segment-discrimination fix - 67.0's empirical proof never touched BSE,
# so every proof-scope check against this id must resolve UNPROVEN even
# when timeframe/era exactly match the proven NSE_EQ scope.
RELIANCE_BSE_ID = make_instrument_id(Exchange.BSE, "RELIANCE")


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


# Checkpoint 67.5: request windows used across the era-aware policy
# tests below. `_CAS_ERA_WINDOW` is entirely on/after CAS_EFFECTIVE_DATE
# (2026-08-03); `_PRE_CAS_WINDOW` is entirely before it; both are single-day
# windows so they can never straddle the boundary (no MIXED_UNRESOLVED
# ambiguity in these fixtures).
_CAS_ERA_WINDOW = (
    datetime(2026, 8, 17, 3, 50, tzinfo=UTC),
    datetime(2026, 8, 17, 9, 45, tzinfo=UTC),
)
_PRE_CAS_WINDOW = (
    datetime(2026, 7, 20, 3, 50, tzinfo=UTC),
    datetime(2026, 7, 20, 9, 45, tzinfo=UTC),
)


def test_canonicalization_state_for_5m_cas_era_is_canonicalized() -> None:
    """Checkpoint 67.5 Part 4: ONLY 5m + CAS-era (67.0's exact proven
    scope: RELIANCE, 2026-08-17) is stamped CANONICALIZED."""
    from intraday.domain.market_data.source_timestamp import (
        CANONICALIZATION_STATE_CANONICALIZED,
    )

    provider = _provider(())
    start, end = _CAS_ERA_WINDOW
    assert (
        provider.canonicalization_state_for(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)
        == CANONICALIZATION_STATE_CANONICALIZED
    )


def test_canonicalization_state_for_5m_pre_cas_is_unknown_not_canonicalized() -> None:
    """Checkpoint 67.5 Part 4 - THE KEY REGRESSION TEST: a future 5m
    ingestion request for a PRE-CAS date must NOT inherit the CAS-era-only
    67.0 proof merely because it is 5-minute. This is the exact scope-leakage
    bug 67.5 fixes (67.4's `_EMPIRICALLY_PROVEN_CANONICAL_TIMEFRAMES` keyed
    proof off `timeframe` alone, so this case would have wrongly resolved
    CANONICALIZED under 67.4)."""
    from intraday.domain.market_data.source_timestamp import CANONICALIZATION_STATE_UNKNOWN

    provider = _provider(())
    start, end = _PRE_CAS_WINDOW
    assert (
        provider.canonicalization_state_for(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)
        == CANONICALIZATION_STATE_UNKNOWN
    )


def test_canonicalization_state_for_unproven_intraday_timeframes_is_unknown() -> None:
    """Checkpoint 67.4 Part 4/I (still true under 67.5's era-aware
    policy): 1m/15m/1h still run the `+interval` arithmetic
    (harmless/best-effort) but must NEVER be reported as CANONICALIZED -
    only UNKNOWN, since 67.0 never proved their semantics, at any era.
    'Code applied +interval' must never be treated as 'data is
    semantically proven canonical'."""
    from intraday.domain.market_data.source_timestamp import CANONICALIZATION_STATE_UNKNOWN

    provider = _provider(())
    for start, end in (_CAS_ERA_WINDOW, _PRE_CAS_WINDOW):
        for timeframe in (Timeframe.ONE_MINUTE, Timeframe.FIFTEEN_MINUTE, Timeframe.ONE_HOUR):
            assert (
                provider.canonicalization_state_for(RELIANCE_ID, timeframe, start, end)
                == CANONICALIZATION_STATE_UNKNOWN
            )


def test_canonicalization_state_for_daily_is_not_applicable() -> None:
    """Checkpoint 67.3 Part 11 (unchanged by 67.4/67.5): daily is
    deliberately kept OUT of this state transition entirely - never
    mislabeled UNCANONICALIZED or CANONICALIZED just because `fetch()`
    treats its raw timestamp as already-CLOSE, regardless of era."""
    from intraday.domain.market_data.source_timestamp import (
        CANONICALIZATION_STATE_NOT_APPLICABLE,
    )

    provider = _provider(())
    start, end = _CAS_ERA_WINDOW
    assert (
        provider.canonicalization_state_for(RELIANCE_ID, Timeframe.DAY, start, end)
        == CANONICALIZATION_STATE_NOT_APPLICABLE
    )


def test_canonicalization_state_for_5m_mixed_era_window_is_unknown() -> None:
    """Checkpoint 67.5 Part 1/3: a request window that straddles
    `CAS_EFFECTIVE_DATE` resolves MIXED_UNRESOLVED, not silently either
    era - it must NOT be treated as proven CAS-era just because its
    `end` falls in the CAS era."""
    from intraday.domain.market_data.source_timestamp import CANONICALIZATION_STATE_UNKNOWN

    provider = _provider(())
    start = datetime(2026, 7, 20, 3, 50, tzinfo=UTC)  # PRE-CAS
    end = datetime(2026, 8, 17, 9, 45, tzinfo=UTC)  # CAS-era
    assert (
        provider.canonicalization_state_for(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)
        == CANONICALIZATION_STATE_UNKNOWN
    )


def test_source_timestamp_semantics_for_5m_cas_era_is_open() -> None:
    """Checkpoint 67.5 Part 2/4: the SEMANTICS half - only 5m + CAS-era
    is the scope 67.0 empirically proved OPEN."""
    from intraday.domain.market_data.source_timestamp import SourceTimestampSemantics

    provider = _provider(())
    start, end = _CAS_ERA_WINDOW
    assert (
        provider.source_timestamp_semantics_for(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)
        == SourceTimestampSemantics.OPEN.value
    )


def test_source_timestamp_semantics_for_5m_pre_cas_is_unknown() -> None:
    """Checkpoint 67.5 Part 4 - the SEMANTICS-half companion to the key
    regression test above: PRE-CAS 5m must report UNKNOWN, never OPEN."""
    from intraday.domain.market_data.source_timestamp import SourceTimestampSemantics

    provider = _provider(())
    start, end = _PRE_CAS_WINDOW
    assert (
        provider.source_timestamp_semantics_for(RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end)
        == SourceTimestampSemantics.UNKNOWN.value
    )


def test_source_timestamp_semantics_for_1m_is_unknown_at_any_era() -> None:
    """Checkpoint 67.4 Part 13 test 5 (still true under 67.5): 1m must
    not pass as canonical while its semantics are unproven - the
    provider must report UNKNOWN, never OPEN, for 1m, regardless of
    era."""
    from intraday.domain.market_data.source_timestamp import SourceTimestampSemantics

    provider = _provider(())
    for start, end in (_CAS_ERA_WINDOW, _PRE_CAS_WINDOW):
        assert (
            provider.source_timestamp_semantics_for(RELIANCE_ID, Timeframe.ONE_MINUTE, start, end)
            == SourceTimestampSemantics.UNKNOWN.value
        )


def test_source_timestamp_semantics_for_daily_is_not_applicable() -> None:
    from intraday.domain.market_data.source_timestamp import (
        CANONICALIZATION_STATE_NOT_APPLICABLE,
    )

    provider = _provider(())
    start, end = _CAS_ERA_WINDOW
    assert (
        provider.source_timestamp_semantics_for(RELIANCE_ID, Timeframe.DAY, start, end)
        == CANONICALIZATION_STATE_NOT_APPLICABLE
    )


def test_proof_scope_resolver_reports_provider_endpoint_segment_and_era_explicitly() -> None:
    """Checkpoint 67.5 Part 1, EXTENDED 67.6 Part 2: `DhanTimestampProofScope`
    carries the full proof-scope tuple (provider/endpoint/segment/timeframe/
    era/proof_status), not just a boolean - a caller/test can inspect
    exactly WHY a scope was or was not permitted, rather than only the
    final yes/no. `segment="NSE_EQ"` must be passed explicitly for the
    PROVEN case - 67.0's proof was NSE-only, so the resolver's proof
    lookup genuinely depends on segment being supplied, not merely
    timeframe/era."""
    from intraday.infrastructure.market_data_providers.dhan.historical_provider import (
        ProofStatus,
        _resolve_intraday_proof_scope,
    )

    cas_start, cas_end = _CAS_ERA_WINDOW
    proven_scope = _resolve_intraday_proof_scope(
        Timeframe.FIVE_MINUTE, cas_start, cas_end, segment="NSE_EQ"
    )
    assert proven_scope.provider == "DHAN"
    assert proven_scope.endpoint == "INTRADAY"
    assert proven_scope.segment == "NSE_EQ"
    assert proven_scope.era == "CAS_ERA"
    assert proven_scope.proof_status is ProofStatus.PROVEN
    assert proven_scope.canonicalization_permitted is True

    pre_cas_start, pre_cas_end = _PRE_CAS_WINDOW
    unproven_scope = _resolve_intraday_proof_scope(
        Timeframe.FIVE_MINUTE, pre_cas_start, pre_cas_end, segment="NSE_EQ"
    )
    assert unproven_scope.era == "PRE_CAS"
    assert unproven_scope.proof_status is ProofStatus.UNPROVEN
    assert unproven_scope.canonicalization_permitted is False


# ---------------------------------------------------------------------------
# Checkpoint 67.6 Part 5 - THE NEW REGRESSION TESTS: segment discrimination.
# ---------------------------------------------------------------------------


def test_bse_eq_5m_cas_era_is_unproven_never_inherits_nse_proof() -> None:
    """Checkpoint 67.6 Part 5 test 2 - THE KEY REGRESSION TEST for this
    checkpoint: a BSE_EQ instrument, otherwise IDENTICAL request
    (5m, CAS-era) to the one 67.0 empirically proved for NSE_EQ, must
    resolve UNPROVEN/UNKNOWN. Before this checkpoint's fix,
    `_PROVEN_INTRADAY_SCOPES` was keyed only by (timeframe, era), so
    this exact case would have wrongly resolved PROVEN/CANONICALIZED."""
    from intraday.domain.market_data.source_timestamp import (
        CANONICALIZATION_STATE_UNKNOWN,
        SourceTimestampSemantics,
    )

    provider = _provider(())
    start, end = _CAS_ERA_WINDOW
    assert (
        provider.canonicalization_state_for(RELIANCE_BSE_ID, Timeframe.FIVE_MINUTE, start, end)
        == CANONICALIZATION_STATE_UNKNOWN
    )
    assert (
        provider.source_timestamp_semantics_for(RELIANCE_BSE_ID, Timeframe.FIVE_MINUTE, start, end)
        == SourceTimestampSemantics.UNKNOWN.value
    )


def test_nse_eq_and_bse_eq_genuinely_diverge_for_the_identical_request() -> None:
    """Checkpoint 67.6 - concrete before/after proof that the lookup key
    ACTUALLY uses segment: the exact same timeframe/window, only the
    instrument's exchange differs, and the two calls must produce
    DIFFERENT `canonicalization_state_for` results."""
    from intraday.domain.market_data.source_timestamp import (
        CANONICALIZATION_STATE_CANONICALIZED,
        CANONICALIZATION_STATE_UNKNOWN,
    )

    provider = _provider(())
    start, end = _CAS_ERA_WINDOW
    nse_result = provider.canonicalization_state_for(
        RELIANCE_ID, Timeframe.FIVE_MINUTE, start, end
    )
    bse_result = provider.canonicalization_state_for(
        RELIANCE_BSE_ID, Timeframe.FIVE_MINUTE, start, end
    )
    assert nse_result == CANONICALIZATION_STATE_CANONICALIZED
    assert bse_result == CANONICALIZATION_STATE_UNKNOWN
    assert nse_result != bse_result


def test_policy_lookup_fails_closed_for_unsupported_segment() -> None:
    """Checkpoint 67.6 Part 5 test 8: an instrument whose exchange isn't
    even in `_EXCHANGE_SEGMENTS` (i.e. `_segment_for_instrument` returns
    `None`) must fail closed to UNPROVEN, never silently pass through as
    if segment were irrelevant."""
    from intraday.infrastructure.market_data_providers.dhan.historical_provider import (
        ProofStatus,
        _resolve_intraday_proof_scope,
    )

    cas_start, cas_end = _CAS_ERA_WINDOW
    scope = _resolve_intraday_proof_scope(
        Timeframe.FIVE_MINUTE, cas_start, cas_end, segment=None
    )
    assert scope.proof_status is ProofStatus.UNPROVEN
    assert scope.canonicalization_permitted is False

    scope_bse = _resolve_intraday_proof_scope(
        Timeframe.FIVE_MINUTE, cas_start, cas_end, segment="BSE_EQ"
    )
    assert scope_bse.proof_status is ProofStatus.UNPROVEN
    assert scope_bse.canonicalization_permitted is False


def test_segment_for_instrument_reuses_the_existing_exchange_segment_mapping() -> None:
    """Checkpoint 67.6 Part 2: `_segment_for_instrument` must resolve the
    SAME NSE_EQ/BSE_EQ vocabulary `fetch()` already uses
    (`_EXCHANGE_SEGMENTS`) - a new, parallel segment concept was
    explicitly NOT to be invented."""
    from intraday.infrastructure.market_data_providers.dhan.historical_provider import (
        _segment_for_instrument,
    )

    assert _segment_for_instrument(RELIANCE_ID) == "NSE_EQ"
    assert _segment_for_instrument(RELIANCE_BSE_ID) == "BSE_EQ"
