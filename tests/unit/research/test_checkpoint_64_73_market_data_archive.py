# File: tests/unit/research/test_checkpoint_64_73_market_data_archive.py
#
# Checkpoint 64.73: proof tests for the daily market-data archive and
# the redesigned, process-independent graceful shutdown.
#
# These are DETERMINISTIC and OFFLINE by design. Not one of them opens a
# socket, contacts Dhan, or requires a live session - which is the whole
# point of the shutdown redesign: 64.72 could not prove graceful
# shutdown because proving it required an OS signal against a live
# process. It is now provable against a fake repository in
# milliseconds.
from __future__ import annotations

import asyncio
import datetime as dt
from datetime import date, timedelta

import pytest

from intraday.application.repositories.worker_runtime_status import WorkerStopRequest
from intraday.application.services.worker_stop_request import watch_for_stop_request
from intraday.domain.market_data.aggregation import _interval_start
from intraday.domain.market_data.archive import (
    ArchiveStatus,
    ReconciliationStatus,
    TradingSessionIdentity,
    assess_archive_day,
    is_completeness_supported,
    trading_date_for,
)
from intraday.domain.market_data.archive_retention import (
    RETAIN_FOREVER,
    RetentionCandidate,
    RetentionPolicy,
    select_purgeable_trading_dates,
)
from intraday.domain.market_data.quality import expected_bar_timestamps
from intraday.domain.session.calendar import build_session_for
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

# 2026-08-25 is a Tuesday and is not in NSE_HOLIDAYS_2026.
TRADING_DAY = date(2026, 8, 25)
SATURDAY = date(2026, 8, 29)
HOLIDAY = date(2026, 10, 2)  # Mahatma Gandhi Jayanti

AFTER_CLOSE = dt.datetime(2026, 8, 25, 12, 0, tzinfo=dt.UTC)  # 17:30 IST
DURING_SESSION = dt.datetime(2026, 8, 25, 5, 0, tzinfo=dt.UTC)  # 10:30 IST


def _session(session_date: date = TRADING_DAY, as_of: dt.datetime = AFTER_CLOSE):
    return build_session_for(session_date, as_of)


def _identity(session_date: date = TRADING_DAY) -> TradingSessionIdentity:
    return TradingSessionIdentity(exchange=Exchange.NSE, trading_date=session_date)


def _assess(**overrides):
    session = overrides.pop("session", None) or _session()
    kwargs = {
        "identity": _identity(),
        "instrument_symbol": "RELIANCE",
        "timeframe": Timeframe.ONE_MINUTE,
        "data_source": "dhan_ws",
        "session": session,
        "closed_bar_timestamps": (),
        "forming_bar_count": 0,
        "quote_observation_count": 0,
        "first_observation_at": None,
        "last_observation_at": None,
        "as_of": AFTER_CLOSE,
    }
    kwargs.update(overrides)
    return assess_archive_day(**kwargs)


# ---------------------------------------------------------------------
# Trading-date derivation & timezone correctness
# ---------------------------------------------------------------------
class TestTradingDateDerivation:
    def test_ist_date_not_utc_date_for_opening_range(self) -> None:
        """09:15 IST on 2026-08-25 is 03:45 UTC the SAME day, but the
        general hazard this guards is the whole pre-05:30-UTC window: a
        naive `.date()` on a UTC instant is correct here only by luck of
        the date, so assert against an instant where UTC and IST
        genuinely disagree."""
        just_after_midnight_ist = dt.datetime(2026, 8, 24, 19, 0, tzinfo=dt.UTC)  # 00:30 IST 25th
        assert just_after_midnight_ist.date() == date(2026, 8, 24)
        assert trading_date_for(just_after_midnight_ist) == date(2026, 8, 25)

    def test_market_open_maps_to_its_own_ist_day(self) -> None:
        assert trading_date_for(dt.datetime(2026, 8, 25, 3, 45, tzinfo=dt.UTC)) == TRADING_DAY

    def test_market_close_maps_to_its_own_ist_day(self) -> None:
        assert trading_date_for(dt.datetime(2026, 8, 25, 10, 0, tzinfo=dt.UTC)) == TRADING_DAY

    def test_naive_datetime_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            trading_date_for(dt.datetime(2026, 8, 25, 3, 45))  # noqa: DTZ001

    def test_migration_backfill_rule_agrees_with_domain_rule(self) -> None:
        """Migration 0028 deliberately restates the IST rule rather than
        importing domain code (a migration must stay replayable even if
        domain code changes shape). This test is the guard that the two
        can never silently diverge."""
        from importlib import import_module

        migration = import_module(
            "intraday.infrastructure.persistence.migrations.0028_market_data_archive"
        )
        for instant in (
            dt.datetime(2026, 8, 24, 19, 0, tzinfo=dt.UTC),
            dt.datetime(2026, 8, 25, 3, 45, tzinfo=dt.UTC),
            dt.datetime(2026, 8, 25, 10, 0, tzinfo=dt.UTC),
        ):
            assert migration._ist_date(instant) == trading_date_for(instant)


# ---------------------------------------------------------------------
# Session identity
# ---------------------------------------------------------------------
class TestTradingSessionIdentity:
    def test_identity_key_is_stable_and_natural(self) -> None:
        assert _identity().key == "NSE:2026-08-25"

    def test_identity_is_value_equal_so_two_runs_converge(self) -> None:
        assert _identity() == TradingSessionIdentity(
            exchange=Exchange.NSE, trading_date=TRADING_DAY
        )

    def test_weekend_is_not_a_trading_day(self) -> None:
        assert _identity(SATURDAY).is_trading_day is False

    def test_nse_holiday_is_not_a_trading_day(self) -> None:
        assert _identity(HOLIDAY).is_trading_day is False

    def test_ordinary_weekday_is_a_trading_day(self) -> None:
        assert _identity().is_trading_day is True


# ---------------------------------------------------------------------
# Completeness model
# ---------------------------------------------------------------------
class TestCompletenessModel:
    def test_one_minute_session_expects_375_bars(self) -> None:
        assert len(expected_bar_timestamps(_session(), Timeframe.ONE_MINUTE)) == 375

    @pytest.mark.parametrize(
        "timeframe", [Timeframe.ONE_MINUTE, Timeframe.THREE_MINUTE, Timeframe.FIVE_MINUTE]
    )
    def test_session_aligned_timeframes_are_supported(self, timeframe: Timeframe) -> None:
        assert is_completeness_supported(timeframe) is True

    @pytest.mark.parametrize(
        "timeframe", [Timeframe.THIRTY_MINUTE, Timeframe.ONE_HOUR, Timeframe.TICK, Timeframe.DAY]
    )
    def test_misaligned_timeframes_are_explicitly_unsupported(self, timeframe: Timeframe) -> None:
        """The honesty requirement: rather than inventing an expected
        bar count for a timeframe whose buckets straddle the session
        boundary, the archive declares completeness unevaluable."""
        assert is_completeness_supported(timeframe) is False

    def test_full_session_is_complete(self) -> None:
        expected = expected_bar_timestamps(_session(), Timeframe.ONE_MINUTE)
        result = _assess(closed_bar_timestamps=expected, quote_observation_count=4869)
        assert result.status is ArchiveStatus.COMPLETE
        assert result.missing_bar_count == 0
        assert result.coverage_ratio == 1.0

    def test_twenty_minute_window_is_partial_not_complete(self) -> None:
        """THE 64.72 case. A real ~20-minute observe-only session
        produced 80 closed bars. Rows existed - the day was NOT
        complete. The archive must say so."""
        expected = expected_bar_timestamps(_session(), Timeframe.ONE_MINUTE)
        result = _assess(closed_bar_timestamps=expected[:80], quote_observation_count=4869)
        assert result.status is ArchiveStatus.PARTIAL
        assert result.closed_bar_count == 80
        assert result.expected_bar_count == 375
        assert result.missing_bar_count == 295
        assert result.reason == "missing_bars:295"

    def test_rows_existing_never_alone_implies_complete(self) -> None:
        result = _assess(closed_bar_timestamps=(), quote_observation_count=5000)
        assert result.status is not ArchiveStatus.COMPLETE

    def test_open_session_is_in_progress_never_partial(self) -> None:
        expected = expected_bar_timestamps(_session(), Timeframe.ONE_MINUTE)
        result = _assess(
            closed_bar_timestamps=expected[:10],
            quote_observation_count=500,
            as_of=DURING_SESSION,
            session=_session(as_of=DURING_SESSION),
        )
        assert result.status is ArchiveStatus.IN_PROGRESS
        assert result.reason == "session_not_closed"

    def test_no_data_on_a_trading_day_is_not_observed(self) -> None:
        result = _assess()
        assert result.status is ArchiveStatus.NOT_OBSERVED
        assert result.reason == "no_observations_persisted"

    def test_empty_weekend_is_not_observed_and_that_is_correct(self) -> None:
        result = _assess(identity=_identity(SATURDAY), session=_session(SATURDAY))
        assert result.status is ArchiveStatus.NOT_OBSERVED
        assert result.reason == "non_trading_day"

    def test_explicit_ingestion_failure_is_failed(self) -> None:
        result = _assess(quote_observation_count=10, ingestion_failed=True)
        assert result.status is ArchiveStatus.FAILED

    def test_unsupported_timeframe_can_never_be_complete(self) -> None:
        result = _assess(timeframe=Timeframe.THIRTY_MINUTE, quote_observation_count=100)
        assert result.status is ArchiveStatus.PARTIAL
        assert result.completeness_supported is False
        assert result.coverage_ratio == 0.0
        assert "completeness_unsupported_timeframe" in result.reason

    def test_reconciliation_defaults_to_not_reconciled(self) -> None:
        """64.73 models reconciliation; it does not perform it. Nothing
        computed purely from our own observations may claim otherwise."""
        expected = expected_bar_timestamps(_session(), Timeframe.ONE_MINUTE)
        result = _assess(closed_bar_timestamps=expected)
        assert result.reconciliation_status is ReconciliationStatus.NOT_RECONCILED


# ---------------------------------------------------------------------
# Gap & duplicate detection
# ---------------------------------------------------------------------
class TestGapDetection:
    def test_missing_interval_in_the_middle_is_detected_exactly(self) -> None:
        expected = list(expected_bar_timestamps(_session(), Timeframe.ONE_MINUTE))
        dropped = expected.pop(100)
        result = _assess(closed_bar_timestamps=tuple(expected), quote_observation_count=1)
        assert result.missing_bar_timestamps == (dropped,)
        assert result.status is ArchiveStatus.PARTIAL

    def test_duplicate_bar_timestamps_are_reported_and_not_double_counted(self) -> None:
        expected = expected_bar_timestamps(_session(), Timeframe.ONE_MINUTE)
        with_duplicate = (*expected, expected[0])
        result = _assess(closed_bar_timestamps=with_duplicate, quote_observation_count=1)
        assert result.duplicate_bar_timestamps == (expected[0],)
        assert result.closed_bar_count == 375
        assert result.status is ArchiveStatus.COMPLETE

    def test_expected_timestamps_align_with_live_aggregation_bucketing(self) -> None:
        """Completeness would be a fiction if the archive's expected
        interval boundaries disagreed with the ones the live aggregator
        actually produces. For 1m they must coincide exactly."""
        duration = timedelta(minutes=1)
        for stamp in expected_bar_timestamps(_session(), Timeframe.ONE_MINUTE):
            interval_start = stamp - duration
            assert _interval_start(interval_start, duration) == interval_start


# ---------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------
class TestRetention:
    def test_default_policy_deletes_nothing(self) -> None:
        assert RETAIN_FOREVER.deletes_anything is False

    def test_retain_forever_selects_nothing_however_old(self) -> None:
        candidates = [RetentionCandidate(date(2001, 1, 1), ArchiveStatus.COMPLETE, reconciled=True)]
        assert (
            select_purgeable_trading_dates(candidates, policy=RETAIN_FOREVER, today=TRADING_DAY)
            == ()
        )

    def test_partial_day_is_never_purgeable(self) -> None:
        policy = RetentionPolicy(raw_observation_retention_days=1)
        candidates = [RetentionCandidate(date(2020, 1, 1), ArchiveStatus.PARTIAL, reconciled=True)]
        assert select_purgeable_trading_dates(candidates, policy=policy, today=TRADING_DAY) == ()

    def test_unreconciled_day_is_never_purgeable(self) -> None:
        policy = RetentionPolicy(raw_observation_retention_days=1)
        candidates = [
            RetentionCandidate(date(2020, 1, 1), ArchiveStatus.COMPLETE, reconciled=False)
        ]
        assert select_purgeable_trading_dates(candidates, policy=policy, today=TRADING_DAY) == ()

    def test_only_old_complete_reconciled_days_are_ever_selectable(self) -> None:
        policy = RetentionPolicy(raw_observation_retention_days=1)
        old = date(2020, 1, 1)
        candidates = [
            RetentionCandidate(old, ArchiveStatus.COMPLETE, reconciled=True),
            RetentionCandidate(TRADING_DAY, ArchiveStatus.COMPLETE, reconciled=True),
        ]
        assert select_purgeable_trading_dates(candidates, policy=policy, today=TRADING_DAY) == (
            old,
        )


# ---------------------------------------------------------------------
# Graceful shutdown (process-independent, no live provider)
# ---------------------------------------------------------------------
class _FakeStopRequests:
    """Returns `None` until `arm()` is called - modelling an operator
    running `request_market_data_worker_stop` mid-session."""

    def __init__(self, *, arm_after_polls: int) -> None:
        self.polls = 0
        self._arm_after = arm_after_polls

    async def __call__(self) -> WorkerStopRequest | None:
        self.polls += 1
        if self.polls > self._arm_after:
            return WorkerStopRequest(
                provider="dhan",
                requested_at=AFTER_CLOSE,
                requested_by="operator",
                reason_safe="operator_requested",
            )
        return None


async def _no_sleep(_seconds: float) -> None:
    return None


class TestGracefulShutdownRequest:
    def test_stop_request_sets_the_shared_stop_event(self) -> None:
        async def scenario():
            stop_event = asyncio.Event()
            polls = _FakeStopRequests(arm_after_polls=2)
            request = await watch_for_stop_request(
                stop_event, provider="dhan", get_stop_request=polls, sleep=_no_sleep
            )
            return stop_event, request

        stop_event, request = asyncio.run(scenario())
        assert stop_event.is_set() is True
        assert request is not None
        assert request.requested_by == "operator"

    def test_watcher_exits_when_stopped_by_another_path(self) -> None:
        """An OS signal that DID work, or the run finishing on its own -
        the watcher must not hang or claim credit for the stop."""

        async def scenario():
            stop_event = asyncio.Event()
            stop_event.set()
            polls = _FakeStopRequests(arm_after_polls=0)
            request = await watch_for_stop_request(
                stop_event, provider="dhan", get_stop_request=polls, sleep=_no_sleep
            )
            return request, polls.polls

        request, polls = asyncio.run(scenario())
        assert request is None
        assert polls == 0

    def test_no_stop_request_means_the_worker_keeps_running(self) -> None:
        async def scenario():
            stop_event = asyncio.Event()

            async def _never() -> WorkerStopRequest | None:
                return None

            async def _real_sleep(_seconds: float) -> None:
                await asyncio.sleep(0.001)

            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    watch_for_stop_request(
                        stop_event,
                        provider="dhan",
                        get_stop_request=_never,
                        sleep=_real_sleep,
                    ),
                    timeout=0.05,
                )
            return stop_event.is_set()

        assert asyncio.run(scenario()) is False

    def test_stop_request_propagates_through_the_reconnect_supervisor(self) -> None:
        """The full requirement chain, minus the socket: a stop request
        observed mid-run must prevent the supervisor opening any FURTHER
        connection and must yield a clean STOPPED final state."""
        from intraday.infrastructure.market_data_providers.dhan.async_worker import (
            AsyncWorkerRunResult,
        )
        from intraday.infrastructure.market_data_providers.dhan.reconnect_supervisor import (
            run_worker_with_reconnect,
        )
        from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState

        connections = 0

        async def scenario():
            nonlocal connections
            stop_event = asyncio.Event()

            async def connect_and_run() -> AsyncWorkerRunResult:
                nonlocal connections
                connections += 1
                stop_event.set()  # the watcher observed a stop request mid-connection
                return AsyncWorkerRunResult(final_state=WorkerState.RECONNECTING)

            return await run_worker_with_reconnect(
                connect_and_run, max_attempts=5, stop_event=stop_event
            )

        result = asyncio.run(scenario())
        assert result.final_state is WorkerState.STOPPED
        assert connections == 1
