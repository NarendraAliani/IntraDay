# tests/unit/infrastructure/market_data_providers/test_dhan_instrument_master.py
#
# Follow-up to Checkpoint 63.x: proves the tolerant CSV parser correctly
# extracts NSE/BSE cash-equity symbols and excludes other segments/
# exchanges, and that an unrecognizable schema raises loudly rather than
# silently returning wrong data. Never makes a real network call - only
# `_parse_scrip_master()` (pure function) is exercised directly.
from __future__ import annotations

import pytest

from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    InstrumentMasterParseError,
    _parse_scrip_master,
)


def test_parses_nse_and_bse_equity_rows_only() -> None:
    csv_text = (
        "EXCH_ID,SEGMENT,SYMBOL_NAME\n"
        "NSE,Equity,RELIANCE\n"
        "NSE,Equity,TCS\n"
        "BSE,Equity,RELIANCE\n"
        "NSE,Derivatives,RELIANCE24AUGFUT\n"
        "MCX,Commodity,GOLD\n"
    )

    result = _parse_scrip_master(csv_text)

    assert result["NSE"] == ("RELIANCE", "TCS")
    assert result["BSE"] == ("RELIANCE",)
    assert "MCX" not in result


def test_deduplicates_repeated_symbols() -> None:
    csv_text = "EXCH_ID,SEGMENT,SYMBOL_NAME\nNSE,Equity,RELIANCE\nNSE,Equity,RELIANCE\n"

    result = _parse_scrip_master(csv_text)

    assert result["NSE"] == ("RELIANCE",)


def test_tolerates_alternate_column_name_casing_and_aliases() -> None:
    csv_text = "sem_exm_exch_id,sem_segment,sem_trading_symbol\nNSE,EQ,INFY\n"

    result = _parse_scrip_master(csv_text)

    assert result["NSE"] == ("INFY",)


def test_unrecognizable_schema_raises_loudly_never_silently_wrong() -> None:
    csv_text = "totally_unknown_column_a,totally_unknown_column_b\nfoo,bar\n"

    with pytest.raises(InstrumentMasterParseError):
        _parse_scrip_master(csv_text)
