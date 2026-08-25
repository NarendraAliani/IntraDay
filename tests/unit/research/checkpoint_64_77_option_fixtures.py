# File: tests/unit/research/checkpoint_64_77_option_fixtures.py
#
# Checkpoint 64.77: SYNTHETIC, DETERMINISTIC option instrument-master
# fixtures.
#
# ***THIS DATA IS FABRICATED FOR TESTING.*** Nothing here was downloaded
# from Dhan, and NO security_id, strike, expiry or lot size below should
# ever be treated as a real, tradable Dhan contract. The COLUMN NAMES
# are real (they are the verified 16-column compact scrip-master header
# recorded in `dhan/instrument_master.py`); the ROW VALUES are invented,
# and the security_ids are deliberately in an obviously-synthetic
# 9000000+ range so that a real one could never be confused for one of
# these. This file exists precisely so that 64.77 can be tested with
# ZERO network access to a live market data provider.
#
# Coverage, per the checkpoint's Phase 12 requirement: RELIANCE CE and
# PE, at TWO strikes, across TWO expiries (8 option rows), plus the
# out-of-scope and non-option neighbours a real file interleaves them
# with - an OPTIDX row, a cash-equity row and a futures row - so the
# filtering is exercised against realistic company, not a pure list.
from __future__ import annotations

from datetime import date

# Fabricated expiries (real-looking Thursdays, but NOT asserted to be
# real exchange expiry dates - Phase 6 forbids deriving expiries, and
# these are read back from the fixture, never computed).
EXPIRY_NEAR = date(2026, 9, 24)
EXPIRY_FAR = date(2026, 10, 29)

STRIKE_LOW = "2400.00"
STRIKE_HIGH = "2500.00"

RELIANCE = "RELIANCE"
RELIANCE_LOT_SIZE = 500
OPTION_TICK_SIZE = "0.05"

_HEADER = (
    "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,"
    "SEM_EXPIRY_CODE,SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,"
    "SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE,"
    "SEM_EXPIRY_FLAG,SEM_EXCH_INSTRUMENT_TYPE,SEM_SERIES,SM_SYMBOL_NAME"
)


def _option_row(
    *,
    security_id: int,
    trading_symbol: str,
    expiry: date,
    strike: str,
    option_type: str,
    instrument_type: str = "OPTSTK",
    underlying: str = RELIANCE,
    lot_size: int = RELIANCE_LOT_SIZE,
) -> str:
    # Dhan publishes expiry as a timestamp; the fixture keeps that shape
    # so the parser's real-world input format is what gets tested.
    return (
        f"NSE,D,{security_id},OPTSTK,0,{trading_symbol},{lot_size},{trading_symbol},"
        f"{expiry.isoformat()} 14:30:00,{strike},{option_type},{OPTION_TICK_SIZE},"
        f"M,{instrument_type},,{underlying}"
    )


# --- The 8 RELIANCE contracts (2 strikes x 2 expiries x CE/PE) --------
_RELIANCE_ROWS = [
    _option_row(
        security_id=9000001,
        trading_symbol="RELIANCE-Sep2026-2400-CE",
        expiry=EXPIRY_NEAR,
        strike=STRIKE_LOW,
        option_type="CE",
    ),
    _option_row(
        security_id=9000002,
        trading_symbol="RELIANCE-Sep2026-2400-PE",
        expiry=EXPIRY_NEAR,
        strike=STRIKE_LOW,
        option_type="PE",
    ),
    _option_row(
        security_id=9000003,
        trading_symbol="RELIANCE-Sep2026-2500-CE",
        expiry=EXPIRY_NEAR,
        strike=STRIKE_HIGH,
        option_type="CE",
    ),
    _option_row(
        security_id=9000004,
        trading_symbol="RELIANCE-Sep2026-2500-PE",
        expiry=EXPIRY_NEAR,
        strike=STRIKE_HIGH,
        option_type="PE",
    ),
    _option_row(
        security_id=9000005,
        trading_symbol="RELIANCE-Oct2026-2400-CE",
        expiry=EXPIRY_FAR,
        strike=STRIKE_LOW,
        option_type="CE",
    ),
    _option_row(
        security_id=9000006,
        trading_symbol="RELIANCE-Oct2026-2400-PE",
        expiry=EXPIRY_FAR,
        strike=STRIKE_LOW,
        option_type="PE",
    ),
    _option_row(
        security_id=9000007,
        trading_symbol="RELIANCE-Oct2026-2500-CE",
        expiry=EXPIRY_FAR,
        strike=STRIKE_HIGH,
        option_type="CE",
    ),
    _option_row(
        security_id=9000008,
        trading_symbol="RELIANCE-Oct2026-2500-PE",
        expiry=EXPIRY_FAR,
        strike=STRIKE_HIGH,
        option_type="PE",
    ),
]

# --- Out-of-scope / non-option neighbours ------------------------------
INDEX_OPTION_ROW = _option_row(
    security_id=9000101,
    trading_symbol="NIFTY-Sep2026-24000-CE",
    expiry=EXPIRY_NEAR,
    strike="24000.00",
    option_type="CE",
    instrument_type="OPTIDX",
    underlying="NIFTY",
    lot_size=75,
)
_EQUITY_ROW = "NSE,E,2885,EQUITY,0,RELIANCE,1,Reliance Industries,,0,,0.05,,ES,EQ,RELIANCE"
_FUTURES_ROW = (
    "NSE,D,9000201,FUTSTK,0,RELIANCE-Sep2026-FUT,500,RELIANCE-Sep2026-FUT,"
    f"{EXPIRY_NEAR.isoformat()} 14:30:00,0,,0.05,M,FUTSTK,,RELIANCE"
)

SCRIP_MASTER_CSV = "\n".join(
    [_HEADER, _EQUITY_ROW, *_RELIANCE_ROWS[:4], _FUTURES_ROW, INDEX_OPTION_ROW, *_RELIANCE_ROWS[4:]]
)
"""A whole-market fixture: equities, futures, an index option and the 8
RELIANCE stock options, interleaved as a real file would be."""

SCRIP_MASTER_CSV_WITH_DUPLICATE = "\n".join([SCRIP_MASTER_CSV, _RELIANCE_ROWS[0]])
"""Identical republished row - must be accepted idempotently."""

SCRIP_MASTER_CSV_WITH_CONFLICTING_DUPLICATE = "\n".join(
    [
        SCRIP_MASTER_CSV,
        _option_row(
            security_id=9000999,  # SAME contract identity, DIFFERENT security_id
            trading_symbol="RELIANCE-Sep2026-2400-CE-DUP",
            expiry=EXPIRY_NEAR,
            strike=STRIKE_LOW,
            option_type="CE",
        ),
    ]
)
"""Same canonical identity, different provider identity - must raise."""


# --- Detailed-master shape (carries the underlying columns) ------------
DETAILED_HEADER = _HEADER + ",UNDERLYING_SYMBOL,UNDERLYING_SECURITY_ID"
DETAILED_SCRIP_MASTER_CSV = "\n".join([DETAILED_HEADER, _RELIANCE_ROWS[0] + f",{RELIANCE},2885"])
"""The compact file has no UNDERLYING_SYMBOL/UNDERLYING_SECURITY_ID
columns; the detailed one does. This fixture proves the mapper prefers
them when present rather than falling back to SM_SYMBOL_NAME."""


__all__ = [
    "DETAILED_SCRIP_MASTER_CSV",
    "EXPIRY_FAR",
    "EXPIRY_NEAR",
    "INDEX_OPTION_ROW",
    "OPTION_TICK_SIZE",
    "RELIANCE",
    "RELIANCE_LOT_SIZE",
    "SCRIP_MASTER_CSV",
    "SCRIP_MASTER_CSV_WITH_CONFLICTING_DUPLICATE",
    "SCRIP_MASTER_CSV_WITH_DUPLICATE",
    "STRIKE_HIGH",
    "STRIKE_LOW",
]
