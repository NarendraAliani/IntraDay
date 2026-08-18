# tests/unit/infrastructure/market_data_providers/test_dhan_instrument_master.py
#
# Follow-up to Checkpoint 63.x: proves the parser correctly extracts
# genuine NSE/BSE cash-equity symbols + display names using the REAL,
# verified Dhan scrip-master schema, and - the specific real bug this
# session found by fetching and inspecting the live file directly -
# excludes bonds/NCDs AND Dhan's own dummy test scrips (e.g.
# "011NSETEST"), which share `SEM_SEGMENT == "E"` and even
# `SEM_SERIES == "EQ"` with genuine shares, and are only distinguishable
# by `SEM_EXCH_INSTRUMENT_TYPE == "ES"`. Never makes a real network
# call - only `_parse_scrip_master()` (pure function) is exercised
# directly, using row shapes copied from the real file.
from __future__ import annotations

import pytest

from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    InstrumentMasterEntry,
    InstrumentMasterParseError,
    _parse_scrip_master,
)

_HEADER = (
    "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_EXPIRY_CODE,"
    "SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,"
    "SEM_OPTION_TYPE,SEM_TICK_SIZE,SEM_EXPIRY_FLAG,SEM_EXCH_INSTRUMENT_TYPE,SEM_SERIES,"
    "SM_SYMBOL_NAME"
)


def test_parses_genuine_equity_shares_with_real_display_names() -> None:
    csv_text = (
        _HEADER
        + "\n"
        + (
            "NSE,E,2885,EQUITY,0,RELIANCE,1.0,Reliance Industries,,,,10.0000,NA,ES,EQ,"
            "RELIANCE INDUSTRIES LTD\n"
            "BSE,E,500325,EQUITY,0,RELIANCE,1.0,Reliance Industries,,,,10.0000,NA,ES,EQ,"
            "RELIANCE INDUSTRIES LTD\n"
        )
    )

    result = _parse_scrip_master(csv_text)

    assert result["NSE"] == (
        InstrumentMasterEntry(
            symbol="RELIANCE", display_name="Reliance Industries", security_id=2885
        ),
    )
    assert result["BSE"] == (
        InstrumentMasterEntry(
            symbol="RELIANCE", display_name="Reliance Industries", security_id=500325
        ),
    )


def test_excludes_dhan_dummy_test_scrips_despite_matching_segment_and_series() -> None:
    """The real bug this session found: a test scrip like 011NSETEST has
    SEM_SEGMENT="E" and SEM_SERIES="EQ" - identical to a genuine share
    on both those fields - and is only excluded via
    SEM_EXCH_INSTRUMENT_TYPE != "ES" ("Other" instead)."""
    csv_text = (
        _HEADER
        + "\n"
        + (
            "NSE,E,14747,EQUITY,0,011NSETEST,1.0,011NSETEST,,,,5.0000,NA,Other,EQ,011NSETEST\n"
            "NSE,E,2885,EQUITY,0,RELIANCE,1.0,Reliance Industries,,,,10.0000,NA,ES,EQ,"
            "RELIANCE INDUSTRIES LTD\n"
        )
    )

    result = _parse_scrip_master(csv_text)

    assert result["NSE"] == (
        InstrumentMasterEntry(
            symbol="RELIANCE", display_name="Reliance Industries", security_id=2885
        ),
    )


def test_excludes_bonds_and_debentures_despite_segment_e() -> None:
    csv_text = (
        _HEADER
        + "\n"
        + (
            "NSE,E,1000,EQUITY,0,656MH32,100.0,SDL MH 6.56% 2032,,,,1.0000,NA,DBT,SG,"
            "SDL MH 6.56% 2032\n"
            "NSE,E,763751,EQUITY,0,0ABCL31,1.0,ABCL 0% 2031 SR C2,,,,1.0000,NA,DEB,N0,"
            "ABCL 0% 2031 SR C2\n"
            "NSE,E,2885,EQUITY,0,RELIANCE,1.0,Reliance Industries,,,,10.0000,NA,ES,EQ,"
            "RELIANCE INDUSTRIES LTD\n"
        )
    )

    result = _parse_scrip_master(csv_text)

    assert result["NSE"] == (
        InstrumentMasterEntry(
            symbol="RELIANCE", display_name="Reliance Industries", security_id=2885
        ),
    )


def test_excludes_derivative_and_other_exchange_rows() -> None:
    csv_text = (
        _HEADER
        + "\n"
        + (
            "NSE,D,36687,FUTSTK,0,011NSETEST-Nov2036-FUT,50.0,011NSETEST 27 NOV FUT,"
            "2036-11-27 14:30:00,-0.01000,XX,5.0000,W,FUT,,\n"
            "MCX,E,1,EQUITY,0,GOLD,1.0,Gold,,,,1.0000,NA,ES,EQ,GOLD\n"
        )
    )

    result = _parse_scrip_master(csv_text)

    assert result == {}


def test_falls_back_to_symbol_when_display_name_is_blank() -> None:
    csv_text = _HEADER + "\n" + "NSE,E,1,EQUITY,0,SOMESTOCK,1.0,,,,,1.0000,NA,ES,EQ,\n"

    result = _parse_scrip_master(csv_text)

    assert result["NSE"] == (
        InstrumentMasterEntry(symbol="SOMESTOCK", display_name="SOMESTOCK", security_id=1),
    )


def test_missing_expected_columns_raises_loudly_never_silently_wrong() -> None:
    csv_text = "totally_unknown_column_a,totally_unknown_column_b\nfoo,bar\n"

    with pytest.raises(InstrumentMasterParseError):
        _parse_scrip_master(csv_text)
