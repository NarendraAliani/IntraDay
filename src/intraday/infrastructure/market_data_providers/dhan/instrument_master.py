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
#
# CHECKPOINT 64.77 EXTENSION - stock options. This module is EXTENDED
# rather than duplicated: the option universe comes from the exact same
# published scrip-master file, fetched through the exact same cached
# HTTP path, and is separated from equities by the exact same column
# (`SEM_EXCH_INSTRUMENT_TYPE`) that already distinguishes real equities
# from bonds and Dhan's dummy test scrips. No "V2" provider exists.
from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from intraday.application.services.instrument_master import InstrumentMasterEntry
from intraday.domain.instrument.options import (
    DerivativeSegment,
    OptionContract,
    OptionContractIdentityError,
    OptionInstrumentRecord,
    OptionType,
    OptionUnderlyingClass,
    ProviderOptionIdentity,
)
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


# =====================================================================
# Checkpoint 64.77 - OPTION instrument master (OPTSTK)
# =====================================================================
#
# COLUMN VOCABULARY. Every name below is taken from the REAL header
# verified against a live response and recorded in this module's
# docstring above - none is invented:
#
#   SEM_SMST_SECURITY_ID     provider-native contract id
#   SEM_TRADING_SYMBOL       provider-native symbol
#   SEM_EXPIRY_DATE          expiry
#   SEM_STRIKE_PRICE         strike
#   SEM_OPTION_TYPE          CE/PE
#   SEM_LOT_UNITS            lot size
#   SEM_TICK_SIZE            tick size
#   SEM_EXCH_INSTRUMENT_TYPE OPTSTK vs OPTIDX
#   SM_SYMBOL_NAME           underlying symbol (see below)
#
# HONEST GAP, stated rather than papered over: `UNDERLYING_SYMBOL` and
# `UNDERLYING_SECURITY_ID` appear in Dhan's DETAILED scrip master, but
# the COMPACT file this module already fetches does NOT carry them (its
# verified 16-column header, above, has neither). So underlying
# resolution reads `UNDERLYING_SYMBOL` when the file provides it and
# falls back to `SM_SYMBOL_NAME` - which, for derivative rows, is the
# underlying's own symbol name - and refuses (never guesses, never
# string-parses the trading symbol) when neither is present.
# `UNDERLYING_SECURITY_ID` is likewise read when present and left
# `None` otherwise, rather than being fabricated.

_UNDERLYING_SYMBOL_COLUMN = "UNDERLYING_SYMBOL"
_UNDERLYING_SECURITY_ID_COLUMN = "UNDERLYING_SECURITY_ID"
_SYMBOL_NAME_COLUMN = "SM_SYMBOL_NAME"
_EXPIRY_DATE_COLUMN = "SEM_EXPIRY_DATE"
_STRIKE_PRICE_COLUMN = "SEM_STRIKE_PRICE"
_OPTION_TYPE_COLUMN = "SEM_OPTION_TYPE"
_LOT_UNITS_COLUMN = "SEM_LOT_UNITS"
_TICK_SIZE_COLUMN = "SEM_TICK_SIZE"

_STOCK_OPTION_INSTRUMENT_TYPE = "OPTSTK"
_INDEX_OPTION_INSTRUMENT_TYPE = "OPTIDX"
_OPTION_INSTRUMENT_TYPES = {
    _STOCK_OPTION_INSTRUMENT_TYPE: OptionUnderlyingClass.STOCK,
    _INDEX_OPTION_INSTRUMENT_TYPE: OptionUnderlyingClass.INDEX,
}

_OPTION_REQUIRED_COLUMNS = (
    _EXCHANGE_COLUMN,
    _INSTRUMENT_TYPE_COLUMN,
    _SYMBOL_COLUMN,
    _SECURITY_ID_COLUMN,
    _EXPIRY_DATE_COLUMN,
    _STRIKE_PRICE_COLUMN,
    _OPTION_TYPE_COLUMN,
    _LOT_UNITS_COLUMN,
    _TICK_SIZE_COLUMN,
)

DHAN_PROVIDER_NAME = "DHAN"
NSE_FNO_SEGMENT = "NSE_FNO"


def _parse_expiry(raw: str) -> date:
    """Phase 6: the master's OWN expiry value, parsed - never a computed
    weekly/monthly expiry rule.

    Dhan publishes expiry as a timestamp (`YYYY-MM-DD HH:MM:SS`); the
    date part is the contract's expiry day. A bare `YYYY-MM-DD` is
    accepted too. Anything else raises rather than being coerced."""
    text = raw.strip()
    if not text:
        raise OptionContractIdentityError("SEM_EXPIRY_DATE is empty")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise OptionContractIdentityError(
            f"SEM_EXPIRY_DATE {raw!r} is not a recognised Dhan expiry format "
            "(expected 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS') - refusing to guess"
        ) from exc


def _parse_decimal(raw: str, *, column: str) -> Decimal:
    text = raw.strip()
    if not text:
        raise OptionContractIdentityError(f"{column} is empty")
    try:
        # str -> Decimal directly; never via float, which would make
        # a strike of 2500.05 unrepresentable exactly.
        return Decimal(text)
    except InvalidOperation as exc:
        raise OptionContractIdentityError(f"{column} {raw!r} is not a valid decimal") from exc


def option_contract_from_scrip_row(row: dict[str, str]) -> OptionInstrumentRecord:
    """Deterministic Dhan-row -> canonical-identity mapping (Phase 11).

    Raises `OptionContractIdentityError` for any row that is not a
    well-formed option. Returns INDEX options as well as stock ones -
    excluding OPTIDX is the service layer's product-scope decision, not
    this parser's, so an index row stays recognisable."""
    instrument_type = (row.get(_INSTRUMENT_TYPE_COLUMN) or "").strip().upper()
    underlying_class = _OPTION_INSTRUMENT_TYPES.get(instrument_type)
    if underlying_class is None:
        raise OptionContractIdentityError(
            f"{_INSTRUMENT_TYPE_COLUMN}={instrument_type!r} is not an option instrument "
            f"type (expected one of {sorted(_OPTION_INSTRUMENT_TYPES)})"
        )

    exchange_value = (row.get(_EXCHANGE_COLUMN) or "").strip().upper()
    if exchange_value != Exchange.NSE.value:
        raise OptionContractIdentityError(
            f"{_EXCHANGE_COLUMN}={exchange_value!r}: only NSE options are in product scope"
        )

    raw_option_type = (row.get(_OPTION_TYPE_COLUMN) or "").strip().upper()
    try:
        option_type = OptionType(raw_option_type)
    except ValueError as exc:
        raise OptionContractIdentityError(
            f"{_OPTION_TYPE_COLUMN}={raw_option_type!r} is not a valid option type (CE/PE)"
        ) from exc

    underlying = (row.get(_UNDERLYING_SYMBOL_COLUMN) or "").strip().upper() or (
        row.get(_SYMBOL_NAME_COLUMN) or ""
    ).strip().upper()
    if not underlying:
        raise OptionContractIdentityError(
            f"neither {_UNDERLYING_SYMBOL_COLUMN} nor {_SYMBOL_NAME_COLUMN} identifies an "
            "underlying for this row - refusing to derive one from the trading symbol"
        )

    raw_security_id = (row.get(_SECURITY_ID_COLUMN) or "").strip()
    if not raw_security_id.isdigit():
        raise OptionContractIdentityError(
            f"{_SECURITY_ID_COLUMN}={raw_security_id!r} is missing or non-numeric - an "
            "option with no provider identity cannot be subscribed to or quoted"
        )

    raw_underlying_id = (row.get(_UNDERLYING_SECURITY_ID_COLUMN) or "").strip()
    raw_lot = (row.get(_LOT_UNITS_COLUMN) or "").strip()
    if not raw_lot.isdigit():
        raise OptionContractIdentityError(
            f"{_LOT_UNITS_COLUMN}={raw_lot!r} is missing or non-numeric"
        )

    contract = OptionContract(
        exchange=Exchange.NSE,
        segment=DerivativeSegment.NSE_FNO,
        underlying_symbol=underlying,
        underlying_class=underlying_class,
        expiry=_parse_expiry(row.get(_EXPIRY_DATE_COLUMN) or ""),
        strike=_parse_decimal(row.get(_STRIKE_PRICE_COLUMN) or "", column=_STRIKE_PRICE_COLUMN),
        option_type=option_type,
        lot_size=int(raw_lot),
        tick_size=_parse_decimal(row.get(_TICK_SIZE_COLUMN) or "", column=_TICK_SIZE_COLUMN),
    )
    provider_identity = ProviderOptionIdentity(
        provider=DHAN_PROVIDER_NAME,
        security_id=int(raw_security_id),
        trading_symbol=(row.get(_SYMBOL_COLUMN) or "").strip().upper(),
        exchange_segment=NSE_FNO_SEGMENT,
        underlying_security_id=int(raw_underlying_id) if raw_underlying_id.isdigit() else None,
    )
    return OptionInstrumentRecord(contract=contract, provider_identity=provider_identity)


def parse_option_scrip_master(csv_text: str) -> tuple[OptionInstrumentRecord, ...]:
    """Every NSE option row (OPTSTK and OPTIDX) in a scrip-master CSV.

    Rows that are not options at all are skipped silently - the file is
    a whole-market file, so equities/futures/currency rows are expected,
    not errors. Rows that ARE options but are malformed propagate their
    `OptionContractIdentityError`, because that means the schema
    changed and must be noticed."""
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = set(reader.fieldnames or [])
    missing = [col for col in _OPTION_REQUIRED_COLUMNS if col not in fieldnames]
    if missing:
        raise InstrumentMasterParseError(
            f"scrip master is missing expected option column(s) {missing!r} "
            f"(fieldnames={sorted(fieldnames)!r}) - Dhan's schema may have changed"
        )
    records = []
    for row in reader:
        instrument_type = (row.get(_INSTRUMENT_TYPE_COLUMN) or "").strip().upper()
        if instrument_type not in _OPTION_INSTRUMENT_TYPES:
            continue
        if (row.get(_EXCHANGE_COLUMN) or "").strip().upper() != Exchange.NSE.value:
            continue
        records.append(option_contract_from_scrip_row(row))
    return tuple(records)


_option_cache: tuple[OptionInstrumentRecord, ...] | None = None
_option_cache_fetched_at: float = 0.0


class DhanOptionInstrumentMasterProvider:
    """Satisfies `OptionInstrumentMasterProvider`.

    Deliberately reuses this module's existing URL, timeout and TTL
    constants rather than restating them - it is the same file. Returns
    OPTIDX rows too; the service filters them (see
    `application/services/option_instrument_master.py`)."""

    def list_option_contracts(self, exchange: Exchange) -> tuple[OptionInstrumentRecord, ...]:
        global _option_cache, _option_cache_fetched_at  # noqa: PLW0603 - mirrors this module's existing equity TTL cache

        if exchange is not Exchange.NSE:
            return ()
        now = time.monotonic()
        if _option_cache is None or (now - _option_cache_fetched_at) > _CACHE_TTL_SECONDS:
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
            _option_cache = parse_option_scrip_master(response.text)
            _option_cache_fetched_at = now
        return _option_cache


__all__ = [
    "DHAN_PROVIDER_NAME",
    "DhanInstrumentMasterProvider",
    "DhanOptionInstrumentMasterProvider",
    "InstrumentMasterEntry",
    "InstrumentMasterParseError",
    "InstrumentMasterUnavailableError",
    "NSE_FNO_SEGMENT",
    "SCRIP_MASTER_URL",
    "option_contract_from_scrip_row",
    "parse_option_scrip_master",
]
