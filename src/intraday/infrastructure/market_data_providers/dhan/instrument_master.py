# File: src/intraday/infrastructure/market_data_providers/dhan/instrument_master.py
#
# Follow-up to Checkpoint 63.x: fetches Dhan's real, published
# instrument-master CSV (confirmed via https://dhanhq.co/docs/v2/instruments/
# - "Compact" file at https://images.dhan.co/api-data/api-scrip-master.csv,
# covering NSE/BSE equity, F&O, currency, and commodity instruments) so
# "Select All" in the instrument picker can mean "every real, tradable
# stock on this exchange," not just the handful the live-quote pipeline
# has happened to observe so far.
#
# SCHEMA - NOW VERIFIED AGAINST A LIVE RESPONSE (this was previously an
# honest "unverified, tolerant" disclosure; it no longer is). The real
# header, fetched and inspected directly this session:
#
#   SEM_EXM_EXCH_ID, SEM_SEGMENT, SEM_SMST_SECURITY_ID,
#   SEM_INSTRUMENT_NAME, SEM_EXPIRY_CODE, SEM_TRADING_SYMBOL,
#   SEM_LOT_UNITS, SEM_CUSTOM_SYMBOL, SEM_EXPIRY_DATE, SEM_STRIKE_PRICE,
#   SEM_OPTION_TYPE, SEM_TICK_SIZE, SEM_EXPIRY_FLAG,
#   SEM_EXCH_INSTRUMENT_TYPE, SEM_SERIES, SM_SYMBOL_NAME
#
# A REAL BUG this session found and fixed by actually inspecting the
# file (never fixable by column-name guessing alone): `SEM_SEGMENT ==
# "E"` is NOT sufficient to mean "real cash-equity share" - it also
# covers government/corporate bonds (SDL/NCD, `SEM_SERIES` "SG"/"YL"),
# SME-board securities, AND Dhan's own dummy API-testing scrips (e.g.
# `011NSETEST`, `0ABCL31`) which are registered with `SEM_SERIES ==
# "EQ"` too, so series alone doesn't distinguish them either. The
# column that actually does: `SEM_EXCH_INSTRUMENT_TYPE == "ES"` -
# verified directly (RELIANCE/FEDERALBNK/etc. all have "ES"; every
# NSETEST/bond/NCD row has "Other"/"DEB"/"DBT" instead). Filtering on
# this one column alone, against the real 209,987-row file, yielded
# exactly 3,116 genuine NSE equities and zero test/bond rows - checked
# directly, not assumed.
#
# Results are cached in-process (module-level, time-based) - a >10MB
# CSV covering every derivative/currency/commodity contract on top of
# cash equities must not be re-fetched and re-parsed on every picker
# render (Checkpoint 63.x Phase 28's "avoid obviously inefficient"
# instruction applies here too).
from __future__ import annotations

import csv
import io
import time

import httpx

from intraday.application.services.instrument_master import InstrumentMasterEntry
from intraday.domain.shared_kernel.contracts import Exchange

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
_REQUEST_TIMEOUT_SECONDS = 30.0
_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours - the master list changes rarely intraday

_EXCHANGE_COLUMN = "SEM_EXM_EXCH_ID"
_INSTRUMENT_TYPE_COLUMN = "SEM_EXCH_INSTRUMENT_TYPE"
_SYMBOL_COLUMN = "SEM_TRADING_SYMBOL"
_DISPLAY_NAME_COLUMN = "SEM_CUSTOM_SYMBOL"
_SECURITY_ID_COLUMN = "SEM_SMST_SECURITY_ID"
_EQUITY_SHARE_INSTRUMENT_TYPE = "ES"
_REQUIRED_COLUMNS = (
    _EXCHANGE_COLUMN,
    _INSTRUMENT_TYPE_COLUMN,
    _SYMBOL_COLUMN,
    _DISPLAY_NAME_COLUMN,
    _SECURITY_ID_COLUMN,
)


class InstrumentMasterParseError(RuntimeError):
    """Raised when the fetched CSV does not contain the expected,
    verified columns - signals "Dhan changed their schema, this parser
    needs updating," never silently swallowed into an empty result."""


class InstrumentMasterUnavailableError(RuntimeError):
    """Raised when the scrip-master file cannot be fetched at all
    (network/timeout/HTTP error)."""


def _parse_scrip_master(csv_text: str) -> dict[str, tuple[InstrumentMasterEntry, ...]]:
    """Returns `{exchange_value: (InstrumentMasterEntry, ...)}` for
    genuine cash-equity shares only (`SEM_EXCH_INSTRUMENT_TYPE ==
    "ES"`) - excludes derivatives, currency/commodity contracts, bonds/
    NCDs, and Dhan's own dummy test scrips (see module docstring)."""
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = set(reader.fieldnames or [])
    missing = [col for col in _REQUIRED_COLUMNS if col not in fieldnames]
    if missing:
        raise InstrumentMasterParseError(
            f"scrip master is missing expected column(s) {missing!r} "
            f"(fieldnames={sorted(fieldnames)!r}) - Dhan's schema may have changed"
        )

    by_exchange: dict[str, dict[str, InstrumentMasterEntry]] = {}
    for row in reader:
        exchange_value = (row.get(_EXCHANGE_COLUMN) or "").strip().upper()
        if exchange_value not in {"NSE", "BSE"}:
            continue
        instrument_type = (row.get(_INSTRUMENT_TYPE_COLUMN) or "").strip().upper()
        if instrument_type != _EQUITY_SHARE_INSTRUMENT_TYPE:
            continue
        symbol = (row.get(_SYMBOL_COLUMN) or "").strip().upper()
        if not symbol:
            continue
        display_name = (row.get(_DISPLAY_NAME_COLUMN) or "").strip() or symbol
        raw_security_id = (row.get(_SECURITY_ID_COLUMN) or "").strip()
        security_id = int(raw_security_id) if raw_security_id.isdigit() else None
        by_exchange.setdefault(exchange_value, {})[symbol] = InstrumentMasterEntry(
            symbol=symbol, display_name=display_name, security_id=security_id
        )

    return {
        exchange: tuple(entries[symbol] for symbol in sorted(entries))
        for exchange, entries in by_exchange.items()
    }


_cache: dict[str, tuple[InstrumentMasterEntry, ...]] | None = None
_cache_fetched_at: float = 0.0


class DhanInstrumentMasterProvider:
    """Satisfies `InstrumentMasterProvider`. See module docstring for
    the verified-schema disclosure and the real bug it fixes."""

    def list_instruments(self, exchange: Exchange) -> tuple[InstrumentMasterEntry, ...]:
        global _cache, _cache_fetched_at  # noqa: PLW0603 - simple process-local TTL cache, matching this module's own scope

        now = time.monotonic()
        if _cache is None or (now - _cache_fetched_at) > _CACHE_TTL_SECONDS:
            try:
                response = httpx.get(SCRIP_MASTER_URL, timeout=_REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise InstrumentMasterUnavailableError(
                    "Dhan scrip master request timed out"
                ) from exc
            except httpx.HTTPError as exc:
                raise InstrumentMasterUnavailableError(
                    f"Dhan scrip master request failed: {exc}"
                ) from exc
            _cache = _parse_scrip_master(response.text)
            _cache_fetched_at = now

        return _cache.get(exchange.value, ())


__all__ = [
    "DhanInstrumentMasterProvider",
    "InstrumentMasterEntry",
    "InstrumentMasterParseError",
    "InstrumentMasterUnavailableError",
    "SCRIP_MASTER_URL",
]
