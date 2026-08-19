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
# CHECKPOINT 64 UPDATE: the "full scrip-master ingestion pipeline" this
# module's own docstring named as the natural next increment now exists
# (`instrument_master.py`, built for historical/backtesting instrument
# selection - it captures the real Dhan scrip master INCLUDING each
# instrument's real `security_id`, not just symbol/display_name). This
# was a genuine, named architectural inconsistency (NewStatus.md, live-
# quote universe still hardcoded to 4 symbols while the historical side
# covered ~3,100): a symbol NOT in `_KNOWN_INSTRUMENTS` now falls back
# to a real scrip-master lookup instead of unconditionally raising -
# `MARKET_DATA_OBSERVATION_SYMBOLS` is no longer capped at four hand-
# verified entries. `_KNOWN_INSTRUMENTS` is kept (not deleted) as a
# small, zero-network-call fast path for the default/common case - the
# architecture no longer DEPENDS on it being exhaustive.
from __future__ import annotations

import os
from dataclasses import dataclass

from intraday.application.services.instrument_master import InstrumentMasterProvider
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    InstrumentMasterUnavailableError,
)

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
    """Raised when `MARKET_DATA_OBSERVATION_SYMBOLS` names a symbol
    found in NEITHER `_KNOWN_INSTRUMENTS` NOR the real Dhan scrip
    master - refusing to silently drop it or guess a security_id
    (Checkpoint 23 §4's "do not invent API endpoints" extends to
    payload identifiers, not just URLs)."""


def _resolve_via_scrip_master(
    symbol: str, instrument_master: InstrumentMasterProvider
) -> DhanInstrument | None:
    """The Checkpoint 64 fallback path - real scrip-master lookup for
    any symbol `_KNOWN_INSTRUMENTS` doesn't cover. Returns `None`
    (never raises) on ANY resolution failure - master unavailable, or
    the symbol genuinely not found - so the caller's own single
    `UnknownObservationSymbolError` remains the one place this whole
    function reports "could not resolve," regardless of WHY."""
    try:
        entries = instrument_master.list_instruments(Exchange.NSE)
    except InstrumentMasterUnavailableError:
        return None
    for entry in entries:
        if entry.symbol == symbol and entry.security_id is not None:
            return DhanInstrument(symbol=symbol, security_id=entry.security_id)
    return None


def observation_universe(
    *, instrument_master: InstrumentMasterProvider | None = None
) -> tuple[DhanInstrument, ...]:
    """The configured observation universe (Checkpoint 23 §7) - read
    from `MARKET_DATA_OBSERVATION_SYMBOLS` (comma-separated symbols),
    defaulting to the four symbols this checkpoint's brief itself named
    as an example. Configuration-driven, not hard-coded into any
    business logic - callers never hard-code a symbol list themselves.

    `instrument_master` (Checkpoint 64): the real scrip-master fallback
    for any symbol not in the small, zero-network `_KNOWN_INSTRUMENTS`
    table below - defaults to the real `DhanInstrumentMasterProvider`
    (imported lazily, only when actually needed, so every existing
    caller using only the four `_KNOWN_INSTRUMENTS` symbols still makes
    ZERO network calls, exactly as before). Tests inject a fake here to
    prove the fallback path without a real network call."""
    raw = os.environ.get("MARKET_DATA_OBSERVATION_SYMBOLS", _DEFAULT_OBSERVATION_SYMBOLS)
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
    instruments = []
    for symbol in symbols:
        instrument = _KNOWN_INSTRUMENTS.get(symbol)
        if instrument is None:
            provider = instrument_master
            if provider is None:
                from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
                    DhanInstrumentMasterProvider,
                )

                provider = DhanInstrumentMasterProvider()
            instrument = _resolve_via_scrip_master(symbol, provider)
        if instrument is None:
            raise UnknownObservationSymbolError(
                f"'{symbol}' has no verified Dhan security_id mapping in "
                "infrastructure/market_data_providers/dhan/instruments.py and was not "
                "found in the real Dhan scrip master either - refusing to guess."
            )
        instruments.append(instrument)
    return tuple(instruments)
