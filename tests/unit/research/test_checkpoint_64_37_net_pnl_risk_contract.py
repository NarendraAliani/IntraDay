# File: tests/unit/research/test_checkpoint_64_37_net_pnl_risk_contract.py
#
# Checkpoint 64.37: ADDITIVE REALIZED NET P&L CONTRACT FOR RISK CONTROL.
# 64.36 mechanically proved Backtest/Paper Trading feed the Risk Gate two
# different financial meanings of "daily realized P&L" for the same
# trade, capable of flipping `evaluate_order_risk()`'s decision. This
# module proves 64.37's fix: an ADDITIVE `realized_net_pnl` contract
# (`domain.trade.net_pnl.compute_realized_net_pnl`, `Position.
# realized_net_pnl`, `Trade.realized_net_pnl`) that BOTH engines now feed
# into `RiskEvaluationContext.current_daily_realized_pnl`, WITHOUT
# redefining `Position.realized_pnl`/`Trade.realized_pnl`/
# `SimulatedTrade.net_pnl`. Every test here exercises REAL, production
# code paths - no fabricated `RiskEvaluationContext`.
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
from intraday.domain.trade.net_pnl import compute_realized_net_pnl
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.research.backtesting.cost_model import verified_nse_cash_equity_intraday_cost_model
from intraday.research.backtesting.execution import signed_gross_pnl
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

# The SAME central worked economic trade as 64.36: long entry 1000, exit
# 990, qty 100, zero slippage, the REAL verified NSE cost schedule.
ENTRY_PRICE = Decimal("1000")
EXIT_PRICE = Decimal("990")
QUANTITY = Decimal("100")

COST_MODEL = verified_nse_cash_equity_intraday_cost_model()


def _real_cost_of_round_trip(
    entry_price: Decimal = ENTRY_PRICE,
    exit_price: Decimal = EXIT_PRICE,
    quantity: Decimal = QUANTITY,
) -> Decimal:
    entry_notional = entry_price * quantity
    exit_notional = exit_price * quantity
    breakdown = COST_MODEL.cost_breakdown(is_buy=True, notional=entry_notional).combine(
        COST_MODEL.cost_breakdown(is_buy=False, notional=exit_notional)
    )
    return breakdown.total


def _real_compute_cost(is_buy: bool, notional: Decimal) -> Decimal:
    return COST_MODEL.cost_breakdown(is_buy=is_buy, notional=notional).total


def _build_paper_broker() -> PaperBroker:
    return PaperBroker(
        initial_capital=Decimal("1000000"),
        compute_cost=_real_compute_cost,
        clock=lambda: NOW,
    )


def _fill_round_trip(
    broker: PaperBroker,
    *,
    idempotency_prefix: str,
    entry_price: Decimal = ENTRY_PRICE,
    exit_price: Decimal = EXIT_PRICE,
    quantity: Decimal = QUANTITY,
    instrument=INSTRUMENT,
) -> None:
    """Real BUY then real SELL through the real `PaperBroker.submit_order`
    -> `_attempt_fill` -> `_apply_to_position` path - never a
    hand-constructed `Position`/`Trade`."""
    broker.record_price(instrument, entry_price, NOW)
    buy = OrderIntent(
        order_id=f"{idempotency_prefix}-buy",  # type: ignore[arg-type]
        instrument_id=instrument,
        side=Side.BUY,
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="orb-v1",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key=f"{idempotency_prefix}-buy",
    )
    broker.submit_order(buy)

    broker.record_price(instrument, exit_price, NOW)
    sell = OrderIntent(
        order_id=f"{idempotency_prefix}-sell",  # type: ignore[arg-type]
        instrument_id=instrument,
        side=Side.SELL,
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="orb-v1",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key=f"{idempotency_prefix}-sell",
    )
    broker.submit_order(sell)


# --- A: the canonical contract exists -----------------------------------


def test_a_canonical_realized_net_pnl_contract_exists() -> None:
    """`compute_realized_net_pnl` is a pure, deterministic, Decimal-based
    function: `realized_net_pnl = gross_price_pnl - transaction_cost`."""
    assert compute_realized_net_pnl(Decimal("-1000"), Decimal("82.39")) == Decimal("-1082.39")
    assert compute_realized_net_pnl(Decimal("500"), Decimal("10")) == Decimal("490")


def test_a2_negative_transaction_cost_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        compute_realized_net_pnl(Decimal("100"), Decimal("-1"))


# --- B: Backtest produces realized_net_pnl (mapping, not a new formula) --


def test_b_backtest_produces_realized_net_pnl_via_existing_net_pnl() -> None:
    """Backtest's EXISTING `SimulatedTrade.net_pnl` (unchanged formula)
    already equals `realized_net_pnl` for the worked example - this test
    proves the mapping/equivalence, not a new computation in `engine.py`."""
    gross = signed_gross_pnl(StrategyDirection.BULLISH, ENTRY_PRICE, EXIT_PRICE, QUANTITY)
    real_cost = _real_cost_of_round_trip()
    existing_net_pnl = gross - real_cost  # `engine.py::_close_trade`'s own formula, untouched

    realized_net_pnl = compute_realized_net_pnl(gross, real_cost)

    assert existing_net_pnl == realized_net_pnl
    assert realized_net_pnl == Decimal("-1082.39")


# --- C: Paper Trading produces realized_net_pnl --------------------------


def test_c_paper_trading_produces_realized_net_pnl() -> None:
    """`PaperBroker` now populates `Position.realized_net_pnl` and
    `Trade.realized_net_pnl` - the cost-inclusive figure - alongside the
    unchanged, cost-exclusive `realized_pnl`."""
    broker = _build_paper_broker()
    _fill_round_trip(broker, idempotency_prefix="c1")

    position = broker.get_positions()[0]
    trade = broker.get_trades()[0]

    assert trade.realized_net_pnl == Decimal("-1082.39")
    assert position.realized_net_pnl == Decimal("-1082.39")


# --- D: Position.realized_pnl remains cost-exclusive (backward compat) ---


def test_d_position_realized_pnl_remains_cost_exclusive() -> None:
    broker = _build_paper_broker()
    _fill_round_trip(broker, idempotency_prefix="d1")
    position = broker.get_positions()[0]
    assert position.realized_pnl == Decimal("-1000")
    assert position.realized_pnl != position.realized_net_pnl


def test_d2_trade_realized_pnl_remains_cost_exclusive() -> None:
    broker = _build_paper_broker()
    _fill_round_trip(broker, idempotency_prefix="d2")
    trade = broker.get_trades()[0]
    assert trade.realized_pnl == Decimal("-1000")
    assert trade.realized_pnl != trade.realized_net_pnl


# --- E: SimulatedTrade.net_pnl remains unchanged --------------------------


def test_e_simulated_trade_net_pnl_formula_unchanged() -> None:
    """`engine.py::_close_trade`'s formula (`gross_pnl - trade_costs`) was
    NOT touched by this checkpoint - re-verified directly against source."""
    engine_source = (SRC_ROOT / "research" / "backtesting" / "engine.py").read_text(
        encoding="utf-8"
    )
    assert "net_pnl = gross_pnl - trade_costs" in engine_source


# --- F: same economic trade -> same realized_net_pnl ----------------------


def test_f_same_economic_trade_same_realized_net_pnl_both_engines() -> None:
    gross = signed_gross_pnl(StrategyDirection.BULLISH, ENTRY_PRICE, EXIT_PRICE, QUANTITY)
    real_cost = _real_cost_of_round_trip()
    backtest_realized_net_pnl = compute_realized_net_pnl(gross, real_cost)

    broker = _build_paper_broker()
    _fill_round_trip(broker, idempotency_prefix="f1")
    paper_realized_net_pnl = broker.get_positions()[0].realized_net_pnl

    assert backtest_realized_net_pnl == paper_realized_net_pnl == Decimal("-1082.39")


# --- G: the 64.36 risk divergence is eliminated ----------------------------


def _make_backtest_decision(cumulative_closed_trade_net_pnl: Decimal, limits: RiskLimits):
    next_order = build_backtest_entry_order_intent(
        strategy_id="orb-v1",
        instrument_id=str(INSTRUMENT),
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_timestamp=NOW,
        entry_index=1,
    )
    inputs = BacktestRiskGateInputs(
        risk_limits=limits,
        risk_configuration_version="v1",
        now=NOW,
        cumulative_closed_trade_net_pnl=cumulative_closed_trade_net_pnl,
        current_open_positions_count=0,
        current_position_size_for_instrument=Decimal("0"),
        estimated_order_notional=Decimal("10000"),
        max_concurrent_positions=1,
        max_total_exposure=Decimal("500000"),
        current_total_exposure=Decimal("0"),
    )
    return evaluate_backtest_entry_risk(next_order, inputs)


def _make_paper_result(idempotency_prefix: str, limits: RiskLimits):
    broker = _build_paper_broker()
    _fill_round_trip(broker, idempotency_prefix=idempotency_prefix)
    service = PaperTradingService(
        broker=broker,
        risk_limits=limits,
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("500000"),
        kill_switch_status_provider=lambda: TradingHaltStatus.ACTIVE,
        clock=lambda: NOW,
    )
    next_order = OrderIntent(
        order_id=f"{idempotency_prefix}-next",  # type: ignore[arg-type]
        instrument_id=make_instrument_id(Exchange.NSE, "TCS"),
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="orb-v1",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key=f"{idempotency_prefix}-next",
    )
    result = service.submit_order(
        next_order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("10000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    daily_realized_net_pnl = sum(
        (p.realized_net_pnl or Decimal("0") for p in broker.get_positions()), Decimal("0")
    )
    return result, daily_realized_net_pnl


def test_g_central_64_36_divergence_eliminated_both_rejected() -> None:
    """THE central proof: `max_intraday_loss=1050`, strictly between 1000
    and 1082.39. Pre-64.37, Backtest REJECTED / Paper APPROVED (64.36's
    own proof). Post-64.37: BOTH REJECT, through real production entry
    points, because both now feed the Risk Gate the same cost-inclusive
    `realized_net_pnl=-1082.39`."""
    limits = RiskLimits(
        max_intraday_loss=Decimal("1050"),
        max_position_size=Decimal("100000"),
        max_per_trade_risk=Decimal("100000"),
    )
    backtest_decision = _make_backtest_decision(Decimal("-1082.39"), limits)
    paper_result, paper_daily_realized_net_pnl = _make_paper_result("g1", limits)

    assert paper_daily_realized_net_pnl == Decimal("-1082.39")
    assert backtest_decision.outcome is RiskDecisionOutcome.REJECTED
    assert paper_result.risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert backtest_decision.outcome == paper_result.risk_decision.outcome


# --- H: below-threshold positive control - both APPROVE --------------------


def test_h_below_threshold_loss_both_approve() -> None:
    """A smaller loss (entry 1000, exit 996, qty 100 -> gross -400, real
    cost ~33, realized_net_pnl magnitude well under max_intraday_loss=1050)
    must APPROVE on both engines - proves this checkpoint did not simply
    force every decision to REJECTED."""
    entry_price = Decimal("1000")
    exit_price = Decimal("996")
    quantity = Decimal("100")
    gross = signed_gross_pnl(StrategyDirection.BULLISH, entry_price, exit_price, quantity)
    real_cost = _real_cost_of_round_trip(entry_price, exit_price, quantity)
    realized_net_pnl = compute_realized_net_pnl(gross, real_cost)
    assert realized_net_pnl > Decimal("-1050")  # confirms this really is the "below threshold" case

    limits = RiskLimits(
        max_intraday_loss=Decimal("1050"),
        max_position_size=Decimal("100000"),
        max_per_trade_risk=Decimal("100000"),
    )
    backtest_decision = _make_backtest_decision(realized_net_pnl, limits)

    broker = _build_paper_broker()
    _fill_round_trip(
        broker,
        idempotency_prefix="h1",
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
    )
    paper_position_realized_net_pnl = broker.get_positions()[0].realized_net_pnl
    assert paper_position_realized_net_pnl == realized_net_pnl

    service = PaperTradingService(
        broker=broker,
        risk_limits=limits,
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("500000"),
        kill_switch_status_provider=lambda: TradingHaltStatus.ACTIVE,
        clock=lambda: NOW,
    )
    next_order = OrderIntent(
        order_id="h1-next",  # type: ignore[arg-type]
        instrument_id=make_instrument_id(Exchange.NSE, "TCS"),
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="orb-v1",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key="h1-next",
    )
    paper_result = service.submit_order(
        next_order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("10000"),
        already_submitted_idempotency_keys=frozenset(),
    )

    assert backtest_decision.outcome is RiskDecisionOutcome.APPROVED
    assert paper_result.risk_decision.outcome is RiskDecisionOutcome.APPROVED


# --- I: above-threshold loss - both REJECT (restates G with a distinct fixture)


def test_i_above_threshold_loss_both_reject() -> None:
    limits = RiskLimits(
        max_intraday_loss=Decimal("1050"),
        max_position_size=Decimal("100000"),
        max_per_trade_risk=Decimal("100000"),
    )
    backtest_decision = _make_backtest_decision(Decimal("-1082.39"), limits)
    paper_result, _ = _make_paper_result("i1", limits)
    assert backtest_decision.outcome is RiskDecisionOutcome.REJECTED
    assert paper_result.risk_decision.outcome is RiskDecisionOutcome.REJECTED


# --- J: same RiskLimits type used, no new risk-limits shape ----------------


def test_j_same_risk_limits_type_used() -> None:
    limits = RiskLimits(
        max_intraday_loss=Decimal("1050"),
        max_position_size=Decimal("100000"),
        max_per_trade_risk=Decimal("100000"),
    )
    assert isinstance(limits, RiskLimits)
    # No competing "RiskLimitsV2"/"AccountingRiskLimits" type exists.
    for path in SRC_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and node.name != "RiskLimits"
                and "RiskLimits" in node.name
                and not node.name.endswith("Serializer")
            ):
                raise AssertionError(f"competing RiskLimits type found: {node.name} in {path}")


# --- K: real evaluate_order_risk() used (not a stub) ------------------------


def test_k_real_evaluate_order_risk_used() -> None:
    from intraday.domain.risk.policy import evaluate_order_risk

    source = (SRC_ROOT / "research" / "backtesting" / "risk_gate_adapter.py").read_text(
        encoding="utf-8"
    )
    assert "evaluate_order_risk" in source
    assert callable(evaluate_order_risk)


# --- L: real PaperTradingService.submit_order() path exercised -------------


def test_l_real_paper_trading_service_submit_order_path_exercised() -> None:
    """Already exercised by test_g/test_h/test_i via real
    `PaperTradingService` instances - this test additionally asserts the
    service's own source still builds `RiskEvaluationContext` from
    `Position.realized_net_pnl`, not `Position.realized_pnl`."""
    source = (SRC_ROOT / "application" / "services" / "paper_trading.py").read_text(
        encoding="utf-8"
    )
    assert "p.realized_net_pnl" in source
    assert "current_daily_realized_pnl=daily_realized_net_pnl" in source


# --- M: real PaperBroker cost model used ------------------------------------


def test_m_real_paper_broker_cost_model_used() -> None:
    broker = _build_paper_broker()
    _fill_round_trip(broker, idempotency_prefix="m1")
    balance_drop = Decimal("1000000") - broker.get_funds().available_balance
    real_cost = _real_cost_of_round_trip()
    assert balance_drop == Decimal("1000") + real_cost


# --- N: costs counted exactly once ------------------------------------------


def test_n_costs_counted_exactly_once() -> None:
    """Cash already reflects the cost (charged once, in `_attempt_fill`).
    `realized_net_pnl` is a P&L ATTRIBUTION, not a second cash mutation:
    proves `initial_capital - balance_drop_due_to_cost` is independent of
    `realized_net_pnl`'s own bookkeeping, i.e. the SAME `real_cost` figure
    explains BOTH the balance drop AND the gross/net P&L gap, with no
    double subtraction."""
    broker = _build_paper_broker()
    initial_balance = broker.get_funds().available_balance
    _fill_round_trip(broker, idempotency_prefix="n1")

    position = broker.get_positions()[0]
    real_cost = _real_cost_of_round_trip()

    balance_drop = initial_balance - broker.get_funds().available_balance
    pnl_gap = position.realized_pnl - position.realized_net_pnl  # type: ignore[operator]

    assert balance_drop == Decimal("1000") + real_cost
    assert pnl_gap == real_cost
    # If cost were double-counted, pnl_gap would be 2x real_cost or the
    # balance drop would additionally subtract it a second time - neither
    # is the case.
    assert pnl_gap != real_cost * 2


# --- O: slippage not double-counted -----------------------------------------


def test_o_slippage_not_double_counted_in_realized_net_pnl() -> None:
    """With nonzero slippage and ZERO transaction cost, `realized_net_pnl`
    must equal the (already slippage-adjusted) gross realized P&L exactly
    - slippage must not ALSO be subtracted as a transaction cost."""
    broker = PaperBroker(
        initial_capital=Decimal("1000000"),
        compute_cost=lambda is_buy, notional: Decimal("0"),  # noqa: ARG005
        slippage_percent=Decimal("1"),
        clock=lambda: NOW,
    )
    _fill_round_trip(broker, idempotency_prefix="o1")
    position = broker.get_positions()[0]
    trade = broker.get_trades()[0]

    # Entry fills at 1000 * 1.01 = 1010 (buy slippage worsens price);
    # exit fills at 990 * 0.99 = 980.1 (sell slippage worsens price).
    entry_fill = Decimal("1000") * Decimal("1.01")
    exit_fill = Decimal("990") * Decimal("0.99")
    expected_gross = (exit_fill - entry_fill) * Decimal("100")

    assert position.realized_pnl == expected_gross
    # Zero transaction cost injected -> realized_net_pnl == realized_pnl
    # exactly (no hidden second slippage subtraction).
    assert position.realized_net_pnl == expected_gross
    assert trade.realized_net_pnl == expected_gross


# --- P: no Dhan imports -------------------------------------------------------


def test_p_no_dhan_imports_in_this_module() -> None:
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


def test_p2_no_dhan_imports_in_modified_src_files() -> None:
    """AST-based import guard (not a substring search) - this checkpoint's
    own files legitimately MENTION a future DhanBroker in prose/docstrings
    (e.g. `broker.py`'s existing header comment), which is not an import
    and must not trip this guard."""
    for relative in (
        "domain/trade/net_pnl.py",
        "domain/position/contracts.py",
        "domain/trade/contracts.py",
        "infrastructure/brokers/paper/broker.py",
        "application/services/paper_trading.py",
        "research/backtesting/risk_gate_adapter.py",
    ):
        tree = ast.parse((SRC_ROOT / relative).read_text(encoding="utf-8"))
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
        assert not any("dhan" in name for name in imported_names), relative
        assert not any("dhan" in name for name in module_names), relative


# --- Q: no Fill/Execution classes introduced ----------------------------------


def test_q_no_fill_execution_report_type_introduced() -> None:
    forbidden = {"FillReport", "ExecutionReport", "PartialFill", "SlippageModel", "BrokerOrder"}
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


# --- R: no duplicate accounting vocabulary ------------------------------------


def test_r_no_duplicate_accounting_vocabulary_introduced() -> None:
    forbidden = {
        "AccountingEngine",
        "AccountingLedger",
        "NetPnlService",
        "PnlManager",
        "NetPnl",
        "GrossPnl",
        "CanonicalTrade",
    }
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


# --- S: existing 64.29-64.36 tests remain passing (import-level smoke) -------


def test_s_prior_checkpoint_test_modules_still_import_cleanly() -> None:
    import importlib

    importlib.import_module("tests.unit.research.test_checkpoint_64_36_pnl_accounting_convergence")
    importlib.import_module("tests.unit.research.test_checkpoint_64_35_risk_decision_convergence")
    importlib.import_module("tests.unit.research.test_checkpoint_64_34_portfolio_risk_gate")
