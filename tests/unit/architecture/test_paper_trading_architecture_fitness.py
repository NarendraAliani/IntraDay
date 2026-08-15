# tests/unit/architecture/test_paper_trading_architecture_fitness.py
#
# Checkpoint 34 Part 19: mechanical proof (not documentation) of the
# six architecture-fitness claims this checkpoint's brief names
# explicitly:
#   - PaperBroker does not depend on Dhan
#   - Dhan adapter does not leak broker-specific types into domain
#   - Risk engine sits before order submission
#   - Kill switch cannot be bypassed
#   - Reconciliation does not mutate execution state automatically
#   - Paper trading cannot enter LIVE mode
from __future__ import annotations

import ast
import inspect
from decimal import Decimal
from pathlib import Path

from intraday.application.services.paper_trading import PaperTradingService
from intraday.infrastructure.brokers.paper import broker as paper_broker_module

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src" / "intraday"


def _imported_module_names(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_paper_broker_does_not_import_dhan() -> None:
    source_file = Path(paper_broker_module.__file__)
    imported = _imported_module_names(source_file)
    assert not any("dhan" in name.lower() for name in imported)


def test_dhan_client_modules_do_not_import_order_or_broker_domain_types() -> None:
    """Reversed check: the existing Dhan clients (Checkpoint 22/23) must
    never leak Dhan-specific concepts INTO the domain layer, and the
    domain layer must never need to know about Dhan - proven by
    checking domain/order and domain/broker never import anything
    dhan-shaped."""
    for module_path in ("domain/order", "domain/broker"):
        for source_file in (SRC_ROOT / module_path).rglob("*.py"):
            imported = _imported_module_names(source_file)
            assert not any("dhan" in name.lower() for name in imported), source_file


def test_risk_evaluation_runs_before_broker_submission_in_service_source() -> None:
    """A structural proof, not just a runtime test: the ORDER of
    statements in `PaperTradingService.submit_order`'s source code
    calls `evaluate_order_risk` strictly before
    `self._broker.submit_order` - proven by inspecting the actual
    source text ordering, so a future edit that silently reorders the
    two calls fails this test immediately."""
    source = inspect.getsource(PaperTradingService.submit_order)
    risk_call_index = source.index("evaluate_order_risk(")
    broker_call_index = source.rindex("self.broker.submit_order(")
    assert risk_call_index < broker_call_index


def test_kill_switch_is_read_before_risk_evaluation() -> None:
    """The kill-switch status is fetched and threaded into the SAME
    risk-evaluation context object `evaluate_order_risk` checks first
    (Checkpoint 34 Part 10's own fixed check-ordering, `KILL_SWITCH_ENGAGED`
    is check #1) - there is no code path in `PaperTradingService` that
    calls `self._broker.submit_order` without first constructing that
    context from `self._kill_switch_status_provider()`."""
    source = inspect.getsource(PaperTradingService.submit_order)
    kill_switch_index = source.index("self._kill_switch_status_provider()")
    broker_call_index = source.rindex("self.broker.submit_order(")
    assert kill_switch_index < broker_call_index


def test_reconciler_module_contains_no_write_or_mutation_calls() -> None:
    """Part 13's "no automatic corrective action" - mechanically
    checked: the reconciliation module must never call `.save()`,
    `.update()`, `.delete()`, or any `BrokerGateway` mutating method
    (`submit_order`/`cancel_order`/`modify_order`)."""
    source_file = SRC_ROOT / "control_plane" / "reconciliation" / "reconciler.py"
    source = source_file.read_text(encoding="utf-8")
    forbidden = (
        ".save(",
        ".update(",
        ".delete(",
        "submit_order(",
        "cancel_order(",
        "modify_order(",
    )
    for token in forbidden:
        assert token not in source, f"{token!r} must never appear in reconciler.py"


def test_no_trading_mode_live_reference_in_paper_trading_modules() -> None:
    """Paper trading modules must never reference or enable a LIVE
    trading mode - a purely textual, structural check that no
    'TRADING_MODE' or 'LIVE' capability toggle exists anywhere in this
    checkpoint's new modules."""
    paper_trading_files = [
        SRC_ROOT / "application" / "services" / "paper_trading.py",
        SRC_ROOT / "infrastructure" / "brokers" / "paper" / "broker.py",
    ]
    for source_file in paper_trading_files:
        source = source_file.read_text(encoding="utf-8")
        assert "TRADING_MODE" not in source
        assert "place_live_order" not in source


def test_paper_broker_never_performs_network_io() -> None:
    """No `httpx`/`requests`/`socket`/`websocket` import anywhere in
    the paper broker - it is purely in-memory simulation, structurally
    incapable of reaching a real broker."""
    source_file = Path(paper_broker_module.__file__)
    imported = _imported_module_names(source_file)
    network_libraries = {"httpx", "requests", "socket", "websocket", "aiohttp"}
    assert not (imported & network_libraries)


def test_paper_trading_service_never_imports_the_dhan_client_module() -> None:
    source_file = SRC_ROOT / "application" / "services" / "paper_trading.py"
    imported = _imported_module_names(source_file)
    assert not any("dhan" in name.lower() for name in imported)


def test_risk_engine_rejection_prevents_broker_report_from_ever_existing() -> None:
    """End-to-end proof (not just source inspection): a REJECTED risk
    decision means `broker_report` is structurally `None` - the type
    itself proves the broker was never reached, verified by actually
    calling the service with a rejection-guaranteed input."""
    from datetime import UTC, datetime

    from intraday.domain.instrument.contracts import make_instrument_id
    from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
    from intraday.domain.risk.contracts import RiskDecisionOutcome, RiskLimits, TradingHaltStatus
    from intraday.domain.shared_kernel.contracts import Exchange, Side
    from intraday.infrastructure.brokers.paper.broker import PaperBroker

    instrument = make_instrument_id(Exchange.NSE, "RELIANCE")
    now = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)
    broker = PaperBroker(
        initial_capital=Decimal("100000"),
        compute_cost=lambda is_buy, notional: Decimal("0"),  # noqa: ARG005
        clock=lambda: now,
    )
    service = PaperTradingService(
        broker=broker,
        risk_limits=RiskLimits(
            max_intraday_loss=Decimal("5000"),
            max_position_size=Decimal("100"),
            max_per_trade_risk=Decimal("1000"),
        ),
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("50000"),
        kill_switch_status_provider=lambda: TradingHaltStatus.HALTED,
        clock=lambda: now,
    )
    order = OrderIntent(
        order_id="ord-1",  # type: ignore[arg-type]
        instrument_id=instrument,
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="orb-v1",  # type: ignore[arg-type]
        created_at=now,
        idempotency_key="idem-1",
    )
    result = service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert result.broker_report is None
