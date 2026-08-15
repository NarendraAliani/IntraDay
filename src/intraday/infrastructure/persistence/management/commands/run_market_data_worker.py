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
# in this project: `--provider fake` is the ONLY supported mode. There
# is no real Dhan WebSocket transport in this repository yet (the
# RFC 6455 handshake / WebSocket dependency decision remains explicitly
# unresolved - see Decision 211's own "the WebSocket technology
# decision must now be resolved" note in ARCHITECTURE_DECISIONS.md).
# `--provider fake` self-hosts a REAL local TCP socket
# (`FakeDhanTcpServer`, Checkpoint 56) and drives the REAL async
# packet-processing loop (`async_worker.py`, Checkpoint 57) against
# it - genuine socket I/O, genuine framing, genuine state-machine
# transitions, genuine `Quote` conversion - but explicitly, repeatedly,
# NOT a live Dhan connection. Running this command proves the runtime
# LOOP itself works continuously against a real socket; it does not
# prove anything about Dhan's actual production feed.
from __future__ import annotations

import asyncio
import struct

from django.core.management.base import BaseCommand, CommandParser

from intraday.domain.market_data.contracts import Quote
from intraday.infrastructure.market_data_providers.dhan.async_worker import (
    run_worker_against_stream,
)
from intraday.infrastructure.market_data_providers.dhan.fake_tcp_server import FakeDhanTcpServer
from intraday.infrastructure.market_data_providers.dhan.instruments import observation_universe

_HEADER_STRUCT = struct.Struct("<BHBi")
_DEFAULT_PACKET_COUNT = 20
_DEFAULT_BASE_EPOCH = 1735900800


def _synthetic_ticker_packet(*, security_id: int, ltp: float, ltt_epoch: int) -> bytes:
    """Builds ONE syntactically valid Ticker packet for the SYNTHETIC
    (`--provider fake`) stream only - never used anywhere near a real
    Dhan connection. Uses the exact VERIFIED_PRIMARY layout
    `packet_decoder.py` decodes (Checkpoint 53's research), so the
    command exercises the real decode path with real, correctly-shaped
    bytes, not a shortcut."""
    body = struct.pack("<fi", ltp, ltt_epoch)
    return _HEADER_STRUCT.pack(2, len(body), 1, security_id) + body


def _build_synthetic_script(packet_count: int) -> tuple[bytes, ...]:
    """Cycles through the configured observation universe (Checkpoint
    23's own `observation_universe()` - never a separately hard-coded
    list), producing a small, deterministic, gently-varying price per
    packet so a human watching the command's output sees plausibly
    real-looking ticks rather than one repeated static value."""
    instruments = observation_universe()
    packets: list[bytes] = []
    for i in range(packet_count):
        instrument = instruments[i % len(instruments)]
        packets.append(
            _synthetic_ticker_packet(
                security_id=instrument.security_id,
                ltp=100.0 + (i % 10),
                ltt_epoch=_DEFAULT_BASE_EPOCH + i,
            )
        )
    return tuple(packets)


class Command(BaseCommand):
    help = (
        "Runs the market-data worker persistently against a synthetic "
        "(fake) Dhan-shaped feed. PAPER-safe: makes no broker call, "
        "places no order, and has no code path to any order-placement "
        "API (see tests/unit/architecture/test_live_market_data_boundaries.py). "
        "--provider fake is the only supported mode this checkpoint."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--provider",
            choices=["fake"],
            default="fake",
            help="Market-data provider to run against. Only 'fake' (a real local "
            "socket, synthetic data) is implemented - see this command's own "
            "module docstring for why a real Dhan provider does not exist yet.",
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
        self.stdout.write(
            self.style.WARNING(
                f"Starting market-data worker (provider=fake, "
                f"packet_count={packet_count}) - PAPER-safe synthetic run, "
                f"NOT a live Dhan connection."
            )
        )
        result = asyncio.run(self._run(packet_count))
        self.stdout.write(
            self.style.SUCCESS(
                f"Worker finished: final_state={result.final_state.value} "
                f"quotes_processed={result.quotes_processed} "
                f"decode_failures={result.decode_failures} "
                f"rejected_packets={result.rejected_packets}"
            )
        )

    async def _run(self, packet_count: int):  # type: ignore[no-untyped-def]
        instruments = observation_universe()
        security_id_to_symbol = {i.security_id: i.symbol for i in instruments}
        script = _build_synthetic_script(packet_count)

        server = FakeDhanTcpServer(scripted_packets=script)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection(server.host, server.port)
            try:

                def _on_quote(quote: Quote) -> None:
                    self.stdout.write(
                        f"  quote: {quote.instrument_id} last_price={quote.last_price} "
                        f"at={quote.timestamp.isoformat()}"
                    )

                return await run_worker_against_stream(
                    reader,
                    security_id_to_symbol=security_id_to_symbol,
                    on_quote=_on_quote,
                )
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()
