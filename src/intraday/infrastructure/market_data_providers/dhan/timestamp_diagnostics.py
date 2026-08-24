# File: src/intraday/infrastructure/market_data_providers/dhan/timestamp_diagnostics.py
#
# Checkpoint 64.64: a deterministic MEASUREMENT framework for the
# timestamp anomaly 64.62 discovered and 64.63 honestly left unresolved
# (see `taskReport.md`'s "Timestamp Root Cause" section - Dhan's own
# public documentation does not describe how the WebSocket epoch field
# is computed server-side, and only ~4 confirmed-live samples exist,
# too small a sample to distinguish "systematic IST-offset bug" from
# "clock skew" or "network/processing delay" with any confidence).
#
# This module does NOT fix the anomaly, does NOT guess a +/-5:30
# constant, and does NOT perform any live collection - it is pure,
# side-effect-free bookkeeping a future REAL NSE SESSION #2 checkpoint
# can wire into the live worker to collect a MUCH larger, statistically
# useful sample. DISABLED BY DEFAULT: `TimestampDiagnosticCollector` is
# never constructed or invoked anywhere in `run_market_data_worker.py`
# this checkpoint - it exists only as tested, ready-to-use
# infrastructure, matching the directive's explicit "prepare, but do
# NOT execute" instruction.
#
# No credential, account ID, or secret ever appears in a sample - only
# `symbol`/`packet_type`/two UTC timestamps/their difference.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from intraday.domain.shared_kernel.contracts import ensure_utc


@dataclass(frozen=True, slots=True)
class TimestampDiagnosticSample:
    """ONE observed (source_timestamp, fetched_at) pair for ONE live
    WebSocket packet - the exact shape needed to later classify the
    anomaly as systematic/variable/packet-type-specific/session-
    specific (Checkpoint 64.64 directive §10). Contains no credential,
    account ID, or secret - only a symbol, a packet-type label, two UTC
    timestamps, and their difference."""

    symbol: str
    packet_type: str  # e.g. "TICKER", "QUOTE" - matches DhanFeedResponseCode member names
    source_timestamp_utc: datetime  # the packet's own decoded last_trade_time
    fetched_at_utc: datetime  # when THIS process observed the packet
    delta_seconds: float  # source_timestamp_utc - fetched_at_utc, signed

    def __post_init__(self) -> None:
        ensure_utc(
            self.source_timestamp_utc,
            field_name="TimestampDiagnosticSample.source_timestamp_utc",
        )
        ensure_utc(self.fetched_at_utc, field_name="TimestampDiagnosticSample.fetched_at_utc")
        if not self.symbol:
            raise ValueError("TimestampDiagnosticSample.symbol must not be empty")
        if not self.packet_type:
            raise ValueError("TimestampDiagnosticSample.packet_type must not be empty")

    def as_safe_dict(self) -> dict[str, str | float]:
        """The exact, sanitized export shape (directive §12) - safe to
        write to a log line, a fixture file, or a diagnostic API
        response. Every value here is either a symbol, a packet-type
        label, an ISO-8601 UTC timestamp, or a float - never anything
        resembling a credential or account identifier."""
        return {
            "symbol": self.symbol,
            "packet_type": self.packet_type,
            "source_timestamp_utc": self.source_timestamp_utc.isoformat(),
            "fetched_at_utc": self.fetched_at_utc.isoformat(),
            "delta_seconds": self.delta_seconds,
        }


def make_timestamp_diagnostic_sample(
    *, symbol: str, packet_type: str, source_timestamp_utc: datetime, fetched_at_utc: datetime
) -> TimestampDiagnosticSample:
    """Convenience constructor computing `delta_seconds` from the two
    timestamps, so a caller (the future live worker wiring) never has
    to compute it separately and risk it drifting from the two raw
    values it is derived from."""
    delta = (source_timestamp_utc - fetched_at_utc).total_seconds()
    return TimestampDiagnosticSample(
        symbol=symbol,
        packet_type=packet_type,
        source_timestamp_utc=source_timestamp_utc,
        fetched_at_utc=fetched_at_utc,
        delta_seconds=delta,
    )


@dataclass(slots=True)
class TimestampDiagnosticCollector:
    """In-memory, side-effect-free (no DB, no file I/O, no network)
    accumulator for `TimestampDiagnosticSample`s - the composition root
    (a future `run_market_data_worker.py`) would construct exactly ONE
    of these when an explicit operator flag requests it (see this
    class's own `enabled` field), call `record()` once per live packet
    observed, and read `summary()` at the end of the session.

    `enabled=False` is the field DEFAULT (Checkpoint 64.64 directive
    §12's "disabled by default unless explicitly requested") -
    `record()` is a silent no-op while disabled, so wiring this into a
    hot packet-processing loop ahead of an operator actually asking for
    it costs nothing and changes no behavior."""

    enabled: bool = False
    _samples: list[TimestampDiagnosticSample] = field(default_factory=list)

    def record(self, sample: TimestampDiagnosticSample) -> None:
        if not self.enabled:
            return
        self._samples.append(sample)

    @property
    def samples(self) -> tuple[TimestampDiagnosticSample, ...]:
        return tuple(self._samples)

    def summary(self) -> dict[str, object]:
        """A statistically-useful-at-a-glance rollup (directive §10:
        "enough samples to determine whether the observed offset is
        systematic, variable, packet-type-specific, session-specific") -
        deliberately does NOT classify or conclude anything itself
        (that judgment belongs to a human reviewing a real, much larger
        sample, not this collector) - only reports the raw counts/
        min/max/mean a reviewer needs to make that judgment."""
        if not self._samples:
            return {"sample_count": 0}
        deltas = [s.delta_seconds for s in self._samples]
        by_packet_type: dict[str, int] = {}
        by_symbol: dict[str, int] = {}
        for s in self._samples:
            by_packet_type[s.packet_type] = by_packet_type.get(s.packet_type, 0) + 1
            by_symbol[s.symbol] = by_symbol.get(s.symbol, 0) + 1
        return {
            "sample_count": len(self._samples),
            "delta_seconds_min": min(deltas),
            "delta_seconds_max": max(deltas),
            "delta_seconds_mean": sum(deltas) / len(deltas),
            "samples_by_packet_type": by_packet_type,
            "samples_by_symbol": by_symbol,
        }

    def export_safe_rows(self) -> tuple[dict[str, str | float], ...]:
        """The exact sanitized fixture/log format (directive §12) - a
        tuple of `as_safe_dict()` outputs, ready to be written to a
        diagnostic file or returned from a future read-only API
        endpoint. Contains no credential, account ID, or secret."""
        return tuple(s.as_safe_dict() for s in self._samples)


__all__ = [
    "TimestampDiagnosticCollector",
    "TimestampDiagnosticSample",
    "make_timestamp_diagnostic_sample",
]
