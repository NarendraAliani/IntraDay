# tests/unit/research/test_checkpoint_64_63_live_data_integrity.py
#
# Checkpoint 64.63: LIVE MARKET-DATA INTEGRITY REMEDIATION.
#
# Forensic follow-up to Checkpoint 64.62's first real NSE Dhan
# WebSocket session, which surfaced three genuine, live-only-
# discoverable data-integrity gaps (see `taskReport.md`):
#
#   1. A ~5.5 hour offset between the WebSocket ticker/quote packet's
#      decoded `last_trade_time` and real ingestion time - investigated
#      here, but NOT blindly "fixed" with a hardcoded +/-5:30 constant,
#      because neither Dhan's own public WebSocket documentation (which
#      only says "Last Trade Time (EPOCH)", nothing about how the
#      server itself computes that integer) nor this repository's own
#      code gives a conclusive, source-backed answer for WHY the raw
#      `int32` the server sent was ~5.5h ahead of true UTC. The tests
#      below characterize CURRENT decoder behaviour precisely (so any
#      future, conclusively-proven fix has a regression net) and
#      reproduce the real anomaly against a sanitized, clearly-labeled
#      fixture derived from the real 64.62 evidence - they do not
#      assert a "corrected" value, because none is proven.
#
#   2. `WorkerRuntimeStatus` reporting STOPPED/UNCONFIGURED/DISCONNECTED
#      despite a genuinely connected, quote-receiving, bar-closing
#      session - root-caused to `_QuoteSink.aggregate_now()` calling
#      `WorkerHealthTracker.persist()` AFTER the `if not enabled:
#      return` early-exit, so a scanner configuration with
#      `enabled=False` (the MODEL DEFAULT for any never-configured
#      provider - see `ScannerConfiguration.enabled`) silently skipped
#      every persist() call for the entire session, leaving the row's
#      worker_state/token_state/watchdog_state/last_packet_at/
#      last_bar_at at the Django model's own field defaults (which is
#      EXACTLY what 64.62 observed). Fixed by moving the persist() call
#      before that gate - see `run_market_data_worker.py`.
#
#   3. `AggregatedBarObservation` -> canonical `Bar` compatibility -
#      an adapter ALREADY existed
#      (`domain.market_data.aggregation.AggregatedBar.to_bar()`,
#      reached via `live_market_data_repositories.py::
#      _row_to_aggregated_bar()` + `.to_bar()`), not previously proven
#      by a dedicated test. Volume is honestly `Decimal("0")`
#      (documented as "never fabricated," not a real traded-volume
#      figure - live aggregation is built from LTP-only ticks/quotes
#      with no per-bar volume signal), quality reuses the EXISTING
#      `MarketDataQuality` enum (`OK`), adjustment is `PriceAdjustment.
#      RAW` (live ticks genuinely are unadjusted prices) - no new
#      enum, no fabricated value.
#
# Also verifies the quality/strategy-execution separation the
# directive asked to investigate: `promote_bars_and_trigger_signals()`
# ALREADY calls `evaluate_bar_promotion()` (the TRADING_GRADE_BAR gate)
# unconditionally, before checking `strategy_execution_enabled` - a
# bar can be graded/promoted with zero strategies ever invoked. No
# redesign was needed there; this is a regression-locking test, not a
# new architecture.
#
# REAL_SESSION_FORENSIC_FIXTURE: every timestamp/price value below
# labeled as such is taken directly from `taskReport.md`'s own 64.62
# evidence section (ids 65-68, the confirmed-live batch) - NOT
# production live-feed traffic, NOT credential material, NOT a
# fabricated value. Symbols/prices are real, publicly-observed NSE
# quotes from that session; no account ID, token, or secret appears
# anywhere in this file.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import AggregatedBar, BarStatus
from intraday.domain.market_data.contracts import MarketDataQuality, PriceAdjustment
from intraday.domain.market_data.promotion import PromotionCondition
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    _HEADER_STRUCT,
    _TICKER_BODY_STRUCT,
    DhanFeedResponseCode,
    decode_packet,
)
from intraday.infrastructure.market_data_providers.dhan.timestamp_normalization import (
    normalize_dhan_websocket_timestamp,
)
from intraday.infrastructure.persistence.live_market_data_repositories import (
    _row_to_aggregated_bar,
)

# ---------------------------------------------------------------------------
# TIMESTAMP FORENSICS
# ---------------------------------------------------------------------------


def _build_ticker_packet(*, ltp: float, ltt_epoch: int, security_id: int = 1333) -> bytes:
    """A syntactically valid Ticker (code 2) packet, built the same way
    `packet_decoder.py`'s own test suite already does - used here only
    to characterize decode behaviour, never to open a connection."""
    header = _HEADER_STRUCT.pack(int(DhanFeedResponseCode.TICKER), 8, 1, security_id)
    body = _TICKER_BODY_STRUCT.pack(ltp, ltt_epoch)
    return header + body


class TestTimestampForensics:
    def test_a_decoder_normalizes_ltt_from_ist_labelled_epoch_to_utc(self) -> None:
        """UPDATED AT CHECKPOINT 64.71 - deliberately, with proof.

        This test previously locked in the raw
        `datetime.fromtimestamp(ltt_epoch, tz=UTC)` reading, on the
        grounds that Dhan's public docs say "Last Trade Time (EPOCH)"
        with no timezone caveat, and that no checkpoint should change
        decode semantics WITHOUT evidence. That guard did its job: the
        semantics are changing now precisely because the evidence
        finally exists.

        Checkpoint 64.70 collected 2,154 real observations from a live
        Dhan WebSocket session. Every single one had a decoded
        `source_timestamp` ahead of its actual receipt instant by
        19,799.25s (mean, stdev 0.385s) - exactly the 19,800s IST
        offset, to within tick latency. Dhan's WebSocket LTT epoch
        counts from the Unix epoch as if IST wall-clock time were UTC.
        Reading it raw therefore produced timestamps 5h30m in the
        FUTURE, which the aggregation guard correctly rejected - and
        which is why ZERO bars formed in that entire live session.

        The correction lives in ONE place
        (`timestamp_normalization.normalize_dhan_websocket_timestamp`),
        at the provider boundary, upstream of the canonical domain.
        See `tests/unit/research/
        test_checkpoint_64_71_dhan_timestamp_normalization.py` for the
        full 2,154-sample regression."""
        known_epoch = 1_700_000_000  # as sent by Dhan: an IST-labelled epoch
        packet = _build_ticker_packet(ltp=100.0, ltt_epoch=known_epoch)
        decoded = decode_packet(packet)
        assert decoded.last_trade_time == normalize_dhan_websocket_timestamp(known_epoch)
        # The raw reading is now exactly 5h30m LATER than what we decode.
        assert datetime.fromtimestamp(known_epoch, tz=UTC) - decoded.last_trade_time == timedelta(
            hours=5, minutes=30
        )
        # The canonical contract is unchanged: still timezone-aware UTC.
        assert decoded.last_trade_time.tzinfo is UTC

    def test_b_decoded_last_trade_time_is_always_timezone_aware_utc(self) -> None:
        packet = _build_ticker_packet(ltp=1304.10, ltt_epoch=1_756_000_000)
        decoded = decode_packet(packet)
        assert decoded.last_trade_time.utcoffset() == timedelta(0)

    def test_c_no_double_timezone_conversion_is_applied_by_the_decoder(self) -> None:
        """`fromtimestamp(x, tz=UTC)` is applied EXACTLY ONCE - decoding
        the same raw epoch integer twice must yield the identical
        instant, proving the decoder itself never re-interprets or
        re-shifts an already-converted value."""
        epoch = 1_756_000_000
        first = decode_packet(_build_ticker_packet(ltp=1.0, ltt_epoch=epoch))
        second = decode_packet(_build_ticker_packet(ltp=1.0, ltt_epoch=epoch))
        assert first.last_trade_time == second.last_trade_time

    def test_d_source_timestamp_and_ingestion_timestamp_are_distinct_fields(self) -> None:
        """Mirrors `client.py::DhanQuoteObservation` (`source_timestamp`
        vs. `fetched_at`, two independently-set fields, never
        collapsed) - the decoder's own packet dataclass carries only
        `last_trade_time` (the provider/source value); ingestion time is
        never stamped by this module at all (that happens one layer up,
        in `packet_to_quote.py`/the worker's own `on_quote()`, using
        THIS process's own clock) - confirmed by inspecting the decoded
        packet's own fields."""
        packet = _build_ticker_packet(ltp=1.0, ltt_epoch=1_756_000_000)
        decoded = decode_packet(packet)
        field_names = set(decoded.__dataclass_fields__)
        assert "last_trade_time" in field_names
        assert "fetched_at" not in field_names  # ingestion time is a separate concern entirely

    def test_e_real_session_anomaly_is_reproducible_against_the_forensic_fixture(self) -> None:
        """REAL_SESSION_FORENSIC_FIXTURE: reconstructs the confirmed-live
        64.62 batch (id=65, RELIANCE, last=1304.10) using the REAL
        `source_timestamp` (2026-08-24 15:14:56+00:00, as decoded by the
        CURRENT, unchanged decoder) and the REAL `fetched_at`
        (2026-08-24 09:47:58.636041+00:00) from `taskReport.md`. This
        test documents, exactly, that the gap is ~5.5h and close to the
        IST/UTC offset - it does NOT assert this is "wrong," since no
        conclusive, source-backed root cause was established this
        checkpoint (see this file's own module docstring). A future
        checkpoint with a PROVEN fix should update this test to assert
        the corrected value, not this one."""
        # REAL_SESSION_FORENSIC_FIXTURE (taskReport.md, 64.62, confirmed-live id=65)
        source_timestamp = datetime(2026, 8, 24, 15, 14, 56, tzinfo=UTC)
        fetched_at = datetime(2026, 8, 24, 9, 47, 58, 636041, tzinfo=UTC)
        gap = source_timestamp - fetched_at
        india_standard_time_offset = timedelta(hours=5, minutes=30)
        # The gap is close to (within a few minutes of) the IST/UTC
        # offset - a real, reproducible, honestly-unexplained anomaly,
        # not a one-off fluke of a single row.
        assert abs(gap - india_standard_time_offset) < timedelta(minutes=10)


# ---------------------------------------------------------------------------
# CANONICAL BAR MAPPING
# ---------------------------------------------------------------------------


class TestCanonicalBarMapping:
    def _closed_aggregated_bar(self) -> AggregatedBar:
        instrument_id = make_instrument_id(Exchange.NSE, "RELIANCE")
        return AggregatedBar(
            instrument_id=instrument_id,
            timeframe=Timeframe.ONE_MINUTE,
            interval_start=datetime(2026, 8, 24, 9, 41, tzinfo=UTC),
            interval_end=datetime(2026, 8, 24, 9, 42, tzinfo=UTC),
            open=Decimal("1304.10"),  # REAL_SESSION_FORENSIC_FIXTURE price
            high=Decimal("1305.00"),
            low=Decimal("1303.50"),
            close=Decimal("1304.60"),
            status=BarStatus.CLOSED,
            observation_count=2,
            data_source="dhan",
        )

    def test_k_aggregated_bar_converts_cleanly_to_canonical_bar(self) -> None:
        bar = self._closed_aggregated_bar().to_bar()
        assert bar.instrument_id == make_instrument_id(Exchange.NSE, "RELIANCE")

    def test_l_volume_is_honestly_zero_not_fabricated(self) -> None:
        """Live LTP-only tick aggregation (Ticker/Quote-packet-derived
        `Quote`s, `packet_to_quote.py`) carries no per-bar traded-volume
        signal - `Quote` itself has no `volume` field (see that
        module's own docstring). `Bar.volume` requires a non-negative
        Decimal (never `None`) - `Decimal("0")` is the documented,
        non-fabricated placeholder (`aggregation.py::to_bar()`'s own
        docstring), not a claim that zero shares traded."""
        bar = self._closed_aggregated_bar().to_bar()
        assert bar.volume == Decimal("0")

    def test_m_quality_reuses_the_existing_market_data_quality_enum(self) -> None:
        bar = self._closed_aggregated_bar().to_bar()
        assert bar.quality is MarketDataQuality.OK
        assert isinstance(bar.quality, MarketDataQuality)

    def test_n_adjustment_is_raw_for_live_unadjusted_ticks(self) -> None:
        bar = self._closed_aggregated_bar().to_bar()
        assert bar.adjustment is PriceAdjustment.RAW

    def test_o_bar_timestamp_is_the_interval_end_and_stays_utc(self) -> None:
        aggregated = self._closed_aggregated_bar()
        bar = aggregated.to_bar()
        assert bar.timestamp == aggregated.interval_end
        assert bar.timestamp.utcoffset() == timedelta(0)

    def test_p_timeframe_is_preserved_through_conversion(self) -> None:
        bar = self._closed_aggregated_bar().to_bar()
        assert bar.timeframe is Timeframe.ONE_MINUTE

    def test_forming_bar_is_refused_not_silently_promoted(self) -> None:
        from intraday.domain.market_data.aggregation import IncompleteBarError

        forming = AggregatedBar(
            instrument_id=make_instrument_id(Exchange.NSE, "RELIANCE"),
            timeframe=Timeframe.ONE_MINUTE,
            interval_start=datetime(2026, 8, 24, 9, 41, tzinfo=UTC),
            interval_end=datetime(2026, 8, 24, 9, 42, tzinfo=UTC),
            open=Decimal("1304.10"),
            high=Decimal("1305.00"),
            low=Decimal("1303.50"),
            close=Decimal("1304.60"),
            status=BarStatus.FORMING,
            observation_count=1,
            data_source="dhan",
        )
        with pytest.raises(IncompleteBarError):
            forming.to_bar()

    def test_row_to_aggregated_bar_adapter_round_trips_the_persisted_shape(self) -> None:
        """Exercises the ACTUAL persistence-layer adapter
        (`live_market_data_repositories.py::_row_to_aggregated_bar`) a
        real `AggregatedBarObservation` row would flow through - a thin
        stand-in row object (same field names, no DB required) proves
        the adapter itself, independent of `to_bar()`, which is tested
        above."""

        class _Row:
            instrument_symbol = "RELIANCE"
            exchange = "NSE"
            timeframe = "1m"
            interval_start = datetime(2026, 8, 24, 9, 41, tzinfo=UTC)
            interval_end = datetime(2026, 8, 24, 9, 42, tzinfo=UTC)
            open_price = Decimal("1304.10")
            high_price = Decimal("1305.00")
            low_price = Decimal("1303.50")
            close_price = Decimal("1304.60")
            status = "CLOSED"
            observation_count = 2
            data_source = "dhan"
            # Checkpoint 64.64: `AggregatedBarObservation.volume` is a new
            # column added this checkpoint - this REST/point-sample
            # fixture never carried a `cumulative_volume`, so `0` remains
            # the honest, non-fabricated persisted value.
            volume = Decimal("0")

        aggregated = _row_to_aggregated_bar(_Row())  # type: ignore[arg-type]
        bar = aggregated.to_bar()
        assert bar.close == Decimal("1304.60")
        assert bar.volume == Decimal("0")
        assert bar.quality is MarketDataQuality.OK
        assert bar.adjustment is PriceAdjustment.RAW


# ---------------------------------------------------------------------------
# QUALITY / STRATEGY-EXECUTION SEPARATION
# ---------------------------------------------------------------------------


class TestQualityPromotionSeparation:
    def test_q_promotion_condition_vocabulary_has_no_strategy_concept(self) -> None:
        """`evaluate_bar_promotion()`'s own six conditions
        (`PromotionCondition`) are entirely about bar/session/connection
        facts - none of them name a strategy, a signal, or an order.
        Quality assessment is a pure, strategy-agnostic domain function
        (`domain/market_data/promotion.py`, no import of anything
        strategy/signal-related)."""
        names = {c.name for c in PromotionCondition}
        assert "STRATEGY" not in "".join(names)
        assert names == {
            "BAR_IS_CLOSED",
            "SESSION_IS_OPEN",
            "NO_DUPLICATE_OR_OUT_OF_ORDER",
            "NO_GAP_BEFORE_THIS_BAR",
            "CONNECTION_HEALTHY",
            "SUFFICIENT_OBSERVATIONS",
        }

    def test_r_promote_bars_grades_every_bar_even_with_strategy_execution_disabled(self) -> None:
        """`promote_bars_and_trigger_signals()` already calls
        `evaluate_bar_promotion()` UNCONDITIONALLY (before checking
        `strategy_execution_enabled`) - `promoted_count` reflects real
        TRADING_GRADE_BAR grading regardless of whether any strategy is
        ever invoked. This is a regression-locking test for existing,
        correct behaviour - no production code changed for this
        finding."""
        from intraday.domain.market_data.aggregation import BarAggregationResult
        from intraday.domain.session.calendar import session_for_instant
        from intraday.infrastructure.api.signal_pipeline_runtime import (
            promote_bars_and_trigger_signals,
        )

        instrument_id = make_instrument_id(Exchange.NSE, "RELIANCE")
        clock = datetime(2026, 8, 24, 9, 42, 1, tzinfo=UTC)  # inside real 09:15-15:30 IST hours
        bar = AggregatedBar(
            instrument_id=instrument_id,
            timeframe=Timeframe.ONE_MINUTE,
            interval_start=datetime(2026, 8, 24, 9, 41, tzinfo=UTC),
            interval_end=datetime(2026, 8, 24, 9, 42, tzinfo=UTC),
            open=Decimal("1304.10"),
            high=Decimal("1305.00"),
            low=Decimal("1303.50"),
            close=Decimal("1304.60"),
            status=BarStatus.CLOSED,
            observation_count=5,
            data_source="dhan",
        )
        session = session_for_instant(clock)
        aggregation = BarAggregationResult(
            bars=(bar,), missing_intervals=(), anomalous_observations=()
        )

        outcome = promote_bars_and_trigger_signals(
            aggregation,
            session=session,
            clock=clock,
            connection_is_healthy=True,
            strategy_execution_enabled=False,
        )
        assert outcome.promoted_count == 1
        assert outcome.active_loop_invocations == 0

    def test_s_strategy_pipeline_remains_optional_given_strategy_execution_enabled_true(
        self,
    ) -> None:
        """Sanity check on the flag's own meaning: with
        `strategy_execution_enabled=True` AND the SAME genuinely
        promotable bar, the strategy pipeline IS invoked - proving the
        `False` branch above is a real, deliberate skip, not an
        accidental no-op regardless of the flag. `run_active_loop_tick`
        itself needs real strategy configuration/DB fixtures well
        outside this checkpoint's scope to run end-to-end - patched here
        to a no-op probe so this test stays a pure, DB-free unit test of
        `promote_bars_and_trigger_signals()`'s own call-or-skip
        decision, not a strategy-engine integration test."""
        from unittest.mock import patch

        from intraday.domain.market_data.aggregation import BarAggregationResult
        from intraday.domain.session.calendar import session_for_instant
        from intraday.infrastructure.api import signal_pipeline_runtime

        instrument_id = make_instrument_id(Exchange.NSE, "RELIANCE")
        clock = datetime(2026, 8, 24, 9, 42, 1, tzinfo=UTC)
        bar = AggregatedBar(
            instrument_id=instrument_id,
            timeframe=Timeframe.ONE_MINUTE,
            interval_start=datetime(2026, 8, 24, 9, 41, tzinfo=UTC),
            interval_end=datetime(2026, 8, 24, 9, 42, tzinfo=UTC),
            open=Decimal("1304.10"),
            high=Decimal("1305.00"),
            low=Decimal("1303.50"),
            close=Decimal("1304.60"),
            status=BarStatus.CLOSED,
            observation_count=5,
            data_source="dhan",
        )
        session = session_for_instant(clock)
        aggregation = BarAggregationResult(
            bars=(bar,), missing_intervals=(), anomalous_observations=()
        )

        with patch.object(signal_pipeline_runtime, "run_active_loop_tick") as probe:
            outcome = signal_pipeline_runtime.promote_bars_and_trigger_signals(
                aggregation,
                session=session,
                clock=clock,
                connection_is_healthy=True,
                strategy_execution_enabled=True,
            )
        assert outcome.promoted_count == 1
        assert outcome.active_loop_invocations == 1
        probe.assert_called_once()


# ---------------------------------------------------------------------------
# WORKER RUNTIME STATUS
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestWorkerRuntimeStatus:
    """Root cause (confirmed against real 64.62 evidence + source):
    `_QuoteSink.aggregate_now()` used to call
    `WorkerHealthTracker.persist()` (the ONLY write path that sets
    worker_state/token_state/watchdog_state/last_packet_at/last_bar_at
    from the tracker's real in-memory state) AFTER
    `if not enabled: return`. `ScannerConfiguration.enabled` defaults to
    `False` at the MODEL level (`models.py::ScannerConfiguration.
    enabled = models.BooleanField(default=False)`) for any
    never-explicitly-enabled provider - so on a fresh/never-configured
    scanner, `persist()` was skipped for the ENTIRE session, and the
    row's health columns were instead first populated by
    `save_effective_scanner_state()`'s own `update_or_create()` (called
    just above the gate), whose `defaults` dict never mentions those
    columns - Django's `get_or_create` leaves them at the MODEL's own
    field defaults (STOPPED/UNCONFIGURED/DISCONNECTED/None/None),
    exactly reproducing the row 64.62 captured. Fixed by moving the
    `persist()` call before the `enabled` gate (see
    `run_market_data_worker.py`)."""

    def test_e_healthy_running_state_persists_correctly(self) -> None:
        from intraday.infrastructure.market_data_providers.dhan.worker_health_tracker import (
            WorkerHealthTracker,
        )
        from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState
        from intraday.infrastructure.persistence.worker_runtime_status_repository import (
            DjangoWorkerRuntimeStatusRepository,
        )

        repository = DjangoWorkerRuntimeStatusRepository()
        tracker = WorkerHealthTracker()
        now = datetime(2026, 8, 24, 9, 50, 0, tzinfo=UTC)
        tracker.mark_token_state("VALID")
        tracker.mark_connected(subscribed_instrument_count=4)
        tracker.record_packet(now=now)
        tracker.record_bar(now=now)

        tracker.persist(repository, provider="test_64_63_connected", now=now)

        record = repository.get("test_64_63_connected")
        assert record is not None
        assert record.worker_state == WorkerState.RUNNING.value
        assert record.token_state == "VALID"  # noqa: S105 - a state label, not a credential
        assert record.last_packet_at == now
        assert record.last_bar_at == now

    def test_f_receiving_packets_but_no_bar_yet_is_not_reported_as_stopped(self) -> None:
        from intraday.infrastructure.market_data_providers.dhan.worker_health_tracker import (
            WorkerHealthTracker,
        )
        from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState
        from intraday.infrastructure.persistence.worker_runtime_status_repository import (
            DjangoWorkerRuntimeStatusRepository,
        )

        repository = DjangoWorkerRuntimeStatusRepository()
        tracker = WorkerHealthTracker()
        now = datetime(2026, 8, 24, 9, 48, 0, tzinfo=UTC)
        tracker.mark_token_state("VALID")
        tracker.mark_connected(subscribed_instrument_count=4)
        tracker.record_packet(now=now)

        tracker.persist(repository, provider="test_64_63_receiving", now=now)

        record = repository.get("test_64_63_receiving")
        assert record is not None
        assert record.worker_state == WorkerState.RUNNING.value
        assert record.last_packet_at == now

    def test_g_stale_packets_are_reflected_by_a_stale_watchdog_state(self) -> None:
        from intraday.control_plane.market_data_watchdog.contracts import MarketDataWatchdogState
        from intraday.infrastructure.market_data_providers.dhan.worker_health_tracker import (
            WorkerHealthTracker,
        )
        from intraday.infrastructure.persistence.worker_runtime_status_repository import (
            DjangoWorkerRuntimeStatusRepository,
        )

        repository = DjangoWorkerRuntimeStatusRepository()
        tracker = WorkerHealthTracker()
        packet_time = datetime(2026, 8, 24, 9, 0, 0, tzinfo=UTC)
        evaluation_time = packet_time + timedelta(minutes=5)  # past STALE_PACKET_AGE (30s)
        tracker.mark_token_state("VALID")
        tracker.mark_connected(subscribed_instrument_count=4)
        tracker.record_packet(now=packet_time)

        tracker.persist(repository, provider="test_64_63_stale", now=evaluation_time)

        record = repository.get("test_64_63_stale")
        assert record is not None
        assert record.watchdog_state == MarketDataWatchdogState.STALE.value

    def test_h_stopped_worker_persists_a_truthful_stopped_state(self) -> None:
        from intraday.infrastructure.market_data_providers.dhan.worker_health_tracker import (
            WorkerHealthTracker,
        )
        from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState
        from intraday.infrastructure.persistence.worker_runtime_status_repository import (
            DjangoWorkerRuntimeStatusRepository,
        )

        repository = DjangoWorkerRuntimeStatusRepository()
        tracker = WorkerHealthTracker()  # never connected - genuinely STOPPED
        now = datetime(2026, 8, 24, 9, 0, 0, tzinfo=UTC)

        tracker.persist(repository, provider="test_64_63_stopped", now=now)

        record = repository.get("test_64_63_stopped")
        assert record is not None
        assert record.worker_state == WorkerState.STOPPED.value

    def test_i_persisted_runtime_status_matches_real_in_memory_tracker_state(self) -> None:
        """The exact regression this checkpoint fixes: a `persist()`
        call made AFTER a genuinely connected/healthy tracker state must
        never be silently skipped by an unrelated administrative flag -
        this test exercises `persist()` directly (the fixed call site
        now calls it unconditionally in `run_market_data_worker.py`) and
        confirms the row genuinely reflects RUNNING/VALID, not the
        Django model's own STOPPED/UNCONFIGURED/DISCONNECTED defaults."""
        from intraday.infrastructure.market_data_providers.dhan.worker_health_tracker import (
            WorkerHealthTracker,
        )
        from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState
        from intraday.infrastructure.persistence.worker_runtime_status_repository import (
            DjangoWorkerRuntimeStatusRepository,
        )

        repository = DjangoWorkerRuntimeStatusRepository()
        tracker = WorkerHealthTracker()
        now = datetime(2026, 8, 24, 9, 50, 0, tzinfo=UTC)
        tracker.mark_token_state("VALID")
        tracker.mark_connected(subscribed_instrument_count=4)
        tracker.record_packet(now=now)
        tracker.record_bar(now=now)

        # Simulate the OLD bug's mechanism first: a bare
        # `save_effective_scanner_state()` write (as happens every
        # cycle, unconditionally) reaching an as-yet-untouched row -
        # this alone must NOT be mistaken for a health write.
        repository.save_effective_scanner_state(
            "test_64_63_regression",
            effective_configuration_version=1,
            effective_timeframe="1m",
            effective_strategy_ids=["ema_crossover"],
            effective_universe_requested_count=4,
            effective_universe_subscribed_count=4,
        )
        pre_fix_row = repository.get("test_64_63_regression")
        assert pre_fix_row is not None
        # This alone leaves worker_state at the MODEL default - exactly
        # 64.62's own observed (buggy) row shape.
        assert pre_fix_row.worker_state == WorkerState.STOPPED.value
        assert pre_fix_row.token_state == "UNCONFIGURED"  # noqa: S105 - a state label, not a credential

        # Now the FIXED code path: persist() must be reachable (and, per
        # the source fix, IS now called) regardless of `enabled` -
        # exercised directly here since `enabled` never gates this
        # repository call itself, only whether the worker command
        # bothers to invoke it.
        tracker.persist(repository, provider="test_64_63_regression", now=now)

        post_fix_row = repository.get("test_64_63_regression")
        assert post_fix_row is not None
        assert post_fix_row.worker_state == WorkerState.RUNNING.value
        assert post_fix_row.token_state == "VALID"  # noqa: S105 - a state label, not a credential
        assert post_fix_row.last_packet_at == now
        assert post_fix_row.last_bar_at == now

    def test_j_no_false_unconfigured_token_state_when_credential_is_valid(self) -> None:
        from intraday.infrastructure.market_data_providers.dhan.worker_health_tracker import (
            WorkerHealthTracker,
        )
        from intraday.infrastructure.persistence.worker_runtime_status_repository import (
            DjangoWorkerRuntimeStatusRepository,
        )

        repository = DjangoWorkerRuntimeStatusRepository()
        tracker = WorkerHealthTracker()
        tracker.mark_token_state("VALID")
        now = datetime(2026, 8, 24, 9, 0, 0, tzinfo=UTC)
        tracker.persist(repository, provider="test_64_63_valid_token", now=now)

        record = repository.get("test_64_63_valid_token")
        assert record.token_state == "VALID"  # noqa: S105 - a state label, not a credential
        assert record.token_state != "UNCONFIGURED"  # noqa: S105 - a state label, not a credential

    def test_fix_moves_persist_before_the_enabled_gate_in_source(self) -> None:
        """Locks in the exact source-level fix location, so a future
        refactor cannot silently re-introduce the bug by moving
        `health_tracker.persist(...)` back below `if not enabled:
        return` without this test failing."""
        import inspect

        from intraday.infrastructure.persistence.management.commands import (
            run_market_data_worker,
        )

        source = inspect.getsource(run_market_data_worker)
        persist_index = source.index("await sync_to_async(self.health_tracker.persist)")
        enabled_gate_index = source.index("        if not enabled:\n")
        assert persist_index < enabled_gate_index, (
            "health_tracker.persist() must run BEFORE the `if not enabled:` gate - "
            "moving it back below reintroduces the 64.62 WorkerRuntimeStatus bug"
        )
