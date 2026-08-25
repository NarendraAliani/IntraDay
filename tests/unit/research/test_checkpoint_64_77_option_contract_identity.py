# File: tests/unit/research/test_checkpoint_64_77_option_contract_identity.py
#
# Checkpoint 64.77: OptionContract identity, validation, Dhan mapping
# and the stock-option instrument-master query surface.
#
# OFFLINE AND DETERMINISTIC. No socket, no HTTP, no Dhan, no database,
# no credentials. Every scrip-master row is synthesised in-process by
# `checkpoint_64_77_option_fixtures` (see that module's fabrication
# disclaimer). The one HTTP-capable class in the provider module
# (`DhanOptionInstrumentMasterProvider`) is never instantiated here -
# these tests drive the pure parse/map functions it delegates to, which
# is exactly the boundary that lets an option universe be tested with
# the market closed.
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from intraday.application.services.option_instrument_master import (
    DuplicateOptionContractError,
    OptionInstrumentMasterService,
    historical_snapshot_requirement,
)
from intraday.domain.instrument.contracts import InstrumentType
from intraday.domain.instrument.options import (
    DerivativeSegment,
    OptionContract,
    OptionContractIdentityError,
    OptionInstrumentRecord,
    OptionType,
    OptionUnderlyingClass,
    ProviderOptionIdentity,
    make_option_contract_id,
    normalise_strike,
    require_stock_option,
)
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    DHAN_PROVIDER_NAME,
    NSE_FNO_SEGMENT,
    InstrumentMasterParseError,
    option_contract_from_scrip_row,
    parse_option_scrip_master,
)
from tests.unit.research.checkpoint_64_77_option_fixtures import (
    DETAILED_SCRIP_MASTER_CSV,
    EXPIRY_FAR,
    EXPIRY_NEAR,
    RELIANCE,
    RELIANCE_LOT_SIZE,
    SCRIP_MASTER_CSV,
    SCRIP_MASTER_CSV_WITH_CONFLICTING_DUPLICATE,
    SCRIP_MASTER_CSV_WITH_DUPLICATE,
)


def _contract(**overrides: object) -> OptionContract:
    kwargs: dict[str, object] = {
        "exchange": Exchange.NSE,
        "segment": DerivativeSegment.NSE_FNO,
        "underlying_symbol": RELIANCE,
        "underlying_class": OptionUnderlyingClass.STOCK,
        "expiry": EXPIRY_NEAR,
        "strike": Decimal("2400.00"),
        "option_type": OptionType.CE,
        "lot_size": RELIANCE_LOT_SIZE,
        "tick_size": Decimal("0.05"),
    }
    kwargs.update(overrides)
    return OptionContract(**kwargs)  # type: ignore[arg-type]


class _StaticProvider:
    """A provider that serves a fixed, in-memory record set - the
    injection seam that keeps every test below network-free."""

    def __init__(self, csv_text: str) -> None:
        self._records = parse_option_scrip_master(csv_text)

    def list_option_contracts(self, exchange: Exchange) -> tuple[OptionInstrumentRecord, ...]:
        return self._records if exchange is Exchange.NSE else ()


def _service(csv_text: str = SCRIP_MASTER_CSV) -> OptionInstrumentMasterService:
    return OptionInstrumentMasterService(provider=_StaticProvider(csv_text))


# =====================================================================
# Phase 2/3 - canonical identity
# =====================================================================
def test_valid_ce_and_pe_contracts_are_constructible() -> None:
    assert _contract(option_type=OptionType.CE).option_type is OptionType.CE
    assert _contract(option_type=OptionType.PE).option_type is OptionType.PE


def test_contract_id_is_deterministic_and_provider_independent() -> None:
    """The same exchange/underlying/expiry/strike/type must always yield
    the same identity - and no security_id participates in it, which is
    what lets a contract keep its identity if a provider reassigns ids."""
    first = _contract().contract_id
    second = make_option_contract_id(
        exchange=Exchange.NSE,
        underlying_symbol="reliance",  # normalised on the way in
        expiry=EXPIRY_NEAR,
        strike=Decimal("2400"),  # a different SPELLING of the same strike
        option_type=OptionType.CE,
    )
    assert first == second == "NSE:FNO:RELIANCE:2026-09-24:2400:CE"
    assert "9000001" not in str(first)


def test_strike_spelling_does_not_fork_identity() -> None:
    for spelling in ("2400", "2400.0", "2400.00", "2400.000"):
        assert normalise_strike(Decimal(spelling)) == "2400"
    assert normalise_strike(Decimal("2400.50")) == "2400.5"


def test_identity_distinguishes_every_key_dimension() -> None:
    base = _contract().contract_id
    assert _contract(option_type=OptionType.PE).contract_id != base
    assert _contract(strike=Decimal("2500.00")).contract_id != base
    assert _contract(expiry=EXPIRY_FAR).contract_id != base
    assert _contract(underlying_symbol="TCS").contract_id != base


def test_lot_and_tick_are_specification_not_identity() -> None:
    """A revised lot size describes the SAME contract, so it must not
    mint a second identity."""
    assert _contract(lot_size=250).contract_id == _contract().contract_id
    assert _contract(tick_size=Decimal("0.10")).contract_id == _contract().contract_id


def test_identity_object_carries_no_observation_fields() -> None:
    """OI/IV/Greeks/bid/ask are observations, explicitly deferred - they
    must not have leaked into the identity contract."""
    fields = set(OptionContract.__dataclass_fields__)
    forbidden = {
        "open_interest",
        "oi",
        "implied_volatility",
        "iv",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "bid",
        "ask",
        "last_price",
        "premium",
        "volume",
    }
    assert fields & forbidden == set()


# =====================================================================
# Phase 10 - validation (must raise, never silently coerce)
# =====================================================================
@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"option_type": "CE"}, "OptionType"),
        ({"expiry": "2026-09-24"}, "datetime.date"),
        ({"expiry": datetime(2026, 9, 24, 14, 30)}, "datetime.date"),
        ({"strike": 2400.0}, "Decimal"),
        ({"strike": Decimal("0")}, "positive"),
        ({"strike": Decimal("-100")}, "positive"),
        ({"underlying_symbol": ""}, "non-empty"),
        ({"underlying_symbol": "   "}, "non-empty"),
        ({"underlying_symbol": "reliance"}, "normalised"),
        ({"lot_size": 0}, "positive int"),
        ({"lot_size": -5}, "positive int"),
        ({"tick_size": Decimal("0")}, "positive finite"),
        ({"tick_size": 0.05}, "Decimal"),
        ({"exchange": Exchange.BSE}, "product scope"),
        ({"segment": "NSE_FNO"}, "DerivativeSegment"),
    ],
)
def test_invalid_contracts_raise(overrides: dict[str, object], fragment: str) -> None:
    with pytest.raises(OptionContractIdentityError, match=fragment):
        _contract(**overrides)


def test_missing_or_invalid_security_id_is_rejected() -> None:
    for bad in (0, -1, "9000001"):
        with pytest.raises(OptionContractIdentityError, match="security_id"):
            ProviderOptionIdentity(
                provider=DHAN_PROVIDER_NAME,
                security_id=bad,  # type: ignore[arg-type]
                trading_symbol="RELIANCE-Sep2026-2400-CE",
                exchange_segment=NSE_FNO_SEGMENT,
            )


def test_optidx_is_rejected_by_a_stock_option_selector() -> None:
    index_option = _contract(
        underlying_symbol="NIFTY",
        underlying_class=OptionUnderlyingClass.INDEX,
        strike=Decimal("24000"),
    )
    assert index_option.is_stock_option is False
    with pytest.raises(OptionContractIdentityError, match="INDEX option"):
        require_stock_option(index_option)
    assert require_stock_option(_contract()) is not None


# =====================================================================
# Phase 11 - Dhan mapping
# =====================================================================
def test_dhan_row_maps_to_canonical_contract_and_preserves_security_id() -> None:
    records = parse_option_scrip_master(SCRIP_MASTER_CSV)
    by_id = {record.contract_id: record for record in records}
    record = by_id["NSE:FNO:RELIANCE:2026-09-24:2400:CE"]

    assert record.contract.underlying_symbol == RELIANCE
    assert record.contract.expiry == EXPIRY_NEAR
    assert record.contract.strike == Decimal("2400.00")
    assert record.contract.option_type is OptionType.CE
    assert record.contract.lot_size == RELIANCE_LOT_SIZE
    assert record.contract.tick_size == Decimal("0.05")
    assert record.contract.segment is DerivativeSegment.NSE_FNO
    # Provider identity preserved beside - not as - the identity.
    assert record.provider_identity.provider == DHAN_PROVIDER_NAME
    assert record.provider_identity.security_id == 9000001
    assert record.provider_identity.exchange_segment == NSE_FNO_SEGMENT


def test_expiry_comes_from_the_master_not_from_a_calendar_rule() -> None:
    """Phase 6: the timestamp Dhan publishes is read; nothing computes
    'last Thursday of the month'."""
    records = parse_option_scrip_master(SCRIP_MASTER_CSV)
    assert {record.contract.expiry for record in records} == {EXPIRY_NEAR, EXPIRY_FAR}


def test_detailed_master_underlying_columns_are_preferred_when_present() -> None:
    (record,) = parse_option_scrip_master(DETAILED_SCRIP_MASTER_CSV)
    assert record.contract.underlying_symbol == RELIANCE
    assert record.provider_identity.underlying_security_id == 2885


def test_compact_master_leaves_underlying_security_id_unfabricated() -> None:
    records = parse_option_scrip_master(SCRIP_MASTER_CSV)
    assert all(r.provider_identity.underlying_security_id is None for r in records)


def test_non_option_rows_are_skipped_but_option_rows_must_parse() -> None:
    """Equity/futures rows are expected company in a whole-market file;
    a malformed OPTION row is a schema change and must surface."""
    records = parse_option_scrip_master(SCRIP_MASTER_CSV)
    assert len(records) == 9  # 8 stock options + 1 index option
    with pytest.raises(OptionContractIdentityError, match="option type"):
        option_contract_from_scrip_row(
            {
                "SEM_EXM_EXCH_ID": "NSE",
                "SEM_EXCH_INSTRUMENT_TYPE": "OPTSTK",
                "SEM_OPTION_TYPE": "XX",
                "SEM_SMST_SECURITY_ID": "9000001",
                "SEM_TRADING_SYMBOL": "X",
                "SEM_EXPIRY_DATE": "2026-09-24 14:30:00",
                "SEM_STRIKE_PRICE": "2400",
                "SEM_LOT_UNITS": "500",
                "SEM_TICK_SIZE": "0.05",
                "SM_SYMBOL_NAME": RELIANCE,
            }
        )


def test_unparseable_expiry_raises_rather_than_guessing() -> None:
    with pytest.raises(OptionContractIdentityError, match="refusing to guess"):
        option_contract_from_scrip_row(
            {
                "SEM_EXM_EXCH_ID": "NSE",
                "SEM_EXCH_INSTRUMENT_TYPE": "OPTSTK",
                "SEM_OPTION_TYPE": "CE",
                "SEM_SMST_SECURITY_ID": "9000001",
                "SEM_TRADING_SYMBOL": "X",
                "SEM_EXPIRY_DATE": "24-SEP-2026",
                "SEM_STRIKE_PRICE": "2400",
                "SEM_LOT_UNITS": "500",
                "SEM_TICK_SIZE": "0.05",
                "SM_SYMBOL_NAME": RELIANCE,
            }
        )


def test_missing_option_columns_are_reported_as_a_schema_change() -> None:
    with pytest.raises(InstrumentMasterParseError, match="SEM_STRIKE_PRICE"):
        parse_option_scrip_master("SEM_EXM_EXCH_ID,SEM_EXCH_INSTRUMENT_TYPE\nNSE,OPTSTK")


# =====================================================================
# Phase 4/5 - instrument master + query surface
# =====================================================================
def test_active_universe_is_stock_options_only() -> None:
    service = _service()
    universe = service.stock_option_universe()
    assert len(universe) == 8
    assert all(record.contract.is_stock_option for record in universe)
    assert service.underlyings() == (RELIANCE,)
    assert "NIFTY" not in service.underlyings()


def test_optidx_is_parseable_but_excluded_from_the_active_universe() -> None:
    """Both halves matter: an index option must be RECOGNISED (so it is
    excluded on purpose) and ABSENT from the universe."""
    parsed = parse_option_scrip_master(SCRIP_MASTER_CSV)
    index_options = [r for r in parsed if not r.contract.is_stock_option]
    assert len(index_options) == 1
    assert index_options[0].contract.underlying_class is OptionUnderlyingClass.INDEX
    assert index_options[0] not in _service().stock_option_universe()


def test_contracts_for_underlying_and_expiry() -> None:
    service = _service()
    assert len(service.contracts_for_underlying(RELIANCE)) == 8
    assert len(service.contracts_for_underlying("reliance", expiry=EXPIRY_NEAR)) == 4
    assert service.contracts_for_underlying("TCS") == ()


def test_available_expiries_are_observed_values_ascending() -> None:
    assert _service().available_expiries(RELIANCE) == (EXPIRY_NEAR, EXPIRY_FAR)
    assert EXPIRY_NEAR < EXPIRY_FAR


def test_ce_and_pe_filters_for_an_expiry() -> None:
    service = _service()
    calls = service.contracts_for_expiry(EXPIRY_NEAR, option_type=OptionType.CE)
    puts = service.contracts_for_expiry(EXPIRY_NEAR, option_type=OptionType.PE)
    assert len(calls) == len(puts) == 2
    assert {r.contract.option_type for r in calls} == {OptionType.CE}
    assert {r.contract.option_type for r in puts} == {OptionType.PE}
    assert len(service.contracts_for_expiry(EXPIRY_NEAR)) == 4


def test_strikes_for_an_expiry() -> None:
    assert _service().strikes_for(RELIANCE, expiry=EXPIRY_FAR) == (
        Decimal("2400.00"),
        Decimal("2500.00"),
    )


def test_exact_contract_lookup_and_provider_security_id() -> None:
    service = _service()
    record = service.find_contract(
        underlying_symbol=RELIANCE,
        expiry=EXPIRY_FAR,
        strike=Decimal("2500"),  # unpadded spelling still resolves
        option_type=OptionType.PE,
    )
    assert record is not None
    assert record.provider_identity.security_id == 9000008
    assert service.provider_security_id_for(record.contract) == 9000008
    assert (
        service.find_contract(
            underlying_symbol=RELIANCE,
            expiry=EXPIRY_NEAR,
            strike=Decimal("9999"),
            option_type=OptionType.CE,
        )
        is None
    )


def test_find_contract_rejects_a_float_strike() -> None:
    with pytest.raises(OptionContractIdentityError, match="Decimal"):
        _service().find_contract(
            underlying_symbol=RELIANCE,
            expiry=EXPIRY_NEAR,
            strike=2400.0,  # type: ignore[arg-type]
            option_type=OptionType.CE,
        )


def test_universe_ordering_is_deterministic() -> None:
    assert _service().stock_option_universe() == _service().stock_option_universe()
    keys = [
        (
            r.contract.underlying_symbol,
            r.contract.expiry,
            r.contract.strike,
            r.contract.option_type.value,
        )
        for r in _service().stock_option_universe()
    ]
    assert keys == sorted(keys)


def test_provider_returns_nothing_for_an_out_of_scope_exchange() -> None:
    service = OptionInstrumentMasterService(
        provider=_StaticProvider(SCRIP_MASTER_CSV), exchange=Exchange.BSE
    )
    assert service.stock_option_universe() == ()


# =====================================================================
# Idempotency / duplicates
# =====================================================================
def test_identical_republished_row_is_idempotent() -> None:
    assert len(_service(SCRIP_MASTER_CSV_WITH_DUPLICATE).stock_option_universe()) == 8


def test_conflicting_duplicate_identity_is_rejected() -> None:
    with pytest.raises(DuplicateOptionContractError, match="conflicting duplicate"):
        _service(SCRIP_MASTER_CSV_WITH_CONFLICTING_DUPLICATE).stock_option_universe()


# =====================================================================
# Phase 7/8/9 - readiness statements and coexistence
# =====================================================================
def test_historical_snapshot_requirement_is_recorded() -> None:
    text = historical_snapshot_requirement()
    assert "PRESENT-STATE" in text
    assert "UNVERIFIED" in text
    assert "snapshot" in text.lower()


def test_equity_contracts_are_unchanged_by_the_option_scope() -> None:
    """Phase 9: `OptionContract` coexists with the equity contracts
    WITHOUT pushing option fields into them. `InstrumentType` still has
    no derivative member - options are a sibling contract, not a case
    inside the equity enum."""
    assert {member.name for member in InstrumentType} == {"EQUITY", "INDEX"}
    equity_fields = set(
        __import__(
            "intraday.domain.instrument.contracts", fromlist=["Instrument"]
        ).Instrument.__dataclass_fields__
    )
    assert equity_fields & {"expiry", "strike", "option_type", "underlying_symbol"} == set()


def test_archive_compatibility_key_is_expressible_from_identity() -> None:
    """Phase 8: no archive table is modified this checkpoint, but a
    future option archive must be able to key a cell by underlying/
    expiry/strike/CE-PE. The canonical identity is a single stable
    string that both carries and round-trips those dimensions."""
    contract = _contract()
    contract_id = str(contract.contract_id)
    exchange, segment, underlying, expiry, strike, option_type = contract_id.split(":")
    assert (exchange, segment) == ("NSE", "FNO")
    assert underlying == RELIANCE
    assert date.fromisoformat(expiry) == EXPIRY_NEAR
    assert Decimal(strike) == contract.strike
    assert OptionType(option_type) is contract.option_type
