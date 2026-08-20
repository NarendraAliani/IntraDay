# File: src/intraday/infrastructure/persistence/management/commands/run_market_data_worker.py
#
# Checkpoint 57: `python manage.py run_market_data_worker` - the FIRST
# real, persistent-process entry point in this project's Dhan
# integration. Lives under `infrastructure/persistence/management/
# commands/` because `intraday.infrastructure.persistence` is the ONE
# Django app registered in `INSTALLED_APPS` (see `settings/base.py`) -
# Django only auto-discovers management commands inside a registered
# app's own `management/commands/` directory, so this is the correct,
# only-possible location, not a boundary violation (this command is
# infrastructure/composition-root code, exactly like every other
# `infrastructure/api/*_runtime.py` module in this project).
#
# CHECKPOINT 64.1 ADDS: `--provider dhan` - a REAL production provider,
# using the exact same `DhanWebSocketTransport`/`packet_decoder`/
# `packet_to_quote`/bar-aggregation pipeline the fake/fake-ws providers
# already exercise (never a second, parallel implementation), wrapped
# in the new `run_worker_with_reconnect()` bounded-backoff supervisor.
# MARKET DATA ONLY - this command has no code path to any order-
# placement API at all (mechanically verified by
# tests/unit/architecture/test_live_market_data_boundaries.py, which
# scans this entire directory for a forbidden `trading_engine` import).
# Refuses to even attempt a connection if Dhan credentials are absent
# or the access token's own claims report anything other than VALID/
# EXPIRING_SOON (Checkpoint 64.1's own explicit requirement: "the
# worker must never pretend to be connected when the token is known to
# be expired"). This environment's own configured token was found
# EXPIRED at Checkpoint 64 - `--provider dhan` in THIS environment
# will therefore refuse to start until a fresh token is configured;
# that refusal is itself the correct, honest behavior, not a bug.
#
# Checkpoint 59 CORRECTION to Checkpoint 58: bar aggregation
# (`_aggregate_now()`) is triggered PERIODICALLY, every
# `_AGGREGATION_BATCH_SIZE` quotes, WHILE the packet-processing loop is
# still running - proven by dedicated tests that stop the worker
# mid-stream (with scripted packets still unread) and assert bars
# already exist. This closes a real gap the user identified in
# Checkpoint 58's own implementation: aggregating only once, after the
# stream ended, only proved "quotes can eventually become bars," never
# "bars form continuously while the worker runs."
#
# Checkpoint 62 ADDS: `--provider fake-ws`, exercising the REAL RFC
# 6455 WebSocket transport (`DhanWebSocketTransport`,
# `FakeDhanWebSocketServer`, Checkpoint 61) through this SAME operator-
# facing command, not only through tests. The quote-persistence and
# periodic-aggregation logic is shared between both providers (via
# `_QuoteSink`) - a real Dhan provider, when it exists, would plug into
# the identical sink, never a third parallel implementation.
from __future__ import annotations

import asyncio
import datetime as dt
import json
import struct
from collections.abc import Callable

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand, CommandParser
from django.db import close_old_connections

from intraday.application.services.bar_aggregation import BarAggregationService
from intraday.application.services.provider_settings import DhanSettingsService
from intraday.application.services.token_lifecycle import (
    TokenLifecycleState,
    evaluate_dhan_token_lifecycle,
)
from intraday.domain.market_data.aggregation import BarStatus
from intraday.domain.market_data.contracts import Quote
from intraday.domain.session.calendar import session_for_instant
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.infrastructure.api.signal_pipeline_runtime import (
    DEFAULT_STRATEGY_ID as SIGNAL_STRATEGY_ID,
)
from intraday.infrastructure.api.signal_pipeline_runtime import promote_bars_and_trigger_signals
from intraday.infrastructure.market_data_providers.dhan.async_worker import (
    AsyncWorkerRunResult,
    run_worker_against_stream,
    run_worker_against_websocket,
)
from intraday.infrastructure.market_data_providers.dhan.fake_tcp_server import FakeDhanTcpServer
from intraday.infrastructure.market_data_providers.dhan.fake_websocket_server import (
    FakeDhanWebSocketServer,
)
from intraday.infrastructure.market_data_providers.dhan.instruments import (
    DhanInstrument,
    observation_universe,
)
from intraday.infrastructure.market_data_providers.dhan.reconnect_supervisor import (
    run_worker_with_reconnect,
)
from intraday.infrastructure.market_data_providers.dhan.scanner_universe import (
    resolve_scanner_universe,
)
from intraday.infrastructure.market_data_providers.dhan.websocket_transport import (
    DhanWebSocketTransport,
    DhanWebSocketTransportError,
)
from intraday.infrastructure.market_data_providers.dhan.worker_health_tracker import (
    WorkerHealthTracker,
)
from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState
from intraday.infrastructure.persistence.live_market_data_repositories import (
    DjangoAggregatedBarRepository,
    DjangoLiveQuoteRepository,
)
from intraday.infrastructure.persistence.models import SignalRecord
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)
from intraday.infrastructure.persistence.repositories import DjangoWatchlistRepository
from intraday.infrastructure.persistence.scanner_configuration_repository import (
    DjangoScannerConfigurationRepository,
)
from intraday.infrastructure.persistence.scanner_scan_progress_repository import (
    DjangoScannerScanProgressRepository,
)
from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)

DHAN_LIVE_FEED_ENDPOINT = "wss://api-feed.dhan.co"
"""Verified directly against Dhan's own official documentation
(https://dhanhq.co/docs/v2/live-market-feed/) at Checkpoint 64/64.1 -
never invented. The `version`/`token`/`clientId`/`authType` query
parameters below match that same source exactly."""
_SUBSCRIBE_REQUEST_CODE = 15
_MAX_INSTRUMENTS_PER_SUBSCRIBE_MESSAGE = 100
"""Dhan's own documented per-message limit (verified against
https://dhanhq.co/docs/v2/live-market-feed/) - Checkpoint 64.4 closes
the "silently truncates to 100" gap named in Checkpoint 64.3's own
report: a universe larger than this is now split into MULTIPLE
subscribe messages (`_build_subscribe_messages()` below), never
truncated."""


def _build_subscribe_messages(
    instruments: tuple[DhanInstrument, ...],
    chunk_size: int = _MAX_INSTRUMENTS_PER_SUBSCRIBE_MESSAGE,
) -> list[str]:
    """Splits `instruments` into `chunk_size`-sized batches, each
    encoded as its own real `RequestCode: 15` subscribe message -
    e.g. 287 instruments -> 3 messages of 100/100/87. Never silently
    drops anything past the first `chunk_size`."""
    messages: list[str] = []
    for start in range(0, len(instruments), chunk_size):
        batch = instruments[start : start + chunk_size]
        messages.append(
            json.dumps(
                {
                    "RequestCode": _SUBSCRIBE_REQUEST_CODE,
                    "InstrumentCount": len(batch),
                    "InstrumentList": [
                        {"ExchangeSegment": i.exchange_segment, "SecurityId": str(i.security_id)}
                        for i in batch
                    ],
                }
            )
        )
    return messages


_HEADER_STRUCT = struct.Struct("<BHBi")
_DEFAULT_PACKET_COUNT = 20
_AGGREGATION_BATCH_SIZE = 5
"""Checkpoint 59: the user's own explicit, correct challenge to
Checkpoint 58's implementation - aggregating only AFTER the stream
ended proves "quotes can eventually become bars," never "bars form
continuously while the worker runs," which is what an active pipeline
actually needs. Triggering aggregation every `_AGGREGATION_BATCH_SIZE`
quotes - WHILE still inside the packet-processing loop, not after it
exits - is what closes that gap. `5` is a small, deterministic value
chosen so a test can prove aggregation happened mid-stream (with
packets still unread) without needing a long-running/timed test."""


def _synthetic_ticker_packet(*, security_id: int, ltp: float, ltt_epoch: int) -> bytes:
    """Builds ONE syntactically valid Ticker packet for the SYNTHETIC
    providers only - never used anywhere near a real Dhan connection.
    Uses the exact VERIFIED_PRIMARY layout `packet_decoder.py` decodes
    (Checkpoint 53's research), so the command exercises the real
    decode path with real, correctly-shaped bytes, not a shortcut."""
    body = struct.pack("<fi", ltp, ltt_epoch)
    return _HEADER_STRUCT.pack(2, len(body), 1, security_id) + body


def _build_synthetic_script(packet_count: int) -> tuple[bytes, ...]:
    """Cycles through the configured observation universe (Checkpoint
    23's own `observation_universe()` - never a separately hard-coded
    list), producing a small, deterministic, gently-varying price per
    packet so a human watching the command's output sees plausibly
    real-looking ticks rather than one repeated static value.

    Checkpoint 58: timestamps are anchored to the REAL current instant
    (seconds in the past, one per packet), not a fixed historical
    epoch - `BarAggregationService.aggregate_and_persist()` only looks
    back `DEFAULT_LOOKBACK` (8 hours) from `as_of`, so a fixed
    2025-dated epoch would silently produce ZERO bars regardless of
    how many quotes were persisted. Anchoring to "now" is what makes
    the quote-to-bar wiring actually produce a real, non-empty
    aggregation result."""
    instruments = observation_universe()
    base_epoch = int(dt.datetime.now(tz=dt.UTC).timestamp()) - packet_count
    packets: list[bytes] = []
    for i in range(packet_count):
        instrument = instruments[i % len(instruments)]
        packets.append(
            _synthetic_ticker_packet(
                security_id=instrument.security_id,
                ltp=100.0 + (i % 10),
                ltt_epoch=base_epoch + i,
            )
        )
    return tuple(packets)


class _QuoteSink:
    """Checkpoint 62: the persistence + periodic-aggregation logic
    Checkpoint 58/59 built, extracted into ONE reusable object shared
    by every provider this command supports - `--provider fake` (raw
    TCP) and `--provider fake-ws` (real WebSocket) both call the exact
    SAME `on_quote()` method. A future real Dhan provider would do the
    same - this sink has no idea which transport produced the `Quote`
    it is given, matching this project's own "transport is dumb, the
    rest of the pipeline does not care which transport it came from"
    discipline (`websocket_transport.py`'s own module docstring)."""

    def __init__(
        self,
        stdout: Callable[[str], None],
        *,
        strategy_id: str = SIGNAL_STRATEGY_ID,
        health_tracker: WorkerHealthTracker | None = None,
        runtime_status_provider: str | None = None,
        scanner_config_provider: str | None = None,
        effective_universe_requested_count: int = 0,
        effective_universe_subscribed_count: int = 0,
    ) -> None:
        self._stdout = stdout
        self._quote_repository = DjangoLiveQuoteRepository()
        self._bar_service = BarAggregationService(
            quote_repository=self._quote_repository,
            bar_repository=DjangoAggregatedBarRepository(),
        )
        self._quotes_since_last_aggregation = 0
        self._strategy_id = strategy_id
        # Checkpoint 64.3: `None` for the synthetic fake/fake-ws test
        # providers (never persisted - they'd otherwise overwrite the
        # real "dhan" status row with test-run data). Set to "dhan" only
        # for the real production provider, so an operator-facing status
        # API always reflects the real worker, never a test run.
        self._runtime_status_provider = runtime_status_provider
        self._runtime_status_repository = DjangoWorkerRuntimeStatusRepository()
        # Checkpoint 64.4: the DESIRED scanner configuration is
        # re-read FRESH on every aggregation cycle (never cached across
        # cycles) - `enabled`/`timeframe`/`selected_strategy_ids` are
        # genuinely live-reconfigurable this way, without a process
        # restart. `None` for the synthetic providers, which have no
        # desired-configuration concept of their own (they keep the
        # single `strategy_id`/1m-timeframe behavior from before this
        # checkpoint, unchanged).
        self._scanner_config_provider = scanner_config_provider
        self._scanner_config_repository = DjangoScannerConfigurationRepository()
        # Checkpoint 64.18 §2/§5: the ONLY writer of scanner scan
        # progress anywhere in this codebase - `None` for the synthetic
        # providers, same discipline as `_runtime_status_provider` above.
        self._scan_progress_provider = runtime_status_provider
        self._scan_progress_repository = DjangoScannerScanProgressRepository()
        # Universe resolution happens ONCE per connection (at connect
        # time, before this sink is constructed for that attempt) -
        # changing universe_mode/selected instruments takes effect on
        # the NEXT reconnect, not instantly - an honest, documented
        # limitation (unlike timeframe/strategy, applying a universe
        # change live would mean resubscribing mid-stream, a bigger,
        # separate piece of work not attempted this checkpoint).
        self._effective_universe_requested_count = effective_universe_requested_count
        self._effective_universe_subscribed_count = effective_universe_subscribed_count
        # Checkpoint 64.3: THE truthful-health fix - `is_healthy()` is
        # now evaluated fresh, from real tracked facts, every time a bar
        # is about to be promoted - never a captured-once bool/callable
        # that can't reflect a mid-run reconnect. Defaults to a tracker
        # that's already `mark_connected()` (below) for the synthetic
        # fake/fake-ws providers, which have no independent health
        # signal of their own to report and were always intended to
        # behave as "healthy" for their own deterministic test purposes.
        self.health_tracker = health_tracker or WorkerHealthTracker()
        if health_tracker is None:
            self.health_tracker.mark_token_state("VALID")
            self.health_tracker.mark_connected(subscribed_instrument_count=0)

    async def on_quote(self, quote: Quote) -> None:
        # Django's ORM refuses synchronous DB access from inside an
        # async context (`SynchronousOnlyOperation`) - `sync_to_async`
        # is the standard, documented bridge, not a workaround unique
        # to this module.
        now = dt.datetime.now(tz=dt.UTC)
        await sync_to_async(self._quote_repository.save_all)((quote,), fetched_at=now)
        self.health_tracker.record_packet(now=now)
        self._stdout(
            f"  quote: {quote.instrument_id} last_price={quote.last_price} "
            f"at={quote.timestamp.isoformat()}"
        )
        self._quotes_since_last_aggregation += 1
        if self._quotes_since_last_aggregation >= _AGGREGATION_BATCH_SIZE:
            # THE Checkpoint 59 fix: this runs WHILE the packet stream
            # may still have unread packets waiting - real, continuous
            # bar formation, not "wait for disconnect."
            self._quotes_since_last_aggregation = 0
            await self.aggregate_now()

    async def aggregate_now(self) -> None:
        clock = dt.datetime.now(tz=dt.UTC)

        # Checkpoint 64.4: RECONCILIATION - the desired configuration is
        # read fresh, every cycle, never cached across cycles. This is
        # what makes timeframe/strategy/enabled changes genuinely live-
        # reconfigurable without a process restart - see this class's
        # own __init__ docstring for what is NOT (universe changes,
        # which still require a reconnect).
        strategy_ids: tuple[str, ...] = (self._strategy_id,)
        timeframe = Timeframe.ONE_MINUTE
        enabled = True
        configuration_version = 0
        if self._scanner_config_provider is not None:
            desired = await sync_to_async(self._scanner_config_repository.get)(
                self._scanner_config_provider
            )
            enabled = desired.enabled
            configuration_version = desired.configuration_version
            try:
                timeframe = Timeframe(desired.timeframe)
            except ValueError:
                self._stdout(
                    f"  desired timeframe {desired.timeframe!r} is not a real Timeframe - "
                    "keeping the previous effective timeframe"
                )
            strategy_ids = desired.selected_strategy_ids or (self._strategy_id,)

        aggregation = await sync_to_async(self._bar_service.aggregate_and_persist)(
            as_of=clock, timeframe=timeframe
        )
        if aggregation.bars:
            self.health_tracker.record_bar(now=clock)
        self._stdout(
            f"  aggregated {len(aggregation.bars)} bar(s) so far "
            f"(missing_intervals={len(aggregation.missing_intervals)} "
            f"anomalous_observations={len(aggregation.anomalous_observations)})"
        )

        if self._scanner_config_provider is not None:
            await sync_to_async(self._runtime_status_repository.save_effective_scanner_state)(
                self._scanner_config_provider,
                effective_configuration_version=configuration_version,
                effective_timeframe=timeframe.value,
                effective_strategy_ids=list(strategy_ids),
                effective_universe_requested_count=self._effective_universe_requested_count,
                effective_universe_subscribed_count=self._effective_universe_subscribed_count,
            )

        if not enabled:
            # Checkpoint 64.4: THE real, in-scope PAUSE/STOP mechanism -
            # bars still aggregate and persist (never lost), but the
            # signal pipeline is skipped entirely. Existing positions/
            # history are completely untouched.
            self._stdout("  scanner disabled (desired configuration) - signal pipeline skipped")
            if self._scan_progress_provider is not None:
                await sync_to_async(self._scan_progress_repository.mark_idle)(
                    self._scan_progress_provider
                )
            return

        # Checkpoint 64.2/64.3: newly-closed bars reach the shared
        # strategy/signal/risk/paper pipeline - `connection_is_healthy`
        # is now a REAL, freshly-evaluated fact from the watchdog
        # (Checkpoint 64.1), never a hard-coded truthy value (the
        # review's own explicitly-named safety-critical gap). A bar is
        # never promotable just because a process happens to be
        # running. Checkpoint 64.4: now loops over EVERY desired
        # strategy, never just one - `promote_bars_and_trigger_signals`
        # itself is unmodified (still single-strategy-per-call), this
        # is the multi-strategy fan-out, kept at the call site rather
        # than inside the shared function so the REST-ingestion path
        # (still genuinely single-strategy) is unaffected.
        session = session_for_instant(clock)
        connection_is_healthy = self.health_tracker.is_healthy(now=clock)
        total_promoted = 0
        total_invocations = 0

        # Checkpoint 64.18 §2/§4/§5: ONE scan = one aggregate_now() cycle
        # across every desired strategy. `universe_total` is computed
        # ONCE, before the strategy loop, from the SAME closed-bar set
        # `promote_bars_and_trigger_signals` itself will iterate (never a
        # second, divergent count).
        scan_degraded = False
        if self._scan_progress_provider is not None:
            closed_instrument_ids = {
                str(b.instrument_id) for b in aggregation.bars if b.status is BarStatus.CLOSED
            }
            await sync_to_async(self._scan_progress_repository.start_scan)(
                self._scan_progress_provider,
                scan_id=clock.isoformat(),
                scan_started_at=clock,
                timeframe=timeframe.value,
                universe_total=len(closed_instrument_ids),
                strategies_total=len(strategy_ids),
            )

        for strategy_index, strategy_id in enumerate(strategy_ids, start=1):
            if self._scan_progress_provider is not None:

                def _report_progress(
                    instrument_id: str,
                    processed_count: int,
                    _total: int,
                    *,
                    _strategy_id: str = strategy_id,
                ) -> None:
                    # Called from inside `sync_to_async(promote_bars_and_
                    # trigger_signals)(...)` below - already running on the
                    # sync-context thread, so this repository call is a
                    # plain (not `await sync_to_async(...)`) call, matching
                    # how Django's `sync_to_async` executes its wrapped
                    # callable's own nested synchronous calls.
                    self._scan_progress_repository.update_progress(
                        self._scan_progress_provider,  # type: ignore[arg-type]
                        status="SCANNING",
                        current_instrument=instrument_id,
                        current_strategy=_strategy_id,
                        universe_processed=processed_count,
                    )

                await sync_to_async(self._scan_progress_repository.update_progress)(
                    self._scan_progress_provider,
                    status="SCANNING",
                    current_strategy=strategy_id,
                    strategies_processed=strategy_index - 1,
                )
            else:
                _report_progress = None  # type: ignore[assignment]

            try:
                pipeline_outcome = await sync_to_async(promote_bars_and_trigger_signals)(
                    aggregation,
                    session=session,
                    clock=clock,
                    connection_is_healthy=connection_is_healthy,
                    strategy_id=strategy_id,
                    on_instrument_progress=_report_progress,
                )
                total_promoted += pipeline_outcome.promoted_count
                total_invocations += pipeline_outcome.active_loop_invocations
            except Exception as exc:  # noqa: BLE001 - one strategy's
                # failure must not abort the whole scan (§4's explicit
                # instruction) - caught, recorded as DEGRADED, safely
                # logged (never a raw traceback in the persisted state),
                # and the loop continues to the remaining strategies.
                scan_degraded = True
                self._stdout(f"  strategy {strategy_id!r} failed during this scan: {exc}")
                if self._scan_progress_provider is not None:
                    await sync_to_async(self._scan_progress_repository.update_progress)(
                        self._scan_progress_provider,
                        status="DEGRADED",
                        last_error_safe=f"strategy {strategy_id} failed",
                    )

            if self._scan_progress_provider is not None:
                await sync_to_async(self._scan_progress_repository.update_progress)(
                    self._scan_progress_provider,
                    status="DEGRADED" if scan_degraded else "SCANNING",
                    strategies_processed=strategy_index,
                )

        if self._scan_progress_provider is not None:
            # `created_at` (`auto_now_add`) is the row's real wall-clock
            # insertion time - `clock` was captured at the START of this
            # very cycle, before any signal this cycle could produce was
            # written, so this precisely counts "signals created during
            # THIS scan," never an approximated time window.
            signals_found = await sync_to_async(
                lambda: SignalRecord.objects.filter(created_at__gte=clock).count()
            )()
            await sync_to_async(self._scan_progress_repository.update_progress)(
                self._scan_progress_provider,
                status="DEGRADED" if scan_degraded else "COMPLETED",
                signals_found=signals_found,
            )

        if self._runtime_status_provider is not None:
            await sync_to_async(self.health_tracker.persist)(
                self._runtime_status_repository, provider=self._runtime_status_provider, now=clock
            )

        if total_promoted or total_invocations:
            self._stdout(
                f"  promoted {total_promoted} bar(s) to TRADING_GRADE_BAR, "
                f"triggered {total_invocations} active-loop tick(s) across "
                f"{len(strategy_ids)} strategy(ies)"
            )

    async def flush_remainder(self) -> None:
        # A final aggregation catches any REMAINDER quotes that
        # arrived after the last periodic batch but before the stream
        # ended - a cleanup pass, not the primary mechanism, so a real
        # active pipeline is never dependent on the stream ending to
        # produce its bars.
        if self._quotes_since_last_aggregation > 0:
            await self.aggregate_now()


class Command(BaseCommand):
    help = (
        "Runs the market-data worker persistently. --provider fake/fake-ws "
        "are local, synthetic, PAPER-safe test modes. --provider dhan is the "
        "REAL production provider (market data only - makes no broker call, "
        "places no order, and has no code path to any order-placement API, "
        "see tests/unit/architecture/test_live_market_data_boundaries.py) - "
        "it refuses to connect at all unless a usable Dhan token is "
        "configured (see this command's own module docstring)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--provider",
            choices=["fake", "fake-ws", "dhan"],
            default="fake",
            help="Market-data provider to run against. 'fake' uses a real local "
            "raw-TCP socket (Checkpoint 56/57); 'fake-ws' uses a real local "
            "RFC 6455 WebSocket connection (Checkpoint 61/62); 'dhan' "
            "(Checkpoint 64.1) is the REAL production Dhan feed - market data "
            "only, refuses to start without a usable token. See this "
            "command's own module docstring.",
        )
        parser.add_argument(
            "--packet-count",
            type=int,
            default=_DEFAULT_PACKET_COUNT,
            help="How many synthetic packets the fake/fake-ws provider sends "
            "before the stream ends cleanly (default: %(default)s). Ignored "
            "for --provider dhan, which runs indefinitely (bounded reconnect, "
            "never a fixed packet count) until stopped or a genuinely "
            "unrecoverable state is reached.",
        )
        parser.add_argument(
            "--max-reconnect-attempts",
            type=int,
            default=5,
            help="--provider dhan only: how many connection attempts the "
            "reconnect supervisor makes (with bounded exponential backoff) "
            "before reporting FAILED (default: %(default)s). Never applies "
            "to an unrecoverable state (expired/invalid token) - that is "
            "never retried, regardless of this value.",
        )

    def handle(self, *args: object, **options: object) -> None:
        packet_count = int(str(options["packet_count"]))
        provider = str(options["provider"])
        max_reconnect_attempts = int(str(options["max_reconnect_attempts"]))
        self.stdout.write(
            self.style.WARNING(
                f"Starting market-data worker (provider={provider}"
                + (f", packet_count={packet_count}" if provider != "dhan" else "")
                + (
                    ") - MARKET DATA ONLY, real Dhan feed."
                    if provider == "dhan"
                    else ") - PAPER-safe synthetic run, NOT a live Dhan connection."
                )
            )
        )
        result = asyncio.run(self._run(provider, packet_count, max_reconnect_attempts))
        self.stdout.write(
            self.style.SUCCESS(
                f"Worker finished: final_state={result.final_state.value} "
                f"quotes_processed={result.quotes_processed} "
                f"decode_failures={result.decode_failures} "
                f"rejected_packets={result.rejected_packets}"
            )
        )

    async def _run(
        self, provider: str, packet_count: int, max_reconnect_attempts: int
    ) -> AsyncWorkerRunResult:
        if provider == "dhan":
            sink, result = await self._run_dhan(max_reconnect_attempts)
            await sink.flush_remainder()
            await sync_to_async(close_old_connections)()
            return result

        instruments = observation_universe()
        security_id_to_symbol = {i.security_id: i.symbol for i in instruments}
        script = _build_synthetic_script(packet_count)
        sink = _QuoteSink(stdout=self.stdout.write)

        if provider == "fake-ws":
            result = await self._run_fake_ws(script, security_id_to_symbol, sink)
        else:
            result = await self._run_fake_tcp(script, security_id_to_symbol, sink)

        await sink.flush_remainder()
        # `sync_to_async` runs each DB call in its own worker thread,
        # each opening its own real DB connection - Django only closes
        # those automatically at the end of an HTTP request, which this
        # bare `asyncio.run()` process never has. Closing explicitly
        # here avoids leaking a connection past the command's own
        # lifetime.
        await sync_to_async(close_old_connections)()
        return result

    async def _run_fake_tcp(
        self,
        script: tuple[bytes, ...],
        security_id_to_symbol: dict[int, str],
        sink: _QuoteSink,
    ) -> AsyncWorkerRunResult:
        server = FakeDhanTcpServer(scripted_packets=script)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection(server.host, server.port)
            try:
                return await run_worker_against_stream(
                    reader, security_id_to_symbol=security_id_to_symbol, on_quote=sink.on_quote
                )
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    async def _run_fake_ws(
        self,
        script: tuple[bytes, ...],
        security_id_to_symbol: dict[int, str],
        sink: _QuoteSink,
    ) -> AsyncWorkerRunResult:
        server = FakeDhanWebSocketServer(scripted_packets=script)
        await server.start()
        try:
            transport = DhanWebSocketTransport(uri=server.uri)
            await transport.connect()
            try:
                return await run_worker_against_websocket(
                    transport, security_id_to_symbol=security_id_to_symbol, on_quote=sink.on_quote
                )
            finally:
                await transport.close()
        finally:
            await server.stop()

    async def _run_dhan(
        self, max_reconnect_attempts: int
    ) -> tuple[_QuoteSink, AsyncWorkerRunResult]:
        """Checkpoint 64.1: the real production provider. MARKET DATA
        ONLY - see this command's own module docstring for the
        mechanically-enforced boundary. Refuses to attempt ANY
        connection unless the token's own claims currently report
        VALID or EXPIRING_SOON - `_select_historical_bar_provider()`'s
        own honest-fallback discipline (infrastructure/api/tasks.py)
        extended here to "refuse outright," since a live worker
        pretending to be connected with a known-bad token is a real
        safety hazard a backtest's fallback-to-synthetic is not.

        Checkpoint 64.4: the DESIRED `ScannerConfiguration` (provider
        "dhan") is resolved ONCE here, at connect time - this is what
        universe/subscription reflects for the lifetime of this
        connection. `strategy_ids`/`timeframe`/`enabled` are re-read
        FRESH on every aggregation cycle instead (see `_QuoteSink.
        aggregate_now()`), genuinely live-reconfigurable without a
        reconnect."""
        health_tracker = WorkerHealthTracker()
        scanner_config_repository = DjangoScannerConfigurationRepository()
        desired = await sync_to_async(scanner_config_repository.get)("dhan")

        dhan_service = DhanSettingsService(repository=DjangoDhanCredentialRepository())
        credentials = await sync_to_async(dhan_service.effective_credentials)()
        if credentials is None:
            self.stdout.write(
                self.style.ERROR("Dhan credentials are not configured - refusing to connect.")
            )
            sink = _QuoteSink(stdout=self.stdout.write, health_tracker=health_tracker)
            return sink, AsyncWorkerRunResult(final_state=WorkerState.AUTH_FAILED)

        client_id, access_token = credentials
        token_status = evaluate_dhan_token_lifecycle(access_token, now=dt.datetime.now(tz=dt.UTC))
        health_tracker.mark_token_state(token_status.state.value)
        if token_status.state not in (TokenLifecycleState.VALID, TokenLifecycleState.EXPIRING_SOON):
            self.stdout.write(
                self.style.ERROR(
                    f"Dhan token_state={token_status.state.value} - refusing to start a live "
                    "connection with a known-unusable token. This worker will never pretend "
                    "to be connected while the token is known bad."
                )
            )
            sink = _QuoteSink(stdout=self.stdout.write, health_tracker=health_tracker)
            return sink, AsyncWorkerRunResult(final_state=WorkerState.TOKEN_EXPIRED)

        watchlist_repository = DjangoWatchlistRepository()
        instruments = await sync_to_async(resolve_scanner_universe)(
            desired, watchlist_repository=watchlist_repository
        )
        requested_count = (
            len(desired.selected_instrument_ids)
            if desired.universe_mode == "SELECTED"
            else len(instruments)
        )
        if not instruments:
            self.stdout.write(self.style.ERROR("No instruments resolved - refusing to connect."))
            sink = _QuoteSink(stdout=self.stdout.write, health_tracker=health_tracker)
            return sink, AsyncWorkerRunResult(final_state=WorkerState.FAILED)

        security_id_to_symbol = {i.security_id: i.symbol for i in instruments}
        # Checkpoint 64.4: real batching - never truncates past 100,
        # splits into as many subscribe messages as needed instead.
        subscribe_messages = _build_subscribe_messages(instruments)
        self.stdout.write(
            f"  subscribing to {len(instruments)} instrument(s) "
            f"({len(subscribe_messages)} subscribe message(s), requested={requested_count})"
        )

        sink = _QuoteSink(
            stdout=self.stdout.write,
            health_tracker=health_tracker,
            runtime_status_provider="dhan",
            scanner_config_provider="dhan",
            effective_universe_requested_count=requested_count,
            effective_universe_subscribed_count=len(instruments),
        )

        async def connect_and_run() -> AsyncWorkerRunResult:
            health_tracker.mark_connecting()
            uri = (
                f"{DHAN_LIVE_FEED_ENDPOINT}?version=2&token={access_token}"
                f"&clientId={client_id}&authType=2"
            )
            transport = DhanWebSocketTransport(uri=uri)
            try:
                await transport.connect()
            except DhanWebSocketTransportError as exc:
                # The connection attempt itself failed (handshake
                # refused, DNS failure, etc.) - reported to the
                # supervisor as RECONNECTING (never raised past it), so
                # the bounded-backoff retry logic handles it exactly
                # like a mid-stream disconnect.
                health_tracker.mark_reconnecting(reason=f"connect_failed:{exc!r}")
                return AsyncWorkerRunResult(final_state=WorkerState.RECONNECTING)
            health_tracker.mark_connected(subscribed_instrument_count=len(instruments))
            try:
                for message in subscribe_messages:
                    await transport.send_json_text(message)
                result = await run_worker_against_websocket(
                    transport, security_id_to_symbol=security_id_to_symbol, on_quote=sink.on_quote
                )
                if result.final_state is WorkerState.RECONNECTING:
                    health_tracker.mark_reconnecting(reason="connection_lost")
                elif result.final_state in (
                    WorkerState.FAILED,
                    WorkerState.AUTH_FAILED,
                    WorkerState.TOKEN_EXPIRED,
                ):
                    health_tracker.mark_failed(result.final_state, reason=result.final_state.value)
                return result
            finally:
                await transport.close()

        supervisor_result = await run_worker_with_reconnect(
            connect_and_run, max_attempts=max_reconnect_attempts
        )
        self.stdout.write(
            f"  reconnect_count={supervisor_result.reconnect_count} "
            f"attempts={supervisor_result.attempts} "
            f"last_disconnect_reason={supervisor_result.last_disconnect_reason}"
        )
        return sink, AsyncWorkerRunResult(
            final_state=supervisor_result.final_state,
            quotes_processed=supervisor_result.total_quotes_processed,
        )
