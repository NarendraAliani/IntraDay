# File: src/intraday/infrastructure/market_data_providers/dhan/instruments.py
#
# Checkpoint 23: the initial, small, CONFIGURATION-DRIVEN observation
# universe (Checkpoint 23 §7 - "must be configuration-driven, not
# hard-coded into business logic") and its mapping to Dhan's own
# `security_id` identifiers, which the Market Quote API requires
# (Checkpoint 23 §4 - "do not invent API endpoints"/payloads).
#
# Symbol -> security_id mapping source (Checkpoint 23 §4's "verify the
# current official Dhan API specification" - not invented):
# Dhan's own published, official instrument/scrip master CSV,
# https://images.dhan.co/api-data/api-scrip-master.csv, fetched and
# cross-checked directly during this checkpoint (2026-08-14). Each row
# below is the exact (SEM_EXM_EXCH_ID=NSE, SEM_SEGMENT=E,
# SEM_SMST_SECURITY_ID, SEM_TRADING_SYMBOL) tuple found in that file for
# the four default symbols - not guessed, not derived, not carried over
# from any other broker's identifiers.
#
# A full scrip-master ingestion pipeline (to support an arbitrary,
# larger universe) is explicitly NOT built this checkpoint - seem
# unnecessary machinery for a "small configured list of NSE cash-equity
# symbols" (Checkpoint 23 §7). If the observation universe grows beyond
# a hand-maintained list, that ingestion pipeline is the natural next
# increment - documented as a known limitation, not silently deferred.
from __future__ import annotations

import os
from dataclasses import dataclass

# Dhan's own exchange-segment vocabulary for the Market Quote API - see
# docs/architecture/LIVE_MARKET_DATA_ARCHITECTURE.md. NSE cash equity
# only, matching this project's permanent scope (Rule 2).
NSE_EQ_SEGMENT = "NSE_EQ"


@dataclass(frozen=True, slots=True)
class DhanInstrument:
    """One entry in the hand-maintained symbol -> Dhan security_id table."""

    symbol: str
    security_id: int
    exchange_segment: str = NSE_EQ_SEGMENT


# Verified against Dhan's official scrip-master CSV, 2026-08-14 (see
# module docstring above). Do not add an entry here without the same
# verification - never invent a security_id.
_KNOWN_INSTRUMENTS: dict[str, DhanInstrument] = {
    "RELIANCE": DhanInstrument(symbol="RELIANCE", security_id=2885),
    "TCS": DhanInstrument(symbol="TCS", security_id=11536),
    "INFY": DhanInstrument(symbol="INFY", security_id=1594),
    "HDFCBANK": DhanInstrument(symbol="HDFCBANK", security_id=1333),
}

_DEFAULT_OBSERVATION_SYMBOLS = "RELIANCE,TCS,INFY,HDFCBANK"


class UnknownObservationSymbolError(ValueError):
    """Raised when `MARKET_DATA_OBSERVATION_SYMBOLS` names a symbol with
    no verified entry in `_KNOWN_INSTRUMENTS` - refusing to silently
    drop it or guess a security_id (Checkpoint 23 §4's "do not invent
    API endpoints" extends to payload identifiers, not just URLs)."""


def observation_universe() -> tuple[DhanInstrument, ...]:
    """The configured observation universe (Checkpoint 23 §7) - read
    from `MARKET_DATA_OBSERVATION_SYMBOLS` (comma-separated symbols),
    defaulting to the four symbols this checkpoint's brief itself named
    as an example. Configuration-driven, not hard-coded into any
    business logic - callers never hard-code a symbol list themselves."""
    raw = os.environ.get("MARKET_DATA_OBSERVATION_SYMBOLS", _DEFAULT_OBSERVATION_SYMBOLS)
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
    instruments = []
    for symbol in symbols:
        instrument = _KNOWN_INSTRUMENTS.get(symbol)
        if instrument is None:
            raise UnknownObservationSymbolError(
                f"'{symbol}' has no verified Dhan security_id mapping in "
                "infrastructure/market_data_providers/dhan/instruments.py - "
                "refusing to guess. Add a verified entry first."
            )
        instruments.append(instrument)
    return tuple(instruments)
