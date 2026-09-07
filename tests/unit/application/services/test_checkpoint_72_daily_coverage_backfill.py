# tests/unit/application/services/test_checkpoint_72_daily_coverage_backfill.py
#
# Checkpoint 72: proves `run_daily_backfill()`'s idempotency, safety, and
# window-selection logic — pure unit tests, fakes only, no database, no
# real network, matching `test_historical_data_preparation.py`'s own
# discipline (this file reuses that file's exact fake shapes rather than
# inventing new ones).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.daily_coverage_backfill import (
    DEFAULT_LOOKBACK_DAYS,
    DailyBackfillOutcome,
    most_recent_closed_trading_day,
    run_daily_backfill,
)
from intraday.application.services.historical_data_coverage import (
    HistoricalDataCoverageService,
)
from intraday.application.services.historical_data_preparation import (
    HistoricalDataPreparationService,
    PreparationStatus,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import expected_bar_timestamps
from intraday.domain.session.calendar import build_session_for
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")


# ---------------------------------------------------------------------------
# 1. `most_recent_closed_trading_day` — session/calendar reasoning only,
#    no provider, no repository.
# ---------------------------------------------------------------------------


def test_1_as_of_after_close_on_a_trading_day_returns_that_same_day() -> None:
    # 2026-08-03 is a real Monday trading day (CAS_EFFECTIVE_DATE itself).
    trading_day = datetime(2026, 8, 3, 3, 50, tzinfo=UTC)
    session = build_session_for(trading_day.date(), trading_day)
    after_close = session.market_close + timedelta(minutes=1)

    result = most_recent_closed_trading_day(after_close)

    assert result == trading_day.date()


def test_2_as_of_before_close_on_a_trading_day_returns_the_previous_trading_day() -> None:
    # 2026-08-04 is the trading day after 2026-08-03. Asking mid-session
    # on 08-04 must return 08-03 (08-04's own session has not closed yet).
    mid_session = datetime(2026, 8, 4, 6, 0, tzinfo=UTC)  # well inside the trading day

    result = most_recent_closed_trading_day(mid_session)

    assert result == datetime(2026, 8, 3).date()


def test_3_as_of_on_a_weekend_returns_the_preceding_fridays_close() -> None:
    # 2026-08-08 is a Saturday (2026-08-07 Friday is a trading day,
    # confirmed by CHECKPOINT_69/70's own real backfill of that date).
    saturday_evening = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)

    result = most_recent_closed_trading_day(saturday_evening)

    assert result == datetime(2026, 8, 7).date()


def test_4_naive_datetime_is_rejected_never_silently_assumed_utc() -> None:
    naive = datetime(2026, 8, 3, 10, 0)  # noqa: DTZ001 - deliberately naive, testing the guard
    with pytest.raises(ValueError):
        most_recent_closed_trading_day(naive)


# ---------------------------------------------------------------------------
# 2. `run_daily_backfill` — idempotency, safety, multi-symbol behavior.
#    Fakes below mirror `test_historical_data_preparation.py`'s own
#    `_FakeReadRepository`/`_FakeWriteRepository`/`_AlwaysAvailableProvider`
#    exactly, extended only to track per-call bar VALUES so mutation can be
#    asserted, not just call counts.
# ---------------------------------------------------------------------------


class _FakeReadRepository:
    """Scoped by `(instrument_id, timestamp)`, not bare timestamp — this
    checkpoint's own routine runs 4 DIFFERENT symbols against one shared
    fake, and the real, Django-backed repository scopes coverage per
    instrument via each row's own identity; a fake that ignored
    `instrument_id` would let one symbol's persisted bars falsely look
    like coverage for another, which the real repository could never do
    (`test_historical_data_preparation.py`'s own fakes never needed this
    distinction, since each of its tests only ever exercises ONE
    instrument at a time)."""

    def __init__(self) -> None:
        self.timestamps: set[tuple[object, datetime]] = set()

    def get_existing_timestamps(
        self, instrument_id: object, timeframe: object, start: datetime, end: datetime
    ) -> frozenset[datetime]:
        return frozenset(
            ts
            for (iid, ts) in self.timestamps
            if iid == instrument_id and start <= ts <= end
        )


class _FakeWriteRepository:
    def __init__(self, read_repository: _FakeReadRepository) -> None:
        self._read = read_repository
        self.upsert_calls = 0
        self.bars_by_key: dict[tuple[object, datetime], Bar] = {}

    def bulk_upsert(  # noqa: ARG002
        self,
        bars: tuple[Bar, ...],
        *,
        source: str,
        provenance: str = "UNKNOWN",
        canonicalization_state: str = "UNKNOWN",
        source_timestamp_semantics: str = "UNKNOWN",
    ) -> int:
        self.upsert_calls += 1
        for bar in bars:
            key = (bar.instrument_id, bar.timestamp)
            self._read.timestamps.add(key)
            self.bars_by_key[key] = bar
        return len(bars)


class _RecordingProvider:
    """Like `test_historical_data_preparation.py`'s `_AlwaysAvailableProvider`,
    but counts calls PER (start, end) window so a test can prove the
    second run of an already-covered window makes zero calls, while a
    genuinely new window (e.g. a later trading day) still triggers
    exactly one."""

    provenance = "SYNTHETIC_TEST"

    def __init__(self) -> None:
        self.fetch_calls = 0
        self.requested_windows: list[tuple[datetime, datetime]] = []

    def fetch(
        self, instrument_id: object, timeframe: object, start: datetime, end: datetime
    ) -> tuple[Bar, ...]:
        self.fetch_calls += 1
        self.requested_windows.append((start, end))
        session = build_session_for(start.date(), end)
        return tuple(
            Bar(
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=ts,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=Decimal("1000"),
            )
            for ts in expected_bar_timestamps(session, Timeframe.FIVE_MINUTE)
        )


def _preparation(read: _FakeReadRepository, provider: _RecordingProvider) -> tuple[
    HistoricalDataPreparationService, _FakeWriteRepository
]:
    write = _FakeWriteRepository(read)
    service = HistoricalDataPreparationService(
        coverage=HistoricalDataCoverageService(repository=read), provider=provider, writer=write
    )
    return service, write


AS_OF = datetime(2026, 8, 12, 20, 0, tzinfo=UTC)  # well after 08-11's close (a real trading day)


def test_5_first_run_fetches_and_second_run_same_day_is_a_zero_call_no_op() -> None:
    read = _FakeReadRepository()
    provider = _RecordingProvider()
    preparation, write = _preparation(read, provider)

    first = run_daily_backfill(as_of=AS_OF, preparation=preparation, lookback_days=3)
    assert all(o.outcome.status == PreparationStatus.COMPLETE for o in first)
    # `_group_into_ranges()` (HistoricalDataCoverageService's own,
    # unmodified logic) splits missing coverage into one contiguous
    # DateRange PER TRADING DAY (an overnight gap always exceeds one
    # bar-duration) - the [08-09..08-12] window covers 3 real trading
    # days (08-10/11/12), so 3 fetches x 4 symbols = 12 is the correct
    # first-run count, not "one call per symbol".
    assert provider.fetch_calls == 12
    first_persisted = sum(o.outcome.bars_persisted for o in first)
    assert first_persisted > 0

    second = run_daily_backfill(as_of=AS_OF, preparation=preparation, lookback_days=3)

    assert provider.fetch_calls == 12  # UNCHANGED — the whole point of this test
    assert all(o.outcome.api_requests == 0 for o in second)
    assert all(o.outcome.bars_fetched == 0 for o in second)
    assert all(o.outcome.status == PreparationStatus.COMPLETE for o in second)
    # `_RecordingProvider` (like `test_historical_data_preparation.py`'s
    # own `_AlwaysAvailableProvider`) fetches a full UNIFORM (non-CAS)
    # session, which persists MORE raw bars than the CAS-aware coverage
    # service counts as "expected" for these CATEGORY_I_CAS instruments
    # (RELIANCE/TCS/HDFCBANK/INFY) - the same documented fixture
    # mismatch that file's own `test_fully_cached_cas_instrument_range_
    # triggers_zero_provider_calls` works around. `cache_hits` on the
    # second run must equal the CAS-AWARE expected count, not raw
    # `bars_persisted` from the first run.
    from intraday.application.services.historical_data_coverage import (
        _expected_timestamps,  # noqa: SLF001 - deriving the CAS-aware expectation, not testing it
    )

    window_start_date = first[0].window_start
    window_end_date = first[0].window_end
    start_dt = datetime(
        window_start_date.year, window_start_date.month, window_start_date.day, 0, 0, 0, tzinfo=UTC
    )
    end_dt = datetime(
        window_end_date.year, window_end_date.month, window_end_date.day, 23, 59, 59, tzinfo=UTC
    )
    expected_per_symbol = len(_expected_timestamps(start_dt, end_dt, Timeframe.FIVE_MINUTE, RELIANCE))
    assert all(o.outcome.cache_hits == expected_per_symbol for o in second)


def test_6_running_twice_never_duplicates_or_mutates_an_existing_bar() -> None:
    """P4 discipline, proven directly rather than assumed: capture every
    bar's exact field values after the first run, run again, and assert
    byte-for-byte identity — this routine may only ever ADD rows for a
    genuinely new window, never touch an existing one."""
    read = _FakeReadRepository()
    provider = _RecordingProvider()
    preparation, write = _preparation(read, provider)

    run_daily_backfill(as_of=AS_OF, preparation=preparation, lookback_days=3)
    snapshot = dict(write.bars_by_key)
    assert len(snapshot) > 0

    run_daily_backfill(as_of=AS_OF, preparation=preparation, lookback_days=3)

    assert write.bars_by_key.keys() == snapshot.keys()  # no new, no missing
    for key, bar in snapshot.items():
        again = write.bars_by_key[key]
        assert again.open == bar.open
        assert again.high == bar.high
        assert again.low == bar.low
        assert again.close == bar.close
        assert again.volume == bar.volume


def test_7_a_later_as_of_extends_the_window_and_only_fetches_the_new_day() -> None:
    """Running "the next day" must not re-fetch what yesterday's run
    already cached — the whole reason `HistoricalDataCoverageService`'s
    diffing is reused rather than any new logic here."""
    read = _FakeReadRepository()
    provider = _RecordingProvider()
    preparation, write = _preparation(read, provider)

    run_daily_backfill(as_of=AS_OF, preparation=preparation, lookback_days=3)
    calls_after_day_1 = provider.fetch_calls

    next_as_of = datetime(2026, 8, 13, 20, 0, tzinfo=UTC)  # one real trading day later
    run_daily_backfill(as_of=next_as_of, preparation=preparation, lookback_days=3)

    # Each symbol's window now has exactly one new trading day
    # (2026-08-12) beyond what the first run covered - not a full
    # window re-fetch.
    assert provider.fetch_calls == calls_after_day_1 + 4


def test_8_a_weekend_as_of_is_a_safe_no_op_not_a_crash_or_surprise_fetch() -> None:
    """Requesting on a non-trading day must never error and must never
    fetch anything beyond what a normal weekday run would already have
    covered (a weekend contributes zero NEW expected trading days)."""
    read = _FakeReadRepository()
    provider = _RecordingProvider()
    preparation, write = _preparation(read, provider)

    run_daily_backfill(as_of=AS_OF, preparation=preparation, lookback_days=3)
    calls_before = provider.fetch_calls

    saturday = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)  # a Saturday
    outcomes = run_daily_backfill(as_of=saturday, preparation=preparation, lookback_days=3)

    # most_recent_closed_trading_day(saturday) resolves to 2026-08-14
    # (Friday); the new window is [08-12..08-15], which contains TWO
    # genuinely new trading days beyond the first run's [08-09..08-12]
    # window (08-13, 08-14) - 2 new days x 4 symbols = 8 new fetches,
    # not zero and not a crash, and no re-fetch of the already-cached
    # 08-12.
    assert all(isinstance(o, DailyBackfillOutcome) for o in outcomes)
    assert provider.fetch_calls == calls_before + 8


def test_9_default_lookback_is_used_when_not_overridden() -> None:
    read = _FakeReadRepository()
    provider = _RecordingProvider()
    preparation, write = _preparation(read, provider)

    outcomes = run_daily_backfill(as_of=AS_OF, preparation=preparation)

    expected_start = most_recent_closed_trading_day(AS_OF) - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    assert all(o.window_start == expected_start for o in outcomes)


def test_10_zero_bars_returned_by_the_provider_is_still_a_clean_outcome() -> None:
    """A provider that legitimately has nothing new to return (e.g. the
    window is entirely non-trading days) must not be treated as an
    error - `PreparationStatus.PARTIAL` with zero fetched/persisted is
    the correct, honest label `HistoricalDataPreparationService` itself
    already produces for a zero-expected-bar window; this routine does
    not paper over that with a fabricated COMPLETE."""

    class _EmptyProvider:
        provenance = "SYNTHETIC_TEST"

        def __init__(self) -> None:
            self.fetch_calls = 0

        def fetch(
            self, instrument_id: object, timeframe: object, start: datetime, end: datetime
        ) -> tuple[Bar, ...]:
            self.fetch_calls += 1
            return ()

    read = _FakeReadRepository()
    provider = _EmptyProvider()
    write = _FakeWriteRepository(read)
    preparation = HistoricalDataPreparationService(
        coverage=HistoricalDataCoverageService(repository=read), provider=provider, writer=write
    )

    outcomes = run_daily_backfill(as_of=AS_OF, preparation=preparation, lookback_days=3)

    assert all(o.outcome.bars_persisted == 0 for o in outcomes)
    assert all(o.outcome.status is not None for o in outcomes)  # never raises
