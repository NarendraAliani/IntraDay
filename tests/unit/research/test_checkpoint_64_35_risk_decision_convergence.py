# tests/unit/research/test_checkpoint_64_35_risk_decision_convergence.py
#
# Checkpoint 64.35: DISCOVERY-FIRST convergence check between Backtest's
# risk gate (`research.backtesting.risk_gate_adapter`) and Paper
# Trading's risk gate (`application.services.paper_trading.
# PaperTradingService`). Discovery (documented in full in this
# checkpoint's `taskReport.md` and in
# `docs/architecture/CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md`'s
# "CHECKPOINT 64.35 IMPLEMENTATION NOTES" section) found the two paths
# were ALREADY fully converged by prior checkpoints (34, 64.24, 64.29):
# both call the exact same `domain.risk.policy.evaluate_order_risk()`
# function object, both build `domain.risk.policy.RiskEvaluationContext`,
# both consume/produce the exact same `domain.order.contracts.OrderIntent`
# and `domain.risk.contracts.OrderRiskDecision` types - no
# `PaperOrderIntent`/`PaperRiskDecision`/`BacktestRiskDecision` duplicate
# vocabulary exists anywhere in the repository. This module is a
# MECHANICAL PROOF of that finding (not merely a restatement of it),
# so a future refactor that accidentally reintroduces divergence fails
# these tests immediately. No production code changes were required or
# made for this checkpoint - see the mandatory-stop analysis in
# `taskReport.md` for why "no change needed" is itself the correct,
# honest outcome here.
from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from intraday.application.services.paper_trading import (
    PaperOrderSubmissionResult,
    PaperTradingService,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.risk import policy as domain_risk_policy
from intraday.domain.risk.contracts import (
    OrderRiskDecision,
    RiskDecisionOutcome,
    RiskLimits,
    TradingHaltStatus,
)
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.research.backtesting import order_intent_adapter, risk_gate_adapter
from intraday.research.backtesting.risk_gate_adapter import (
    BacktestRiskGateInputs,
    evaluate_backtest_entry_risk,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src" / "intraday"

INSTRUMENT = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)

RISK_LIMITS = RiskLimits(
    max_intraday_loss=Decimal("5000"),
    max_position_size=Decimal("100"),
    max_per_trade_risk=Decimal("1000"),
)


def _backtest_order(entry_index: int = 0) -> OrderIntent:
    return order_intent_adapter.build_backtest_entry_order_intent(
        strategy_id="orb-v1",
        instrument_id=str(INSTRUMENT),
        direction=order_intent_adapter.StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_timestamp=NOW,
        entry_index=entry_index,
    )


def _paper_order(idempotency_key: str = "idem-1") -> OrderIntent:
    return OrderIntent(
        order_id="ord-1",  # type: ignore[arg-type]
        instrument_id=INSTRUMENT,
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="orb-v1",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key=idempotency_key,
    )


def _paper_service(*, halted: bool = False) -> PaperTradingService:
    broker = PaperBroker(
        initial_capital=Decimal("100000"),
        compute_cost=lambda is_buy, notional: Decimal("0"),  # noqa: ARG005
        clock=lambda: NOW,
    )
    return PaperTradingService(
        broker=broker,
        risk_limits=RISK_LIMITS,
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("50000"),
        kill_switch_status_provider=(
            lambda: TradingHaltStatus.HALTED if halted else TradingHaltStatus.ACTIVE
        ),
        clock=lambda: NOW,
    )


# --- A/B: canonical RiskDecision vocabulary used by both -------------------


def test_a_backtest_risk_gate_calls_the_canonical_evaluate_order_risk_function() -> None:
    """`risk_gate_adapter.evaluate_backtest_entry_risk` calls the EXACT
    same function object `PaperTradingService.submit_order` calls -
    not a re-implementation, not a copy, the same `id()`."""
    assert risk_gate_adapter.evaluate_order_risk is domain_risk_policy.evaluate_order_risk


def test_b_paper_trading_service_calls_the_canonical_evaluate_order_risk_function() -> None:
    import intraday.application.services.paper_trading as paper_trading_module

    assert paper_trading_module.evaluate_order_risk is domain_risk_policy.evaluate_order_risk


def test_c_backtest_and_paper_trading_produce_the_identical_decision_type() -> None:
    """Both paths return `domain.risk.contracts.OrderRiskDecision` -
    literally the same class, proven with `type(...) is`."""
    order = _backtest_order()
    inputs = BacktestRiskGateInputs(
        risk_limits=RISK_LIMITS,
        risk_configuration_version="v1",
        now=NOW,
        cumulative_closed_trade_net_pnl=Decimal("0"),
        current_open_positions_count=0,
        current_position_size_for_instrument=Decimal("0"),
        estimated_order_notional=Decimal("1000"),
        max_concurrent_positions=1,
        max_total_exposure=Decimal("50000"),
        current_total_exposure=Decimal("0"),
    )
    backtest_decision = evaluate_backtest_entry_risk(order, inputs)

    paper_result = _paper_service().submit_order(
        _paper_order(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )

    assert type(backtest_decision) is OrderRiskDecision
    assert type(paper_result.risk_decision) is OrderRiskDecision
    assert type(backtest_decision) is type(paper_result.risk_decision)


# --- D/E/F/N: backtest, portfolio, and paper trading behaviour unchanged ---


def test_d_backtest_still_approves_via_the_same_adapter_shape_as_64_34() -> None:
    """Non-regression: `BacktestRiskGateInputs`/`evaluate_backtest_entry_risk`'s
    signature and approval behaviour, wired into `engine.py` since
    64.30, is untouched by this checkpoint."""
    order = _backtest_order()
    inputs = BacktestRiskGateInputs(
        risk_limits=RISK_LIMITS,
        risk_configuration_version="v1",
        now=NOW,
        cumulative_closed_trade_net_pnl=Decimal("0"),
        current_open_positions_count=0,
        current_position_size_for_instrument=Decimal("0"),
        estimated_order_notional=Decimal("1000"),
        max_concurrent_positions=1,
        max_total_exposure=Decimal("50000"),
        current_total_exposure=Decimal("0"),
    )
    decision = evaluate_backtest_entry_risk(order, inputs)
    assert decision.outcome is RiskDecisionOutcome.APPROVED


def test_e_portfolio_module_still_imports_the_same_unmodified_adapter() -> None:
    """`portfolio.py` (64.34) is untouched by this checkpoint - it still
    imports `evaluate_backtest_entry_risk`/`BacktestRiskGateInputs` from
    `risk_gate_adapter`, never a portfolio-specific copy."""
    import intraday.research.backtesting.portfolio as portfolio_module

    assert portfolio_module.evaluate_backtest_entry_risk is evaluate_backtest_entry_risk
    assert portfolio_module.BacktestRiskGateInputs is BacktestRiskGateInputs


def test_f_paper_trading_rejection_behaviour_is_unchanged() -> None:
    """Non-regression of Paper Trading's own pre-existing behaviour
    (mirrors `test_risk_engine_rejection_prevents_broker_report_from_ever_existing`
    in the architecture-fitness suite) - a HALTED kill switch still
    rejects before the broker is ever reached."""
    result = _paper_service(halted=True).submit_order(
        _paper_order(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert result.broker_report is None


# --- G/H/I/J: OrderIntent/RiskDecision lifecycle through the boundary -------


def test_g_approved_order_intent_reaches_paper_broker_unmodified() -> None:
    service = _paper_service()
    order = _paper_order()
    result = service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.APPROVED
    assert result.broker_report is not None
    assert result.broker_report.order_id == order.order_id


def test_h_rejected_order_intent_never_reaches_paper_broker_submission() -> None:
    service = _paper_service(halted=True)
    submitted: list[OrderIntent] = []
    original_submit = service.broker.submit_order
    service.broker.submit_order = lambda o: submitted.append(o) or original_submit(o)  # type: ignore[method-assign]

    result = service.submit_order(
        _paper_order(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert submitted == []


def test_i_risk_rejection_is_represented_by_the_canonical_order_risk_decision() -> None:
    result = _paper_service(halted=True).submit_order(
        _paper_order(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert isinstance(result.risk_decision, OrderRiskDecision)
    assert result.risk_decision.reason_code is not None


def test_j_risk_acceptance_is_represented_by_the_canonical_order_risk_decision() -> None:
    result = _paper_service().submit_order(
        _paper_order(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert isinstance(result.risk_decision, OrderRiskDecision)
    assert result.risk_decision.reason_code is None


# --- K: duplicate risk evaluation is absent ---------------------------------


def test_k_paper_trading_service_calls_evaluate_order_risk_exactly_once() -> None:
    """Structural proof over the actual source text: exactly one call
    site of `evaluate_order_risk(` inside `submit_order()` - if a
    second evaluation is ever introduced (accidental duplication), this
    test fails immediately rather than the duplication going unnoticed."""
    source = inspect.getsource(PaperTradingService.submit_order)
    assert source.count("= evaluate_order_risk(") == 1


def test_k_paper_broker_module_never_imports_the_risk_policy() -> None:
    """`PaperBroker` performs its own legitimate, narrow EXECUTION safety
    check (sufficient-balance-for-fill, `broker.py`'s `_attempt_fill`) -
    that is a broker/execution concern, never a duplicate of the
    strategy risk policy. Proven structurally: `PaperBroker`'s module
    never imports `domain.risk` at all."""
    source_file = SRC_ROOT / "infrastructure" / "brokers" / "paper" / "broker.py"
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("domain.risk" in name for name in imported)


# --- L: PaperBroker remains responsible only for broker/execution safety ---


def test_l_paper_broker_has_no_risk_decision_or_risk_limits_symbol() -> None:
    source_file = SRC_ROOT / "infrastructure" / "brokers" / "paper" / "broker.py"
    source = source_file.read_text(encoding="utf-8")
    assert "RiskDecision" not in source
    assert "RiskLimits" not in source
    assert "evaluate_order_risk" not in source


# --- C (vocabulary): no duplicate risk/order types exist --------------------


def test_no_duplicate_risk_or_order_intent_vocabulary_exists_in_the_repository() -> None:
    """Repo-wide proof that no `PaperOrderIntent`/`PaperRiskDecision`/
    `BacktestRiskDecision`/`LiveRiskDecision`/`PortfolioRiskDecision`
    type was created anywhere - the canonical `OrderIntent`/
    `OrderRiskDecision` from `domain.order.contracts`/`domain.risk.contracts`
    remain the ONLY such types in the codebase."""
    forbidden_names = (
        "PaperOrderIntent",
        "PaperRiskDecision",
        "BacktestRiskDecision",
        "LiveRiskDecision",
        "PortfolioRiskDecision",
        "class RiskDecision2",
    )
    for source_file in SRC_ROOT.rglob("*.py"):
        source = source_file.read_text(encoding="utf-8")
        for forbidden in forbidden_names:
            assert forbidden not in source, f"{forbidden!r} found in {source_file}"


# --- M: no Dhan/live code touched by this convergence check -----------------


def test_m_paper_trading_convergence_modules_do_not_import_dhan() -> None:
    """Structural (imports only), not textual - these modules' own
    docstrings legitimately DISCUSS a hypothetical future Dhan adapter
    (e.g. `paper_trading.py`'s header, `broker.py`'s docstring) without
    ever importing anything Dhan-shaped."""
    for module_path in (
        SRC_ROOT / "application" / "services" / "paper_trading.py",
        SRC_ROOT / "research" / "backtesting" / "risk_gate_adapter.py",
        SRC_ROOT / "research" / "backtesting" / "order_intent_adapter.py",
    ):
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not any("dhan" in name.lower() for name in imported)


# --- O: no Fill/Execution model introduced by this checkpoint --------------


def test_o_no_fill_or_execution_report_type_introduced_by_this_checkpoint() -> None:
    for forbidden in ("class FillReport", "class ExecutionReport", "class SlippageModel"):
        for source_file in SRC_ROOT.rglob("*.py"):
            assert forbidden not in source_file.read_text(
                encoding="utf-8"
            ), f"{forbidden!r} found in {source_file}"


def test_paper_order_submission_result_type_is_unchanged_shape() -> None:
    """Non-regression: `PaperOrderSubmissionResult` still carries exactly
    `risk_decision`/`broker_report` - this checkpoint added no new
    field to it (no execution convergence was performed)."""
    field_names = set(PaperOrderSubmissionResult.__dataclass_fields__)
    assert field_names == {"risk_decision", "broker_report"}
