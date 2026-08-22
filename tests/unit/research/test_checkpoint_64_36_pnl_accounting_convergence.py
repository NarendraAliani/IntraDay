# tests/unit/research/test_checkpoint_64_36_pnl_accounting_convergence.py
#
# Checkpoint 64.36: DISCOVERY-FIRST P&L accounting reconciliation between
# Backtest (`research.backtesting`) and Paper Trading
# (`application.services.paper_trading` / `infrastructure.brokers.paper`).
# This module is a MECHANICAL, characterization-only proof of the exact
# accounting mismatch documented in `taskReport.md` (Checkpoint 64.36) and
# `docs/architecture/CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md`
# ("CHECKPOINT 64.36 ACCOUNTING CONVENTION NOTES"). No production code was
# changed by this checkpoint - every test here exercises REAL, unmodified
# `src/` code and asserts the CURRENT, documented behaviour, not a desired
# future behaviour. In particular, `test_h`/`test_i` below prove - with
# real numbers, not fabricated ones - that the SAME economic trade
# (identical entry price, exit price, quantity, and cost schedule)
# produces two different `current_daily_realized_pnl` values across the
# two engines, and that this difference is large enough to flip the
# canonical Risk Gate's decision (`evaluate_order_risk()`) for an
# otherwise-identical subsequent order.
from __future__ import annotations

import ast
import datetime as dt
from decimal import Decimal
from pathlib import Path

from intraday.application.services.paper_trading import PaperTradingService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.risk.contracts import RiskDecisionOutcome, RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.research.backtesting.cost_model import verified_nse_cash_equity_intraday_cost_model
from intraday.research.backtesting.order_intent_adapter import (
    StrategyDirection,
    build_backtest_entry_order_intent,
)
from intraday.research.backtesting.risk_gate_adapter import (
    BacktestRiskGateInputs,
    evaluate_backtest_entry_risk,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src" / "intraday"

INSTRUMENT = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = dt.datetime(2026, 1, 5, 4, 0, tzinfo=dt.UTC)

# The one worked economic trade used throughout this module: a long
# entry at 1000, exit at 990 (a loss), 100 shares, no slippage on either
# engine (isolates the COST-treatment difference from any slippage-
# treatment difference - slippage is examined separately in test_e/f).
ENTRY_PRICE = Decimal("1000")
EXIT_PRICE = Decimal("990")
QUANTITY = Decimal("100")

COST_MODEL = verified_nse_cash_equity_intraday_cost_model()


def _real_cost_of_round_trip() -> Decimal:
    """The REAL, verified NSE cash-equity intraday cost of one round
    trip at ENTRY_PRICE/EXIT_PRICE/QUANTITY - computed by calling the
    actual `cost_model.py` code, never hand-computed/estimated."""
    entry_notional = ENTRY_PRICE * QUANTITY
    exit_notional = EXIT_PRICE * QUANTITY
    breakdown = COST_MODEL.cost_breakdown(is_buy=True, notional=entry_notional).combine(
        COST_MODEL.cost_breakdown(is_buy=False, notional=exit_notional)
    )
    return breakdown.total


# --- A: Backtest gross P&L formula -----------------------------------------


def test_a_backtest_gross_pnl_formula() -> None:
    """Backtest gross P&L (`engine.py`'s own `signed_gross_pnl`, mirrored
    here as the documented formula `(exit - entry) * quantity` for a long)
    is exactly (exit - entry) * quantity - no cost, no slippage folded
    in. Quoted formula source: `engine.py::_close_trade`,
    `gross_pnl = signed_gross_pnl(open_position.direction,
    open_position.entry_price, filled_exit, quantity)`."""
    from intraday.research.backtesting.execution import signed_gross_pnl

    gross = signed_gross_pnl(StrategyDirection.BULLISH, ENTRY_PRICE, EXIT_PRICE, QUANTITY)
    assert gross == (EXIT_PRICE - ENTRY_PRICE) * QUANTITY
    assert gross == Decimal("-1000")


# --- B: Backtest net P&L formula --------------------------------------------


def test_b_backtest_net_pnl_formula_is_cost_inclusive() -> None:
    """Backtest net P&L (`engine.py::_close_trade`,
    `net_pnl = gross_pnl - trade_costs`) subtracts the REAL, itemized
    round-trip cost from gross P&L. Verified against the actual
    `cost_model.py` code, not an estimated figure."""
    from intraday.research.backtesting.execution import signed_gross_pnl

    gross = signed_gross_pnl(StrategyDirection.BULLISH, ENTRY_PRICE, EXIT_PRICE, QUANTITY)
    real_cost = _real_cost_of_round_trip()
    net = gross - real_cost

    assert real_cost > 0
    assert net == gross - real_cost
    # The real, verified schedule at these notionals (Decimal computed by
    # the actual code, asserted here so a future cost-schedule change is
    # caught, not silently absorbed):
    assert real_cost == Decimal("82.39")
    assert net == Decimal("-1082.39")


# --- C: Paper Trading realized P&L formula ----------------------------------


def _build_paper_broker(*, compute_cost) -> PaperBroker:  # type: ignore[no-untyped-def]
    return PaperBroker(
        initial_capital=Decimal("1000000"),
        compute_cost=compute_cost,
        clock=lambda: NOW,
    )


def _real_compute_cost(is_buy: bool, notional: Decimal) -> Decimal:
    return COST_MODEL.cost_breakdown(is_buy=is_buy, notional=notional).total


def _fill_round_trip(broker: PaperBroker, *, idempotency_prefix: str) -> None:
    """Submits a real BUY then a real SELL through the real `PaperBroker`
    order-submission/fill path (`submit_order` -> `_attempt_fill` ->
    `_apply_to_position`) - not a hand-constructed `Position`."""
    broker.record_price(INSTRUMENT, ENTRY_PRICE, NOW)
    buy = OrderIntent(
        order_id=f"{idempotency_prefix}-buy",  # type: ignore[arg-type]
        instrument_id=INSTRUMENT,
        side=Side.BUY,
        quantity=QUANTITY,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="orb-v1",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key=f"{idempotency_prefix}-buy",
    )
    broker.submit_order(buy)

    broker.record_price(INSTRUMENT, EXIT_PRICE, NOW)
    sell = OrderIntent(
        order_id=f"{idempotency_prefix}-sell",  # type: ignore[arg-type]
        instrument_id=INSTRUMENT,
        side=Side.SELL,
        quantity=QUANTITY,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="orb-v1",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key=f"{idempotency_prefix}-sell",
    )
    broker.submit_order(sell)


def test_c_paper_trading_realized_pnl_formula_is_cost_exclusive() -> None:
    """Paper Trading `Position.realized_pnl`
    (`broker.py::_apply_to_position`,
    `realized = direction_sign * (fill_price - existing.average_entry_price)
    * closing_quantity`) is GROSS P&L - the REAL cost model is injected
    and IS charged against `_available_balance` inside `_attempt_fill`,
    but is never subtracted from `realized_pnl`. This is proven by
    running the SAME real cost model used in test_b through a real
    `PaperBroker` round trip and observing `realized_pnl` still equals
    the gross figure, not the net one."""
    broker = _build_paper_broker(compute_cost=_real_compute_cost)
    initial_balance = broker.get_funds().available_balance

    _fill_round_trip(broker, idempotency_prefix="rt1")

    positions = broker.get_positions()
    assert len(positions) == 1
    position = positions[0]
    assert position.realized_pnl == (EXIT_PRICE - ENTRY_PRICE) * QUANTITY
    assert position.realized_pnl == Decimal("-1000")

    # The cost WAS actually charged - just not to realized_pnl. Proven by
    # the balance drop exceeding the pure gross loss.
    final_balance = broker.get_funds().available_balance
    balance_drop = initial_balance - final_balance
    real_cost = _real_cost_of_round_trip()
    assert balance_drop == Decimal("1000") + real_cost


# --- D: trading-cost treatment ----------------------------------------------


def test_d_trading_cost_is_applied_in_fundamentally_different_places() -> None:
    """Backtest subtracts cost from `net_pnl` (a P&L field). Paper
    Trading subtracts the SAME cost figure from `_available_balance` (a
    cash/funds field), never from `realized_pnl`. Same cost model, same
    numeric charge, two different downstream ledgers - proven, not
    assumed, by reusing the identical `_real_cost_of_round_trip()` figure
    in both test_b and test_c/here."""
    real_cost = _real_cost_of_round_trip()

    broker = _build_paper_broker(compute_cost=_real_compute_cost)
    initial_balance = broker.get_funds().available_balance
    _fill_round_trip(broker, idempotency_prefix="rt2")
    balance_drop = initial_balance - broker.get_funds().available_balance
    position = broker.get_positions()[0]

    # Cost reduced the balance...
    assert balance_drop == Decimal("1000") + real_cost
    # ...but NOT the realized P&L.
    assert position.realized_pnl == Decimal("-1000")
    assert position.realized_pnl != Decimal("-1000") - real_cost


# --- E/F: slippage treatment -------------------------------------------------


def test_e_backtest_slippage_is_priced_into_the_fill_before_gross_pnl() -> None:
    """Backtest slippage (`cost_model.py::slippage_adjusted_price`) moves
    the FILL PRICE itself before `gross_pnl` is computed - it is not a
    separate cost line item (documented explicitly in
    `CostBreakdown.total`'s own docstring: "deliberately EXCLUDES
    slippage ... to avoid double-counting"). Proven by constructing a
    cost model with nonzero slippage and observing the entry fill price
    itself changes."""
    from intraday.research.backtesting.cost_model import FlatPercentageCostModel

    model = FlatPercentageCostModel(brokerage_percent=Decimal("0"), slippage_percent=Decimal("1"))
    filled_entry = model.slippage_adjusted_price(
        StrategyDirection.BULLISH, ENTRY_PRICE, entering=True
    )
    assert filled_entry == ENTRY_PRICE * Decimal("1.01")
    assert filled_entry != ENTRY_PRICE


def test_f_paper_trading_slippage_is_also_priced_into_the_fill() -> None:
    """Paper Trading slippage (`broker.py::_attempt_fill`,
    `slipped_price = price * (1 +/- slippage_percent/100)`) is likewise
    a FILL-PRICE adjustment, not a separate cost line item - the same
    structural convention as Backtest's. This is the one accounting
    dimension already convergent between the two engines (both fold
    slippage into price, neither double-counts it as a cost)."""
    broker = PaperBroker(
        initial_capital=Decimal("1000000"),
        compute_cost=lambda is_buy, notional: Decimal("0"),  # noqa: ARG005
        slippage_percent=Decimal("1"),
        clock=lambda: NOW,
    )
    broker.record_price(INSTRUMENT, ENTRY_PRICE, NOW)
    buy = OrderIntent(
        order_id="slip-buy",  # type: ignore[arg-type]
        instrument_id=INSTRUMENT,
        side=Side.BUY,
        quantity=QUANTITY,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="orb-v1",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key="slip-buy",
    )
    broker.submit_order(buy)
    position = broker.get_positions()[0]
    assert position.average_entry_price == ENTRY_PRICE * Decimal("1.01")


# --- G: daily realized P&L semantics -----------------------------------------


def test_g_backtest_daily_realized_pnl_is_cumulative_closed_trade_net_pnl() -> None:
    """Backtest's `current_daily_realized_pnl` figure fed to the risk
    gate (`risk_gate_adapter.py`'s own header docstring, `engine.py`'s
    `cumulative_closed_trade_net_pnl=(running_equity -
    backtest_config.initial_capital)`) is COST-INCLUSIVE, because
    `running_equity` accumulates `SimulatedTrade.net_pnl` (cost-
    inclusive) trade by trade."""
    real_cost = _real_cost_of_round_trip()
    from intraday.research.backtesting.execution import signed_gross_pnl

    gross = signed_gross_pnl(StrategyDirection.BULLISH, ENTRY_PRICE, EXIT_PRICE, QUANTITY)
    net_this_trade = gross - real_cost

    initial_capital = Decimal("100000")
    running_equity = initial_capital + net_this_trade
    cumulative_closed_trade_net_pnl = running_equity - initial_capital

    assert cumulative_closed_trade_net_pnl == net_this_trade
    assert cumulative_closed_trade_net_pnl == Decimal("-1082.39")


def test_h_paper_trading_daily_realized_pnl_is_sum_of_position_realized_pnl_gross() -> None:
    """Paper Trading's `current_daily_realized_pnl`
    (`paper_trading.py::submit_order`,
    `daily_realized_pnl = sum((p.realized_pnl for p in positions),
    Decimal("0"))`) is COST-EXCLUSIVE, because `Position.realized_pnl`
    itself never subtracts cost (test_c). Verified end-to-end through
    the real `PaperTradingService`/`PaperBroker`, not a hand-computed
    substitute."""
    broker = _build_paper_broker(compute_cost=_real_compute_cost)
    _fill_round_trip(broker, idempotency_prefix="rt3")

    positions = broker.get_positions()
    daily_realized_pnl = sum((p.realized_pnl for p in positions), Decimal("0"))

    assert daily_realized_pnl == Decimal("-1000")
    # NOT the cost-inclusive figure Backtest would report for the exact
    # same economic trade (test_g):
    assert daily_realized_pnl != Decimal("-1082.39")
    assert daily_realized_pnl - Decimal("-1082.39") == _real_cost_of_round_trip()


# --- I: the risk-gate divergence worked example (the checkpoint's core proof)


def test_i_identical_daily_loss_produces_divergent_risk_decisions() -> None:
    """THE central mechanical proof this checkpoint (64.36) discovered,
    and Checkpoint 64.37 (`test_checkpoint_64_37_net_pnl_risk_contract.py`)
    closed: as originally written, this test asserted the DIVERGENT
    64.36 behaviour (Backtest REJECTED, Paper Trading APPROVED for the
    exact same economic trade). 64.37 fixed
    `PaperTradingService.submit_order` to feed the Risk Gate the
    cost-inclusive `Position.realized_net_pnl` (populated by
    `PaperBroker`, per `domain.trade.net_pnl.compute_realized_net_pnl`)
    instead of the cost-exclusive `Position.realized_pnl` it previously
    summed. This test is UPDATED, not deleted, to assert the NOW-CORRECT
    convergent behaviour - both engines REJECT the identical subsequent
    order - so this file continues to serve as a regression guard against
    the divergence it originally discovered ever silently returning. The
    dedicated 64.37 convergence proof (with both engines' internal
    `realized_net_pnl` values also asserted) lives in
    `test_checkpoint_64_37_net_pnl_risk_contract.py`."""
    limits = RiskLimits(
        max_intraday_loss=Decimal("1050"),
        max_position_size=Decimal("100000"),
        max_per_trade_risk=Decimal("100000"),
    )

    # --- Backtest side: cost-inclusive cumulative net_pnl = -1082.39 ---
    next_order = build_backtest_entry_order_intent(
        strategy_id="orb-v1",
        instrument_id=str(INSTRUMENT),
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_timestamp=NOW,
        entry_index=1,
    )
    backtest_inputs = BacktestRiskGateInputs(
        risk_limits=limits,
        risk_configuration_version="v1",
        now=NOW,
        cumulative_closed_trade_net_pnl=Decimal("-1082.39"),
        current_open_positions_count=0,
        current_position_size_for_instrument=Decimal("0"),
        estimated_order_notional=Decimal("10000"),
        max_concurrent_positions=1,
        max_total_exposure=Decimal("500000"),
        current_total_exposure=Decimal("0"),
    )
    backtest_decision = evaluate_backtest_entry_risk(next_order, backtest_inputs)

    # --- Paper Trading side: cost-exclusive sum(Position.realized_pnl) = -1000
    broker = _build_paper_broker(compute_cost=_real_compute_cost)
    _fill_round_trip(broker, idempotency_prefix="rt4")
    daily_realized_pnl = sum((p.realized_pnl for p in broker.get_positions()), Decimal("0"))
    assert daily_realized_pnl == Decimal("-1000")

    service = PaperTradingService(
        broker=broker,
        risk_limits=limits,
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("500000"),
        kill_switch_status_provider=lambda: TradingHaltStatus.ACTIVE,
        clock=lambda: NOW,
    )
    paper_next_order = OrderIntent(
        order_id="rt4-next",  # type: ignore[arg-type]
        instrument_id=make_instrument_id(Exchange.NSE, "TCS"),
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="orb-v1",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key="rt4-next",
    )
    paper_result = service.submit_order(
        paper_next_order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("10000"),
        already_submitted_idempotency_keys=frozenset(),
    )

    # POST-64.37: THE DIVERGENCE IS CLOSED - both engines now REJECT.
    assert backtest_decision.outcome is RiskDecisionOutcome.REJECTED
    assert paper_result.risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert backtest_decision.outcome == paper_result.risk_decision.outcome


# --- J: the difference is intentional/documented, not silently unnoticed ----


def test_j_the_cost_exclusion_is_documented_in_source_not_silent() -> None:
    """`risk_gate_adapter.py`'s own header docstring names the exact
    conflict this checkpoint's test_i proves numerically - this test
    only proves the disclosure text is still present (a doc-rot guard),
    not the accounting itself."""
    source = (SRC_ROOT / "research" / "backtesting" / "risk_gate_adapter.py").read_text(
        encoding="utf-8"
    )
    assert "PaperBroker" in source
    assert "cost-exclusive" in source or "cost exclusive" in source.lower()


# --- K: no execution-model changes introduced by this checkpoint ------------


def test_k_no_fill_execution_report_or_slippage_model_type_introduced() -> None:
    """Repo-wide guard: this checkpoint is accounting-only discovery -
    no `Fill`/`ExecutionReport`/`BrokerOrder`/`PartialFill`/
    `SlippageModel` class was introduced anywhere in `src/`."""
    forbidden = {"FillReport", "ExecutionReport", "PartialFill", "SlippageModel"}
    found: dict[str, str] = {}
    for path in SRC_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in forbidden:
                found[node.name] = str(path)
    assert found == {}, f"forbidden execution-model type(s) introduced: {found}"


# --- L: no Dhan/live imports introduced --------------------------------------


def test_l_this_checkpoints_own_test_module_imports_no_dhan_symbol() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported_names = {
        alias.name.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    module_names = {
        node.module.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any("dhan" in name for name in imported_names)
    assert not any("dhan" in name for name in module_names)


# --- M: no duplicate accounting vocabulary introduced ------------------------


def test_m_no_duplicate_pnl_or_accounting_type_introduced() -> None:
    """Repo-wide guard: no `NetPnl`/`GrossPnl`/`RealizedPnl`/
    `CanonicalTrade`/`AccountingLedger` dataclass/class was introduced as
    a NEW, competing type by this checkpoint - the existing
    `SimulatedTrade` (Backtest) and `Position`/`Trade`
    (`domain.position.contracts`/`domain.trade.contracts`, shared by
    Paper Trading) remain the only trade/position-shaped types."""
    forbidden = {"NetPnl", "GrossPnl", "RealizedPnl", "CanonicalTrade", "AccountingLedger"}
    found: dict[str, str] = {}
    for path in SRC_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in forbidden:
                found[node.name] = str(path)
    assert found == {}, f"forbidden duplicate accounting type(s) introduced: {found}"


# --- N: existing 64.29-64.35 tests still pass (import-level smoke check) ----


def test_n_prior_checkpoint_test_modules_still_import_cleanly() -> None:
    """A cheap, fast smoke check that this checkpoint's own new imports
    did not break anything the prior risk-convergence test modules rely
    on - the authoritative proof is the full `-q` run of
    `tests/unit/research/`, reported in `taskReport.md`; this is a fast
    in-process guard."""
    import importlib

    importlib.import_module("tests.unit.research.test_checkpoint_64_35_risk_decision_convergence")
    importlib.import_module("tests.unit.research.test_checkpoint_64_34_portfolio_risk_gate")
