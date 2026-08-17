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
# HONEST SCOPE LIMIT, stated as plainly as every prior Dhan checkpoint
# in this project: neither `--provider fake` (raw TCP, Checkpoint 57)
# nor `--provider fake-ws` (real WebSocket, Checkpoint 62) is a live
# Dhan connection - both are local, synthetic, PAPER-safe. No real
# `--provider dhan` mode exists yet (this environment's Dhan credential
# remains unusable for live verification, Checkpoint 41, unchanged).
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
import struct
from collections.abc import Callable

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand, CommandParser
from django.db import close_old_connections

from intraday.application.services.bar_aggregation import BarAggregationService
from intraday.domain.market_data.contracts import Quote
from intraday.infrastructure.market_data_providers.dhan.async_worker import (
    AsyncWorkerRunResult,
    run_worker_against_stream,
    run_worker_against_websocket,
)
from intraday.infrastructure.market_data_providers.dhan.fake_tcp_server import FakeDhanTcpServer
from intraday.infrastructure.market_data_providers.dhan.fake_websocket_server import (
    FakeDhanWebSocketServer,
)
from intraday.infrastructure.market_data_providers.dhan.instruments import observation_universe
from intraday.infrastructure.market_data_providers.dhan.websocket_transport import (
    DhanWebSocketTransport,
)
from intraday.infrastructure.persistence.live_market_data_repositories import (
    DjangoAggregatedBarRepository,
    DjangoLiveQuoteRepository,
)

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

    def __init__(self, stdout: Callable[[str], None]) -> None:
        self._stdout = stdout
        self._quote_repository = DjangoLiveQuoteRepository()
        self._bar_service = BarAggregationService(
            quote_repository=self._quote_repository,
            bar_repository=DjangoAggregatedBarRepository(),
        )
        self._quotes_since_last_aggregation = 0

    async def on_quote(self, quote: Quote) -> None:
        # Django's ORM refuses synchronous DB access from inside an
        # async context (`SynchronousOnlyOperation`) - `sync_to_async`
        # is the standard, documented bridge, not a workaround unique
        # to this module.
        await sync_to_async(self._quote_repository.save_all)(
            (quote,), fetched_at=dt.datetime.now(tz=dt.UTC)
        )
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
        aggregation = await sync_to_async(self._bar_service.aggregate_and_persist)(
            as_of=dt.datetime.now(tz=dt.UTC)
        )
        self._stdout(
            f"  aggregated {len(aggregation.bars)} bar(s) so far "
            f"(missing_intervals={len(aggregation.missing_intervals)} "
            f"anomalous_observations={len(aggregation.anomalous_observations)})"
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
        "Runs the market-data worker persistently against a synthetic "
        "(fake) Dhan-shaped feed. PAPER-safe: makes no broker call, "
        "places no order, and has no code path to any order-placement "
        "API (see tests/unit/architecture/test_live_market_data_boundaries.py). "
        "--provider fake (raw TCP) and --provider fake-ws (real WebSocket) "
        "are the only supported modes - neither is a live Dhan connection."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--provider",
            choices=["fake", "fake-ws"],
            default="fake",
            help="Market-data provider to run against. 'fake' uses a real local "
            "raw-TCP socket (Checkpoint 56/57); 'fake-ws' uses a real local "
            "RFC 6455 WebSocket connection (Checkpoint 61/62) - the SAME "
            "transport a real Dhan provider would eventually use. Neither is "
            "a live Dhan connection - see this command's own module docstring.",
        )
        parser.add_argument(
            "--packet-count",
            type=int,
            default=_DEFAULT_PACKET_COUNT,
            help="How many synthetic packets the fake provider sends before the "
            "stream ends cleanly (default: %(default)s). A REAL provider would "
            "run indefinitely; this is bounded so the command terminates "
            "deterministically for operators/tests running it directly.",
        )

    def handle(self, *args: object, **options: object) -> None:
        packet_count = int(str(options["packet_count"]))
        provider = str(options["provider"])
        self.stdout.write(
            self.style.WARNING(
                f"Starting market-data worker (provider={provider}, "
                f"packet_count={packet_count}) - PAPER-safe synthetic run, "
                f"NOT a live Dhan connection."
            )
        )
        result = asyncio.run(self._run(provider, packet_count))
        self.stdout.write(
            self.style.SUCCESS(
                f"Worker finished: final_state={result.final_state.value} "
                f"quotes_processed={result.quotes_processed} "
                f"decode_failures={result.decode_failures} "
                f"rejected_packets={result.rejected_packets}"
            )
        )

    async def _run(self, provider: str, packet_count: int) -> AsyncWorkerRunResult:
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
