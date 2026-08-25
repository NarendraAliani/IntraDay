# File: src/intraday/infrastructure/market_data_providers/dhan/worker_session.py
#
# Checkpoint 55: the ONE missing link tying Checkpoint 53's decoder +
# worker state machine and Checkpoint 54's packet->Quote bridge into a
# SINGLE orchestrated flow - proving these three previously-independent
# pieces actually compose correctly, deterministically, without a real
# socket or a new third-party dependency.
#
# `run_worker_session()` is driven by a caller-scripted sequence of
# `WorkerEvent`s (connection lifecycle) interleaved with raw packet
# `bytes` (market data) - this IS the "deterministic fake Dhan server"
# the user asked for, in spirit: a fully scripted, byte-accurate
# simulation of what a real transport would hand the worker, without
# opening an actual socket. `ScriptedDhanSession` (below) is the
# concrete builder tests use to construct realistic scripts from real
# packet bytes (via `packet_decoder`'s own byte-fixture helpers).
#
# HONEST SCOPE LIMIT, stated as plainly as Checkpoint 53/54's own: this
# is the worker's CORE ORCHESTRATION LOGIC - synchronous, I/O-free,
# fully testable today. It is NOT `python manage.py
# run_market_data_worker`, NOT a real asyncio event loop, NOT a real
# TCP/WebSocket connection, and NOT wired to a live or even a
# real-socket-based fake Dhan server. Those remain separate, undone,
# named dependencies (see ACTIVE_PRODUCT_GAP_REGISTER.md) - a real
# worker command would wrap THIS function's logic around an actual
# async transport, translating real connection callbacks into the same
# `WorkerEvent`/`bytes` vocabulary this module already consumes.
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from intraday.domain.market_data.contracts import Quote
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    DhanDisconnectPacket,
    DhanOpenInterestPacket,
    PacketDecodeFailure,
    decode_packet,
)
from intraday.infrastructure.market_data_providers.dhan.packet_to_quote import (
    QuoteConversionRejectionReason,
    convert_packet_to_quote,
)
from intraday.infrastructure.market_data_providers.dhan.worker_state import (
    WorkerEvent,
    WorkerState,
    apply_event,
)

WorkerSessionStep = WorkerEvent | bytes
"""Either a connection-lifecycle event to apply to the state machine, or
raw packet bytes to decode and (if valid) convert to a `Quote`."""


@dataclass(frozen=True, slots=True)
class RejectedPacket:
    reason: QuoteConversionRejectionReason
    security_id: int


@dataclass(frozen=True, slots=True)
class WorkerSessionOutcome:
    final_state: WorkerState
    quotes: tuple[Quote, ...]
    rejected_packets: tuple[RejectedPacket, ...]
    """Syntactically valid Ticker/Quote packets that could not become a
    `Quote` - unmapped instrument or an invalid price. NEVER silently
    dropped without a reason attached."""
    decode_failures: int
    """Count of raw byte inputs that failed to decode at all
    (truncated/malformed/unsupported packet type) - the worker kept
    running through every one of them, per Checkpoint 53's own "no
    malformed packet may crash the worker" requirement."""
    illegal_transitions: int
    """Count of scripted `WorkerEvent`s that were refused by the state
    machine (an illegal `(state, event)` pair) - `0` in a correctly
    scripted session; a non-zero count in a test is itself the proof
    that `apply_event()`'s refusal path works end-to-end through this
    orchestration, not just in `worker_state.py`'s own unit tests."""


def run_worker_session(
    steps: Sequence[WorkerSessionStep], *, security_id_to_symbol: dict[int, str]
) -> WorkerSessionOutcome:
    """Processes `steps` in order against a single worker session,
    starting from `WorkerState.STOPPED`. Never raises - a decode
    failure is counted and skipped; an illegal event is refused and
    counted, never crashing the session; a `Disconnect` packet is
    translated into a `CONNECTION_LOST` event automatically (the ONE
    piece of domain knowledge this orchestration adds on top of the
    decoder + state machine: what a disconnect PACKET means for the
    state machine, which neither of those two modules alone knows)."""
    state = WorkerState.STOPPED
    quotes: list[Quote] = []
    rejected: list[RejectedPacket] = []
    decode_failures = 0
    illegal_transitions = 0

    def transition(event: WorkerEvent) -> None:
        nonlocal state, illegal_transitions
        result = apply_event(state, event)
        if not result.accepted:
            illegal_transitions += 1
            return
        state = result.new_state

    for step in steps:
        if isinstance(step, WorkerEvent):
            transition(step)
            continue

        decoded = decode_packet(step)
        if isinstance(decoded, PacketDecodeFailure):
            decode_failures += 1
            continue
        if isinstance(decoded, DhanDisconnectPacket):
            transition(WorkerEvent.CONNECTION_LOST)
            continue

        if isinstance(decoded, DhanOpenInterestPacket):
            # Checkpoint 64.78: OI packets (feed response code 5) are now
            # DECODED rather than classified UNSUPPORTED_PACKET_TYPE. They
            # are not equity quotes and must never enter the equity path,
            # which subscribes NSE_EQ only (a cash instrument has no open
            # interest). Skipped explicitly, and NOT counted as a decode
            # failure - the packet decoded perfectly, it simply does not
            # belong to this consumer. Option OI routing lives in
            # `packet_to_option_observation.py`.
            continue

        conversion = convert_packet_to_quote(decoded, security_id_to_symbol=security_id_to_symbol)
        if conversion.accepted:
            assert conversion.quote is not None  # narrows for mypy; accepted implies non-None
            quotes.append(conversion.quote)
        else:
            assert conversion.rejected_reason is not None
            rejected.append(
                RejectedPacket(
                    reason=conversion.rejected_reason, security_id=decoded.header.security_id
                )
            )

    return WorkerSessionOutcome(
        final_state=state,
        quotes=tuple(quotes),
        rejected_packets=tuple(rejected),
        decode_failures=decode_failures,
        illegal_transitions=illegal_transitions,
    )


# --- The connection-lifecycle event sequence a NORMAL, uninterrupted
# session scripts before any packets arrive - a small, named constant
# so tests (and, eventually, a real worker) never have to repeat this
# exact sequence by hand and risk getting it subtly wrong. -----------
NORMAL_STARTUP_EVENTS: tuple[WorkerEvent, ...] = (
    WorkerEvent.START_REQUESTED,
    WorkerEvent.AUTH_SUCCEEDED,
    WorkerEvent.CONNECTED,
    WorkerEvent.SUBSCRIBED,
)

NORMAL_RECONNECT_EVENTS: tuple[WorkerEvent, ...] = (
    WorkerEvent.RECONNECT_SUCCEEDED,
    WorkerEvent.SUBSCRIBED,
)

CLEAN_SHUTDOWN_EVENTS: tuple[WorkerEvent, ...] = (
    WorkerEvent.STOP_REQUESTED,
    WorkerEvent.STOPPED_CLEANLY,
)
