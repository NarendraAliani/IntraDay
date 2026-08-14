# tests/unit/research/test_indian_cost_model.py
#
# Checkpoint 29: reference-fixture, side-specific, rounding, and
# invariant tests for `IndianCashEquityIntradayCostModel`. Every
# reference number below is hand-computed from the rates documented in
# `docs/architecture/BACKTESTING_ARCHITECTURE.md`'s "Verified Indian
# Cost Schedule" table (Zerodha's official published charges page,
# verified 2026-08-14): brokerage 0.03%/₹20 cap, STT 0.025% (sell only),
# NSE exchange charge 0.00307% (both sides), SEBI ₹10/crore = 0.0001%
# (both sides), GST 18% on (brokerage+exchange+SEBI), stamp duty 0.003%
# (buy only).
from __future__ import annotations

from decimal import Decimal

import pytest

from intraday.research.backtesting.cost_model import (
    BrokeragePolicy,
    CostBreakdown,
    FlatPercentageCostModel,
    IndianCashEquityIntradayCostModel,
    verified_nse_cash_equity_intraday_cost_model,
)


def _model() -> IndianCashEquityIntradayCostModel:
    return verified_nse_cash_equity_intraday_cost_model()


# --- Reference fixtures (Part 13) -------------------------------------------


def test_reference_fixture_a_small_turnover_buy_leg() -> None:
    """Trade A: small turnover, BUY leg (long entry / short exit)."""
    breakdown = _model().cost_breakdown(is_buy=True, notional=Decimal("10000"))
    assert breakdown.brokerage == Decimal("3.00")  # min(10000*0.0003, 20)
    assert breakdown.exchange_transaction_charges == Decimal("0.31")  # 10000*0.0000307=0.307
    assert breakdown.sebi_charges == Decimal("0.01")  # 10000*0.000001=0.01
    assert breakdown.gst == Decimal("0.60")  # 18%*(3.00+0.307+0.01)=0.59706
    assert breakdown.stt == Decimal("0.00")  # buy leg - never charged
    assert breakdown.stamp_duty == Decimal("0.30")  # 10000*0.00003=0.30 - buy leg only
    assert breakdown.total == Decimal("4.22")


def test_reference_fixture_a_sell_leg() -> None:
    """Trade A's matching SELL leg (long exit / short entry) at a
    slightly higher notional - proves STT applies here, stamp duty does
    not (Part 6: side-specific, never symmetric)."""
    breakdown = _model().cost_breakdown(is_buy=False, notional=Decimal("10100"))
    assert breakdown.brokerage == Decimal("3.03")  # min(10100*0.0003, 20)
    assert breakdown.exchange_transaction_charges == Decimal("0.31")
    assert breakdown.sebi_charges == Decimal("0.01")
    assert breakdown.gst == Decimal("0.60")
    assert breakdown.stt == Decimal("2.53")  # 10100*0.00025=2.525 -> ROUND_HALF_UP -> 2.53
    assert breakdown.stamp_duty == Decimal("0.00")  # sell leg - never charged
    assert breakdown.total == Decimal("6.48")


def test_reference_fixture_a_combined_round_trip_matches_hand_calculation() -> None:
    """Trade A whole round trip: buy 100 @ 100.00, sell 100 @ 101.00 -
    gross P&L 100.00, total costs 10.70 (4.22 entry + 6.48 exit), net
    P&L 89.30 - hand-verified end to end."""
    model = _model()
    entry = model.cost_breakdown(is_buy=True, notional=Decimal("10000"))
    exit_ = model.cost_breakdown(is_buy=False, notional=Decimal("10100"))
    combined = entry.combine(exit_)
    assert combined.total == Decimal("10.70")
    gross_pnl = Decimal("100.00")
    net_pnl = gross_pnl - combined.total
    assert net_pnl == Decimal("89.30")


def test_reference_fixture_b_large_turnover_brokerage_hits_the_cap() -> None:
    """Trade B: large turnover - brokerage must be CAPPED at ₹20, not
    the uncapped percentage (which would be far higher)."""
    breakdown = _model().cost_breakdown(is_buy=True, notional=Decimal("500000"))
    uncapped = Decimal("500000") * Decimal("0.0003")  # = 150.00
    assert uncapped > Decimal("20")
    assert breakdown.brokerage == Decimal("20.00")


def test_reference_fixture_c_profitable_long_trade_net_pnl() -> None:
    model = _model()
    entry = model.cost_breakdown(is_buy=True, notional=Decimal("50000"))  # buy 500 @ 100
    exit_ = model.cost_breakdown(is_buy=False, notional=Decimal("51000"))  # sell 500 @ 102
    total_costs = entry.combine(exit_).total
    gross_pnl = Decimal("1000.00")
    net_pnl = gross_pnl - total_costs
    assert net_pnl > 0
    assert net_pnl < gross_pnl  # costs must reduce a winning trade's P&L


def test_reference_fixture_d_losing_long_trade_costs_deepen_the_loss() -> None:
    model = _model()
    entry = model.cost_breakdown(is_buy=True, notional=Decimal("50000"))  # buy 500 @ 100
    exit_ = model.cost_breakdown(is_buy=False, notional=Decimal("49000"))  # sell 500 @ 98
    total_costs = entry.combine(exit_).total
    gross_pnl = Decimal("-1000.00")
    net_pnl = gross_pnl - total_costs
    assert net_pnl < gross_pnl  # costs must make a losing trade worse, never better


def test_reference_fixture_e_rounding_boundary_case() -> None:
    """Trade E: a notional chosen so STT lands exactly on a .5-paisa
    rounding boundary - proves ROUND_HALF_UP is applied, not banker's
    rounding or truncation."""
    # notional * 0.00025 = X.XX5 exactly for notional = 10 * 4*N + 2 pattern;
    # 10100 already demonstrated 2.525 -> 2.53 above. Use a second,
    # independent boundary: notional=4020 -> stt = 4020*0.00025=1.005
    breakdown = _model().cost_breakdown(is_buy=False, notional=Decimal("4020"))
    assert breakdown.stt == Decimal("1.01")  # 1.005 rounds up, not down


# --- Side-specific coverage (Part 6, all four combinations) -----------------


def test_long_entry_is_buy_side_no_stt_has_stamp_duty() -> None:
    breakdown = _model().cost_breakdown(is_buy=True, notional=Decimal("20000"))
    assert breakdown.stt == Decimal("0.00")
    assert breakdown.stamp_duty > 0


def test_long_exit_is_sell_side_has_stt_no_stamp_duty() -> None:
    breakdown = _model().cost_breakdown(is_buy=False, notional=Decimal("20000"))
    assert breakdown.stt > 0
    assert breakdown.stamp_duty == Decimal("0.00")


def test_short_entry_is_sell_side_has_stt_no_stamp_duty() -> None:
    """A short entry is a SELL fill - same is_buy=False semantics as a
    long exit (Part 6: the model reasons in buy/sell terms, not
    entry/exit terms, precisely so this is automatically correct)."""
    breakdown = _model().cost_breakdown(is_buy=False, notional=Decimal("20000"))
    assert breakdown.stt > 0
    assert breakdown.stamp_duty == Decimal("0.00")


def test_short_exit_is_buy_side_no_stt_has_stamp_duty() -> None:
    breakdown = _model().cost_breakdown(is_buy=True, notional=Decimal("20000"))
    assert breakdown.stt == Decimal("0.00")
    assert breakdown.stamp_duty > 0


# --- Invariants (Part 14) ----------------------------------------------------


def test_every_component_is_non_negative() -> None:
    for is_buy in (True, False):
        breakdown = _model().cost_breakdown(is_buy=is_buy, notional=Decimal("13579"))
        for value in (
            breakdown.brokerage,
            breakdown.stt,
            breakdown.exchange_transaction_charges,
            breakdown.sebi_charges,
            breakdown.gst,
            breakdown.stamp_duty,
            breakdown.other_statutory_charges,
        ):
            assert value >= 0


def test_negative_component_construction_is_rejected() -> None:
    with pytest.raises(ValueError):
        CostBreakdown(brokerage=Decimal("-1"))


def test_total_equals_sum_of_components_exactly() -> None:
    breakdown = _model().cost_breakdown(is_buy=True, notional=Decimal("77777"))
    expected = (
        breakdown.brokerage
        + breakdown.stt
        + breakdown.exchange_transaction_charges
        + breakdown.sebi_charges
        + breakdown.gst
        + breakdown.stamp_duty
        + breakdown.other_statutory_charges
    )
    assert breakdown.total == expected


def test_combine_sums_each_component_exactly_once_no_double_counting() -> None:
    a = CostBreakdown(brokerage=Decimal("1"), stt=Decimal("2"))
    b = CostBreakdown(brokerage=Decimal("3"), gst=Decimal("4"))
    combined = a.combine(b)
    assert combined.brokerage == Decimal("4")
    assert combined.stt == Decimal("2")
    assert combined.gst == Decimal("4")
    assert combined.total == Decimal("10")


def test_gst_is_computed_once_never_double_counted_across_legs() -> None:
    """Combining an entry+exit breakdown must not apply GST a second
    time to the already-GST-inclusive combined total - each leg's GST is
    computed independently, once, on that leg's own sub-total only."""
    model = _model()
    entry = model.cost_breakdown(is_buy=True, notional=Decimal("10000"))
    exit_ = model.cost_breakdown(is_buy=False, notional=Decimal("10000"))
    combined = entry.combine(exit_)
    # GST is a simple sum of two independently-computed leg-level GST
    # amounts - never re-derived from the combined brokerage+exchange+SEBI.
    assert combined.gst == entry.gst + exit_.gst


def test_zero_cost_configuration_is_legitimately_supported() -> None:
    """The FlatPercentageCostModel with zero rates remains a valid,
    zero-cost configuration - proves the abstraction does not force a
    non-zero cost floor."""
    model = FlatPercentageCostModel(brokerage_percent=Decimal("0"), slippage_percent=Decimal("0"))
    breakdown = model.cost_breakdown(is_buy=True, notional=Decimal("100000"))
    assert breakdown.total == Decimal("0")


# --- Brokerage policy (configurable, not Dhan-specific - Part 11) -----------


def test_brokerage_policy_uncapped_when_cap_is_none() -> None:
    policy = BrokeragePolicy(percent_rate=Decimal("0.03"), flat_cap_per_order=None)
    assert policy.charge_for(Decimal("1000000")) == Decimal("1000000") * Decimal("0.0003")


def test_brokerage_policy_is_independently_configurable_per_model_instance() -> None:
    cheap = IndianCashEquityIntradayCostModel(
        stt_rate=Decimal("0.025"),
        exchange_rate=Decimal("0.00307"),
        sebi_rate=Decimal("0.0001"),
        gst_rate=Decimal("18"),
        stamp_duty_rate=Decimal("0.003"),
        brokerage_policy=BrokeragePolicy(
            percent_rate=Decimal("0"), flat_cap_per_order=Decimal("0")
        ),
    )
    breakdown = cheap.cost_breakdown(is_buy=True, notional=Decimal("100000"))
    assert breakdown.brokerage == Decimal("0.00")
    # statutory charges still apply even with zero brokerage
    assert breakdown.exchange_transaction_charges > 0
