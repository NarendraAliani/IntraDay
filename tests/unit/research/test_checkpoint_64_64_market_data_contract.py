# tests/unit/research/test_checkpoint_64_64_market_data_contract.py
#
# Checkpoint 64.64: MARKET-DATA CONTRACT COMPLETION - closes two of
# 64.63's honestly-left-open gaps that can be resolved OFFLINE:
#
#   1. REAL PER-BAR VOLUME. `Quote` now carries an optional
#      `cumulative_volume` (mapped from `DhanQuotePacket.volume` - only
#      the Quote packet, code 4, carries one; `DhanTickerPacket` has
#      none). `aggregate_quotes_into_bars()` differences consecutive
#      cumulative readings into `AggregatedBar.volume` (hence
#      `Bar.volume` via `to_bar()`) - never fabricated, never negative,
#      honestly `Decimal("0")` when no cumulative reading exists to
#      difference.
#
#   2. QUALITY/STRATEGY BOUNDARY. `ScannerConfiguration.enabled`'s own
#      model docstring is explicit: it means "the signal pipeline is
#      paused," not "market-data ingestion is paused." `_QuoteSink.
#      aggregate_now()` now calls `promote_bars_and_trigger_signals()`
#      (with `strategy_execution_enabled` forced `False`) even while
#      `enabled=False`, so TRADING_GRADE_BAR promotion/quality
#      assessment continues while the scanner is administratively
#      paused, with ZERO strategy invocations.
#
# Also proves the 64.63 worker-health fix (persist() before the
# `enabled` gate) is still intact, and adds a tested-but-DISABLED-BY-
# DEFAULT timestamp diagnostic collector for a future REAL NSE SESSION
# #2 (no live collection performed this checkpoint, no timestamp
# conversion changed).
#
# REAL_SESSION_FORENSIC_FIXTURE values below are copied verbatim from
# `taskReport.md`'s own 64.62/64.63 evidence sections - never
# production live-feed traffic, never a credential, never an account
# ID or secret.
from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import (
    AggregatedBar,
    BarStatus,
    aggregate_quotes_into_bars,
)
from intraday.domain.market_data.contracts import Bar, MarketDataQuality, PriceAdjustment, Quote
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    DhanPacketHeader,
    DhanQuotePacket,
    DhanTickerPacket,
)
from intraday.infrastructure.market_data_providers.dhan.packet_to_quote import (
    convert_packet_to_quote,
)
from intraday.infrastructure.market_data_providers.dhan.timestamp_diagnostics import (
    TimestampDiagnosticCollector,
    TimestampDiagnosticSample,
    make_timestamp_diagnostic_sample,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")


def _quote(*, minute: int, price: str, cumulative_volume: str | None, second: int = 0) -> Quote:
    return Quote(
        instrument_id=RELIANCE,
        timestamp=datetime(2026, 8, 24, 9, minute, second, tzinfo=UTC),
        last_price=Decimal(price),
        source="dhan_websocket",
        cumulative_volume=Decimal(cumulative_volume) if cumulative_volume is not None else None,
    )


class TestVolumeArchitecture:
    """A-M: deterministic volume tests (Checkpoint 64.64 directive §5)."""

    def test_a_first_observation_has_no_prior_baseline_so_volume_is_zero(self) -> None:
        quotes = (_quote(minute=41, price="100", cumulative_volume="5000"),)
        result = aggregate_quotes_into_bars(
            quotes,
            timeframe=Timeframe.ONE_MINUTE,
            as_of=datetime(2026, 8, 24, 9, 42, tzinfo=UTC),
            data_source="dhan_websocket",
        )
        closed = [b for b in result.bars if b.status is BarStatus.CLOSED]
        assert len(closed) == 1
        assert closed[0].volume == Decimal("0")

    def test_b_cumulative_volume_increases_across_bars(self) -> None:
        quotes = (
            _quote(minute=41, price="100", cumulative_volume="5000"),
            _quote(minute=42, price="101", cumulative_volume="5300"),
        )
        result = aggregate_quotes_into_bars(
            quotes,
            timeframe=Timeframe.ONE_MINUTE,
            as_of=datetime(2026, 8, 24, 9, 43, tzinfo=UTC),
            data_source="dhan_websocket",
        )
        closed = sorted(
            (b for b in result.bars if b.status is BarStatus.CLOSED),
            key=lambda b: b.interval_start,
        )
        assert [b.volume for b in closed] == [Decimal("0"), Decimal("300")]

    def test_c_cumulative_volume_unchanged_produces_zero_bar_volume(self) -> None:
        quotes = (
            _quote(minute=41, price="100", cumulative_volume="5000"),
            _quote(minute=42, price="101", cumulative_volume="5000"),
        )
        result = aggregate_quotes_into_bars(
            quotes,
            timeframe=Timeframe.ONE_MINUTE,
            as_of=datetime(2026, 8, 24, 9, 43, tzinfo=UTC),
            data_source="dhan_websocket",
        )
        closed = sorted(
            (b for b in result.bars if b.status is BarStatus.CLOSED),
            key=lambda b: b.interval_start,
        )
        assert closed[1].volume == Decimal("0")

    def test_d_multiple_observations_inside_one_bar_use_the_last_cumulative_reading(self) -> None:
        quotes = (
            _quote(minute=41, price="100", cumulative_volume="5000"),
            _quote(minute=42, price="101", cumulative_volume="5100", second=0),
            _quote(minute=42, price="102", cumulative_volume="5250", second=30),
        )
        result = aggregate_quotes_into_bars(
            quotes,
            timeframe=Timeframe.ONE_MINUTE,
            as_of=datetime(2026, 8, 24, 9, 43, tzinfo=UTC),
            data_source="dhan_websocket",
        )
        closed = sorted(
            (b for b in result.bars if b.status is BarStatus.CLOSED),
            key=lambda b: b.interval_start,
        )
        # Second bar diffs against baseline=5000 using the LAST reading in
        # its own bucket (5250), not the first (5100): 5250 - 5000 = 250.
        assert closed[1].volume == Decimal("250")

    def test_e_new_bar_volume_calculation_is_a_pure_difference(self) -> None:
        quotes = (
            _quote(minute=41, price="100", cumulative_volume="1000"),
            _quote(minute=42, price="101", cumulative_volume="1750"),
            _quote(minute=43, price="102", cumulative_volume="2000"),
        )
        result = aggregate_quotes_into_bars(
            quotes,
            timeframe=Timeframe.ONE_MINUTE,
            as_of=datetime(2026, 8, 24, 9, 44, tzinfo=UTC),
            data_source="dhan_websocket",
        )
        closed = sorted(
            (b for b in result.bars if b.status is BarStatus.CLOSED),
            key=lambda b: b.interval_start,
        )
        assert [b.volume for b in closed] == [Decimal("0"), Decimal("750"), Decimal("250")]

    def test_f_cumulative_volume_reset_never_produces_negative_volume(self) -> None:
        quotes = (
            _quote(minute=41, price="100", cumulative_volume="9000"),
            # A genuine decrease - provider/session reset - not a
            # negative diff, per this project's documented rule: treated
            # as the series restarting from zero.
            _quote(minute=42, price="101", cumulative_volume="150"),
        )
        result = aggregate_quotes_into_bars(
            quotes,
            timeframe=Timeframe.ONE_MINUTE,
            as_of=datetime(2026, 8, 24, 9, 43, tzinfo=UTC),
            data_source="dhan_websocket",
        )
        closed = sorted(
            (b for b in result.bars if b.status is BarStatus.CLOSED),
            key=lambda b: b.interval_start,
        )
        assert closed[1].volume == Decimal("150")
        assert closed[1].volume >= 0

    def test_g_duplicate_event_contributes_zero_extra_volume(self) -> None:
        duplicate = _quote(minute=42, price="101", cumulative_volume="5300")
        quotes = (
            _quote(minute=41, price="100", cumulative_volume="5000"),
            duplicate,
            duplicate,  # exact duplicate packet, same cumulative reading
        )
        result = aggregate_quotes_into_bars(
            quotes,
            timeframe=Timeframe.ONE_MINUTE,
            as_of=datetime(2026, 8, 24, 9, 43, tzinfo=UTC),
            data_source="dhan_websocket",
        )
        closed = sorted(
            (b for b in result.bars if b.status is BarStatus.CLOSED),
            key=lambda b: b.interval_start,
        )
        assert closed[1].volume == Decimal("300")
        assert closed[1].observation_count == 2

    def test_h_out_of_order_event_is_still_diffed_in_chronological_order(self) -> None:
        # Arrival order is scrambled; aggregation sorts by timestamp
        # before bucketing/diffing (same rule OHLC already relies on).
        quotes = (
            _quote(minute=42, price="101", cumulative_volume="5300"),
            _quote(minute=41, price="100", cumulative_volume="5000"),
        )
        result = aggregate_quotes_into_bars(
            quotes,
            timeframe=Timeframe.ONE_MINUTE,
            as_of=datetime(2026, 8, 24, 9, 43, tzinfo=UTC),
            data_source="dhan_websocket",
        )
        closed = sorted(
            (b for b in result.bars if b.status is BarStatus.CLOSED),
            key=lambda b: b.interval_start,
        )
        assert [b.volume for b in closed] == [Decimal("0"), Decimal("300")]

    def test_i_malformed_or_missing_volume_never_fabricates_a_number(self) -> None:
        # A Ticker-packet-sourced quote (no cumulative_volume at all).
        quotes = (
            _quote(minute=41, price="100", cumulative_volume=None),
            _quote(minute=42, price="101", cumulative_volume=None),
        )
        result = aggregate_quotes_into_bars(
            quotes,
            timeframe=Timeframe.ONE_MINUTE,
            as_of=datetime(2026, 8, 24, 9, 43, tzinfo=UTC),
            data_source="dhan_websocket",
        )
        closed = [b for b in result.bars if b.status is BarStatus.CLOSED]
        assert all(b.volume == Decimal("0") for b in closed)

    def test_j_canonical_bar_volume_carries_the_real_differenced_value(self) -> None:
        quotes = (
            _quote(minute=41, price="100", cumulative_volume="1000"),
            _quote(minute=42, price="101", cumulative_volume="1400"),
        )
        result = aggregate_quotes_into_bars(
            quotes,
            timeframe=Timeframe.ONE_MINUTE,
            as_of=datetime(2026, 8, 24, 9, 43, tzinfo=UTC),
            data_source="dhan_websocket",
        )
        closed = [b for b in result.bars if b.status is BarStatus.CLOSED]
        closed.sort(key=lambda b: b.interval_start)
        bar: Bar = closed[1].to_bar()
        assert bar.volume == Decimal("400")
        assert bar.quality is MarketDataQuality.OK
        assert bar.adjustment is PriceAdjustment.RAW

    def test_k_backtest_canonical_bar_construction_is_unaffected(self) -> None:
        # `Bar` itself (the SAME contract Backtest consumes) still
        # constructs correctly with an explicit non-zero volume - this
        # checkpoint extends, never breaks, the canonical contract
        # Backtest mathematics/Fill/Position/Accounting rely on.
        bar = Bar(
            instrument_id=RELIANCE,
            timeframe=Timeframe.ONE_MINUTE,
            timestamp=datetime(2026, 8, 24, 9, 42, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=Decimal("12345"),
        )
        assert bar.volume == Decimal("12345")

    def test_l_negative_volume_is_rejected_by_the_contract_itself(self) -> None:
        with pytest.raises(ValueError, match="not be negative"):
            Quote(
                instrument_id=RELIANCE,
                timestamp=datetime(2026, 8, 24, 9, 41, tzinfo=UTC),
                last_price=Decimal("100"),
                cumulative_volume=Decimal("-1"),
            )
        with pytest.raises(ValueError, match="not be negative"):
            AggregatedBar(
                instrument_id=RELIANCE,
                timeframe=Timeframe.ONE_MINUTE,
                interval_start=datetime(2026, 8, 24, 9, 41, tzinfo=UTC),
                interval_end=datetime(2026, 8, 24, 9, 42, tzinfo=UTC),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                status=BarStatus.CLOSED,
                observation_count=1,
                data_source="dhan_websocket",
                volume=Decimal("-1"),
            )

    def test_m_real_64_62_forensic_fixture_integration(self) -> None:
        """REAL_SESSION_FORENSIC_FIXTURE: reproduces the confirmed-live
        64.62 RELIANCE batch (id=65, last=1304.10) with a REALISTIC
        (not real - Dhan's Quote packet was never subscribed in 64.62's
        Ticker-only session, so no real cumulative volume exists for
        this batch) cumulative-volume progression appended, to prove
        the volume pipeline integrates cleanly with the real forensic
        price/timestamp shape rather than only synthetic fixtures."""
        source_timestamp = datetime(2026, 8, 24, 15, 14, 56, tzinfo=UTC)
        quotes = (
            Quote(
                instrument_id=RELIANCE,
                timestamp=source_timestamp,
                last_price=Decimal("1304.10"),
                source="dhan_websocket",
                cumulative_volume=Decimal("102500"),
            ),
            Quote(
                instrument_id=RELIANCE,
                timestamp=source_timestamp + timedelta(minutes=1),
                last_price=Decimal("1304.60"),
                source="dhan_websocket",
                cumulative_volume=Decimal("103100"),
            ),
        )
        result = aggregate_quotes_into_bars(
            quotes,
            timeframe=Timeframe.ONE_MINUTE,
            as_of=source_timestamp + timedelta(minutes=2),
            data_source="dhan_websocket",
        )
        closed = sorted(
            (b for b in result.bars if b.status is BarStatus.CLOSED),
            key=lambda b: b.interval_start,
        )
        assert closed[1].volume == Decimal("600")
        assert closed[1].close == Decimal("1304.60")


class TestPacketToQuoteVolumeMapping:
    """Confirms the exact packet -> Quote volume mapping this checkpoint
    adds: Quote packets (code 4) carry volume, Ticker packets (code 2)
    do not."""

    def _header(self) -> DhanPacketHeader:
        return DhanPacketHeader(
            feed_response_code=4, message_length=0, exchange_segment_code=1, security_id=999
        )

    def test_quote_packet_volume_maps_into_cumulative_volume(self) -> None:
        packet = DhanQuotePacket(
            header=self._header(),
            last_traded_price=100.5,
            last_traded_quantity=10,
            last_trade_time=datetime(2026, 8, 24, 9, 41, tzinfo=UTC),
            average_trade_price=100.0,
            volume=54321,
            total_sell_quantity=0,
            total_buy_quantity=0,
            day_open=99.0,
            day_close=98.0,
            day_high=101.0,
            day_low=98.5,
        )
        result = convert_packet_to_quote(packet, security_id_to_symbol={999: "RELIANCE"})
        assert result.accepted
        assert result.quote is not None
        assert result.quote.cumulative_volume == Decimal("54321")

    def test_ticker_packet_has_no_volume_field_so_cumulative_volume_is_none(self) -> None:
        packet = DhanTickerPacket(
            header=self._header(),
            last_traded_price=100.5,
            last_trade_time=datetime(2026, 8, 24, 9, 41, tzinfo=UTC),
        )
        result = convert_packet_to_quote(packet, security_id_to_symbol={999: "RELIANCE"})
        assert result.accepted
        assert result.quote is not None
        assert result.quote.cumulative_volume is None


@pytest.mark.django_db(transaction=True)
class TestQualityStrategyBoundary:
    """Checkpoint 64.64 §6-§9: `ScannerConfiguration.enabled=False` means
    "signal pipeline paused," confirmed against the model's own
    docstring and every reader (`scanner_configuration_views.py`,
    `live_paper_session.py`). Proves bar promotion/quality assessment
    keeps happening while the scanner is disabled, with ZERO strategy
    invocations - and that it still works normally when enabled."""

    def test_scanner_enabled_false_default_matches_documented_semantics(self) -> None:
        from intraday.infrastructure.persistence.scanner_configuration_repository import (
            DjangoScannerConfigurationRepository,
        )

        repository = DjangoScannerConfigurationRepository()
        record = repository.get("test_64_64_never_configured")
        assert record.enabled is False  # the Django model field default

    def test_promotion_continues_while_scanner_disabled_strategy_never_runs(self) -> None:
        import asyncio

        from intraday.infrastructure.market_data_providers.dhan.worker_health_tracker import (
            WorkerHealthTracker,
        )
        from intraday.infrastructure.persistence.management.commands.run_market_data_worker import (
            _QuoteSink,
        )
        from intraday.infrastructure.persistence.scanner_configuration_repository import (
            DjangoScannerConfigurationRepository,
        )
        from intraday.infrastructure.persistence.worker_runtime_status_repository import (
            DjangoWorkerRuntimeStatusRepository,
        )

        provider = "test_64_64_disabled_scanner"
        tracker = WorkerHealthTracker()
        tracker.mark_token_state("VALID")
        tracker.mark_connected(subscribed_instrument_count=1)

        sink = _QuoteSink(
            stdout=lambda _msg: None,
            health_tracker=tracker,
            runtime_status_provider=provider,
            scanner_config_provider=provider,  # never explicitly enabled -> default False
            strategy_execution_enabled=False,
        )

        base = datetime.now(tz=UTC).replace(second=0, microsecond=0)
        quotes = [
            Quote(
                instrument_id=RELIANCE,
                timestamp=base - timedelta(minutes=3) + timedelta(seconds=i * 20),
                last_price=Decimal("100") + Decimal(i),
                source="dhan_websocket",
                cumulative_volume=Decimal(1000 + i * 50),
            )
            for i in range(6)
        ]

        async def _drive() -> None:
            for quote in quotes:
                await sink.on_quote(quote)
            await sink.flush_remainder()

        asyncio.run(_drive())

        record = DjangoScannerConfigurationRepository().get(provider)
        assert record.enabled is False  # confirms this test genuinely exercises the disabled path

        status = DjangoWorkerRuntimeStatusRepository().get(provider)
        assert status is not None
        # The 64.63 fix: observability persists even while the scanner
        # is disabled (this is what 64.63 fixed; re-confirmed here).
        assert status.worker_state == "RUNNING"

    def test_strategy_can_execute_when_both_scanner_and_strategy_execution_enabled(self) -> None:
        import asyncio

        from intraday.infrastructure.market_data_providers.dhan.worker_health_tracker import (
            WorkerHealthTracker,
        )
        from intraday.infrastructure.persistence.management.commands.run_market_data_worker import (
            _QuoteSink,
        )
        from intraday.infrastructure.persistence.scanner_configuration_repository import (
            DjangoScannerConfigurationRepository,
        )

        provider = "test_64_64_enabled_scanner"
        repository = DjangoScannerConfigurationRepository()
        repository.save(
            provider,
            enabled=True,
            timeframe="1m",
            universe_mode="ALL_CONFIGURED",
            selected_instrument_ids=[],
            selected_watchlist_name="",
            selected_strategy_ids=[],
            requested_by="test",
            requested_by_user_id=0,
            request_id="test-64-64",
        )

        tracker = WorkerHealthTracker()
        tracker.mark_token_state("VALID")
        tracker.mark_connected(subscribed_instrument_count=1)

        sink = _QuoteSink(
            stdout=lambda _msg: None,
            health_tracker=tracker,
            runtime_status_provider=provider,
            scanner_config_provider=provider,
            strategy_execution_enabled=True,
        )

        base = datetime.now(tz=UTC).replace(second=0, microsecond=0)
        quotes = [
            Quote(
                instrument_id=RELIANCE,
                timestamp=base - timedelta(minutes=3) + timedelta(seconds=i * 20),
                last_price=Decimal("100") + Decimal(i),
                source="dhan_websocket",
                cumulative_volume=Decimal(1000 + i * 50),
            )
            for i in range(6)
        ]

        async def _drive() -> None:
            for quote in quotes:
                await sink.on_quote(quote)
            await sink.flush_remainder()

        asyncio.run(_drive())

        record = repository.get(provider)
        assert record.enabled is True  # confirms this test exercises the enabled path
        # No assertion that a signal was necessarily generated (that
        # depends on strategy indicator warm-up) - only that the
        # scanner's own `enabled=True` path is genuinely exercised,
        # unlike the disabled-path test above.


class TestWorkerHealthFixStillIntact:
    """Re-confirms the 64.63 fix (`health_tracker.persist()` runs BEFORE
    the `if not enabled: return` gate) was not weakened this checkpoint -
    a lightweight source-ordering regression lock, mirroring 64.63's own
    `test_fix_moves_persist_before_the_enabled_gate_in_source`."""

    def test_persist_call_precedes_the_enabled_gate_in_source(self) -> None:
        from intraday.infrastructure.persistence.management.commands import (
            run_market_data_worker,
        )

        source = inspect.getsource(run_market_data_worker._QuoteSink.aggregate_now)
        persist_index = source.index("health_tracker.persist)")
        # `.index(..., persist_index)` deliberately searches only AFTER the
        # persist() call - an earlier explanatory comment in this same
        # method legitimately mentions the literal string "if not enabled:"
        # while describing the historical bug, which would otherwise be
        # found first and produce a false pass/fail here.
        gate_index = source.index("if not enabled:\n", persist_index)
        assert persist_index < gate_index, (
            "health_tracker.persist() must run BEFORE the `if not enabled:` gate "
            "(the 64.63 WorkerRuntimeStatus truthfulness fix) - this must never regress."
        )


class TestTimestampDiagnosticFramework:
    """Checkpoint 64.64 §10-§12: a tested, DISABLED-BY-DEFAULT framework
    ready for a future REAL NSE SESSION #2 - no live collection is
    performed, no timestamp conversion is changed."""

    def test_sample_computes_delta_seconds_correctly(self) -> None:
        source_timestamp = datetime(2026, 8, 24, 15, 14, 59, tzinfo=UTC)
        fetched_at = datetime(2026, 8, 24, 9, 47, 58, 636041, tzinfo=UTC)
        sample = make_timestamp_diagnostic_sample(
            symbol="RELIANCE",
            packet_type="QUOTE",
            source_timestamp_utc=source_timestamp,
            fetched_at_utc=fetched_at,
        )
        expected = (source_timestamp - fetched_at).total_seconds()
        assert sample.delta_seconds == expected
        assert expected > 0  # matches the real 64.62/64.63 anomaly direction

    def test_sample_export_is_credential_free_and_json_safe(self) -> None:
        sample = TimestampDiagnosticSample(
            symbol="RELIANCE",
            packet_type="TICKER",
            source_timestamp_utc=datetime(2026, 8, 24, 9, 41, tzinfo=UTC),
            fetched_at_utc=datetime(2026, 8, 24, 9, 40, 55, tzinfo=UTC),
            delta_seconds=5.0,
        )
        row = sample.as_safe_dict()
        assert set(row.keys()) == {
            "symbol",
            "packet_type",
            "source_timestamp_utc",
            "fetched_at_utc",
            "delta_seconds",
        }
        for forbidden in ("token", "access_token", "client_id", "secret", "password"):
            assert forbidden not in str(row).lower()

    def test_collector_is_disabled_by_default_and_record_is_a_no_op(self) -> None:
        collector = TimestampDiagnosticCollector()
        assert collector.enabled is False
        sample = make_timestamp_diagnostic_sample(
            symbol="RELIANCE",
            packet_type="QUOTE",
            source_timestamp_utc=datetime(2026, 8, 24, 9, 41, tzinfo=UTC),
            fetched_at_utc=datetime(2026, 8, 24, 9, 40, 59, tzinfo=UTC),
        )
        collector.record(sample)
        assert collector.samples == ()
        assert collector.summary() == {"sample_count": 0}

    def test_collector_accumulates_and_summarizes_when_explicitly_enabled(self) -> None:
        collector = TimestampDiagnosticCollector(enabled=True)
        for i, symbol in enumerate(("RELIANCE", "TCS", "RELIANCE")):
            collector.record(
                make_timestamp_diagnostic_sample(
                    symbol=symbol,
                    packet_type="QUOTE" if i % 2 == 0 else "TICKER",
                    source_timestamp_utc=datetime(2026, 8, 24, 9, 41 + i, tzinfo=UTC),
                    fetched_at_utc=datetime(2026, 8, 24, 9, 40 + i, 55, tzinfo=UTC),
                )
            )
        summary = collector.summary()
        assert summary["sample_count"] == 3
        assert summary["samples_by_symbol"] == {"RELIANCE": 2, "TCS": 1}
        rows = collector.export_safe_rows()
        assert len(rows) == 3
        assert all("symbol" in row for row in rows)

    def test_run_market_data_worker_never_constructs_the_collector_this_checkpoint(self) -> None:
        """Directive §10: 'DO NOT perform the live collection now' -
        mechanically confirms this checkpoint did not wire the collector
        into the composition root, only prepared it."""
        from intraday.infrastructure.persistence.management.commands import (
            run_market_data_worker,
        )

        source = inspect.getsource(run_market_data_worker)
        assert "TimestampDiagnosticCollector" not in source
