# tests/unit/infrastructure/market_data_providers/dhan/test_worker_session.py
#
# Checkpoint 55: proves the decoder (Checkpoint 53), worker state
# machine (Checkpoint 53), and packet->Quote bridge (Checkpoint 54)
# actually compose correctly through `run_worker_session()` - a fully
# deterministic, scripted "session" standing in for what a real
# connection would hand the worker over time. This is the first test
# in this repository that exercises all three pieces together.
from __future__ import annotations

import struct
from datetime import UTC, datetime

from intraday.infrastructure.market_data_providers.dhan.packet_to_quote import (
    QuoteConversionRejectionReason,
)
from intraday.infrastructure.market_data_providers.dhan.timestamp_normalization import (
    normalize_dhan_websocket_timestamp,
)
from intraday.infrastructure.market_data_providers.dhan.worker_session import (
    CLEAN_SHUTDOWN_EVENTS,
    NORMAL_RECONNECT_EVENTS,
    NORMAL_STARTUP_EVENTS,
    run_worker_session,
)
from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerEvent, WorkerState

_HEADER_STRUCT = struct.Struct("<BHBi")
_SECURITY_MAP = {2885: "RELIANCE", 1333: "HDFCBANK"}


def _ticker_bytes(*, security_id: int, ltp: float, ltt_epoch: int = 1735900800) -> bytes:
    body = struct.pack("<fi", ltp, ltt_epoch)
    return _HEADER_STRUCT.pack(2, len(body), 1, security_id) + body


def _disconnect_bytes(*, security_id: int = 0, reason_code: int = 805) -> bytes:
    body = struct.pack("<h", reason_code)
    return _HEADER_STRUCT.pack(50, len(body), 1, security_id) + body


def test_a_normal_session_reaches_running_and_converts_every_packet() -> None:
    steps: list[WorkerEvent | bytes] = [
        *NORMAL_STARTUP_EVENTS,
        _ticker_bytes(security_id=2885, ltp=2900.0),
        _ticker_bytes(security_id=1333, ltp=1650.0),
        *CLEAN_SHUTDOWN_EVENTS,
    ]

    outcome = run_worker_session(steps, security_id_to_symbol=_SECURITY_MAP)

    assert outcome.final_state is WorkerState.STOPPED
    assert len(outcome.quotes) == 2
    assert outcome.quotes[0].instrument_id == "NSE:RELIANCE"
    assert outcome.quotes[1].instrument_id == "NSE:HDFCBANK"
    assert outcome.decode_failures == 0
    assert outcome.rejected_packets == ()
    assert outcome.illegal_transitions == 0


def test_malformed_packet_never_crashes_the_session_and_is_counted() -> None:
    steps: list[WorkerEvent | bytes] = [
        *NORMAL_STARTUP_EVENTS,
        b"\x02\x00",  # truncated - not even a full header
        _ticker_bytes(security_id=2885, ltp=2900.0),  # session continues normally after
        *CLEAN_SHUTDOWN_EVENTS,
    ]

    outcome = run_worker_session(steps, security_id_to_symbol=_SECURITY_MAP)

    assert outcome.decode_failures == 1
    assert len(outcome.quotes) == 1
    assert outcome.final_state is WorkerState.STOPPED


def test_unknown_instrument_packet_is_rejected_not_fabricated_and_session_continues() -> None:
    steps: list[WorkerEvent | bytes] = [
        *NORMAL_STARTUP_EVENTS,
        _ticker_bytes(security_id=999999, ltp=100.0),  # not in the security map
        _ticker_bytes(security_id=2885, ltp=2900.0),
        *CLEAN_SHUTDOWN_EVENTS,
    ]

    outcome = run_worker_session(steps, security_id_to_symbol=_SECURITY_MAP)

    assert len(outcome.quotes) == 1
    assert len(outcome.rejected_packets) == 1
    assert outcome.rejected_packets[0].reason is QuoteConversionRejectionReason.UNKNOWN_SECURITY_ID
    assert outcome.rejected_packets[0].security_id == 999999


def test_a_disconnect_packet_moves_the_session_into_reconnecting() -> None:
    steps: list[WorkerEvent | bytes] = [
        *NORMAL_STARTUP_EVENTS,
        _ticker_bytes(security_id=2885, ltp=2900.0),
        _disconnect_bytes(reason_code=805),
    ]

    outcome = run_worker_session(steps, security_id_to_symbol=_SECURITY_MAP)

    assert outcome.final_state is WorkerState.RECONNECTING
    assert len(outcome.quotes) == 1  # the packet BEFORE the disconnect was still processed


def test_a_successful_reconnect_resumes_processing_packets() -> None:
    steps: list[WorkerEvent | bytes] = [
        *NORMAL_STARTUP_EVENTS,
        _disconnect_bytes(),
        *NORMAL_RECONNECT_EVENTS,
        _ticker_bytes(security_id=2885, ltp=2905.0),  # arrives AFTER reconnect
        *CLEAN_SHUTDOWN_EVENTS,
    ]

    outcome = run_worker_session(steps, security_id_to_symbol=_SECURITY_MAP)

    assert outcome.final_state is WorkerState.STOPPED
    assert len(outcome.quotes) == 1
    assert outcome.illegal_transitions == 0


def test_reconnect_exhaustion_ends_the_session_failed() -> None:
    steps: list[WorkerEvent | bytes] = [
        *NORMAL_STARTUP_EVENTS,
        _disconnect_bytes(),
        WorkerEvent.RECONNECT_EXHAUSTED,
    ]

    outcome = run_worker_session(steps, security_id_to_symbol=_SECURITY_MAP)

    assert outcome.final_state is WorkerState.FAILED


def test_an_illegal_scripted_event_is_refused_not_silently_applied() -> None:
    """A `SUBSCRIBED` event while already `RUNNING` has no legal
    transition (see `worker_state.py`'s own transition table) - the
    session must refuse it, count it, and continue in the SAME state,
    proving the orchestration layer never bypasses the state machine's
    own refusal semantics."""
    steps: list[WorkerEvent | bytes] = [
        *NORMAL_STARTUP_EVENTS,
        WorkerEvent.SUBSCRIBED,  # illegal - already RUNNING
        _ticker_bytes(security_id=2885, ltp=2900.0),
    ]

    outcome = run_worker_session(steps, security_id_to_symbol=_SECURITY_MAP)

    assert outcome.illegal_transitions == 1
    assert outcome.final_state is WorkerState.RUNNING  # unchanged, still processes the packet
    assert len(outcome.quotes) == 1


def test_empty_session_stays_stopped() -> None:
    outcome = run_worker_session([], security_id_to_symbol=_SECURITY_MAP)

    assert outcome.final_state is WorkerState.STOPPED
    assert outcome.quotes == ()
    assert outcome.decode_failures == 0


def test_quotes_preserve_real_decoded_timestamps() -> None:
    epoch = int(datetime(2026, 1, 5, 6, 0, tzinfo=UTC).timestamp())
    steps: list[WorkerEvent | bytes] = [
        *NORMAL_STARTUP_EVENTS,
        _ticker_bytes(security_id=2885, ltp=2900.0, ltt_epoch=epoch),
    ]

    outcome = run_worker_session(steps, security_id_to_symbol=_SECURITY_MAP)

    assert outcome.quotes[0].timestamp == normalize_dhan_websocket_timestamp(epoch)
