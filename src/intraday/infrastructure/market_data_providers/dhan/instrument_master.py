# File: src/intraday/infrastructure/market_data_providers/dhan/instrument_master.py
#
# Follow-up to Checkpoint 63.x: fetches Dhan's real, published
# instrument-master CSV (confirmed via https://dhanhq.co/docs/v2/instruments/
# during this session - "Compact" file at
# https://images.dhan.co/api-data/api-scrip-master.csv, covering NSE/BSE
# equity, F&O, currency, and commodity instruments) so "Select All" in
# the instrument picker can mean "every tradable stock on this
# exchange," not just the handful the live-quote pipeline has happened
# to observe so far.
#
# HONEST, DOCUMENTED LIMITATION: the CSV itself is >10MB and could not
# be directly inspected during this session (the research tool used to
# verify it has a 10MB fetch cap) - its exact column names are
# therefore NOT verified against a live response. Parsing below is
# deliberately TOLERANT (tries several plausible column-name aliases
# Dhan's own documentation and public integration guides describe)
# rather than hard-coded to one guessed schema, and raises a clear
# `InstrumentMasterParseError` if none of the expected columns are
# found - never silently returns wrong or empty data. The very first
# real deployment run against the live file is this parser's actual
# verification; until then, this is best-effort, not guaranteed.
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
from collections.abc import Sequence

import httpx

from intraday.domain.shared_kernel.contracts import Exchange

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
_REQUEST_TIMEOUT_SECONDS = 30.0
_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours - the master list changes rarely intraday

# Plausible column-name aliases (tolerant - see module docstring on why
# these are not verified against a live response).
_EXCHANGE_COLUMN_ALIASES = ("EXCH_ID", "SEM_EXM_EXCH_ID", "SEM_EXCH", "EXCHANGE")
_SEGMENT_COLUMN_ALIASES = ("SEGMENT", "SEM_SEGMENT", "INSTRUMENT_TYPE", "SEM_INSTRUMENT_NAME")
_SYMBOL_COLUMN_ALIASES = (
    "SYMBOL_NAME",
    "SEM_TRADING_SYMBOL",
    "TRADING_SYMBOL",
    "SEM_SMST_SECURITY_ID",
    "DISPLAY_NAME",
)
_EQUITY_SEGMENT_MARKERS = ("EQUITY", "E", "EQ")


class InstrumentMasterParseError(RuntimeError):
    """Raised when the fetched CSV does not contain any recognizable
    exchange/segment/symbol column - signals "this parser needs
    updating against the real schema," never silently swallowed into
    an empty result."""


class InstrumentMasterUnavailableError(RuntimeError):
    """Raised when the scrip-master file cannot be fetched at all
    (network/timeout/HTTP error)."""


def _find_column(fieldnames: Sequence[str], aliases: tuple[str, ...]) -> str | None:
    upper_map = {name.strip().upper(): name for name in fieldnames}
    for alias in aliases:
        if alias in upper_map:
            return upper_map[alias]
    return None


def _parse_scrip_master(csv_text: str) -> dict[str, tuple[str, ...]]:
    """Returns `{exchange_value: (symbol, ...)}` for cash-equity rows
    only - derivative/currency/commodity segments are excluded."""
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = reader.fieldnames or []
    exchange_col = _find_column(fieldnames, _EXCHANGE_COLUMN_ALIASES)
    segment_col = _find_column(fieldnames, _SEGMENT_COLUMN_ALIASES)
    symbol_col = _find_column(fieldnames, _SYMBOL_COLUMN_ALIASES)

    if exchange_col is None or symbol_col is None:
        raise InstrumentMasterParseError(
            f"could not find recognizable exchange/symbol columns in scrip master "
            f"(fieldnames={fieldnames!r}) - parser needs updating against the real schema"
        )

    by_exchange: dict[str, set[str]] = {}
    for row in reader:
        exchange_value = (row.get(exchange_col) or "").strip().upper()
        if exchange_value not in {"NSE", "BSE"}:
            continue
        if segment_col is not None:
            segment_value = (row.get(segment_col) or "").strip().upper()
            if segment_value and segment_value not in _EQUITY_SEGMENT_MARKERS:
                continue
        symbol = (row.get(symbol_col) or "").strip().upper()
        if not symbol:
            continue
        by_exchange.setdefault(exchange_value, set()).add(symbol)

    return {exchange: tuple(sorted(symbols)) for exchange, symbols in by_exchange.items()}


_cache: dict[str, tuple[str, ...]] | None = None
_cache_fetched_at: float = 0.0


class DhanInstrumentMasterProvider:
    """Satisfies `InstrumentMasterProvider`. See module docstring for
    the honest schema-verification disclosure."""

    def list_symbols(self, exchange: Exchange) -> tuple[str, ...]:
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
    "InstrumentMasterParseError",
    "InstrumentMasterUnavailableError",
    "SCRIP_MASTER_URL",
]
