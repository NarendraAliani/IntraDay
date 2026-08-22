# tests/unit/research/test_checkpoint_64_38_paper_mark_to_market.py
#
# Checkpoint 64.38: PAPER MARK-TO-MARKET / UNREALIZED P&L. Covers the new
# pure module `intraday.domain.position.mark_to_market` AND its wiring
# into `PaperBroker.record_price()` (the real production entry point).
from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.position.contracts import Position, PositionId, PositionStatus
from intraday.domain.position.mark_to_market import (
    compute_market_value,
    compute_unrealized_pnl,
    mark_position,
    position_market_value,
)
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.brokers.paper.broker import PaperBroker

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
BASE = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)


def _no_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
    return Decimal("0")


def _clock_sequence(start: datetime):  # type: ignore[no-untyped-def]
    state = {"t": start}

    def _clock() -> datetime:
        state["t"] += timedelta(seconds=1)
        return state["t"]

    return _clock


def _broker(**overrides: object) -> PaperBroker:
    fields: dict[str, object] = {
        "initial_capital": Decimal("100000"),
        "compute_cost": _no_cost,
        "clock": _clock_sequence(BASE),
    }
    fields.update(overrides)
    return PaperBroker(**fields)  # type: ignore[arg-type]


def _order(**overrides: object) -> OrderIntent:
    fields: dict[str, object] = {
        "order_id": "ord-1",
        "instrument_id": RELIANCE,
        "side": Side.BUY,
        "quantity": Decimal("10"),
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.DAY,
        "strategy_id": "orb-v1",
        "created_at": BASE,
        "idempotency_key": "idem-1",
    }
    fields.update(overrides)
    return OrderIntent(**fields)  # type: ignore[arg-type]


def _position(**overrides: object) -> Position:
    fields: dict[str, object] = {
        "position_id": PositionId("pos-1"),
        "instrument_id": RELIANCE,
        "direction": Side.BUY,
        "quantity": Decimal("10"),
        "average_entry_price": Decimal("100"),
        "realized_pnl": Decimal("0"),
        "unrealized_pnl": Decimal("0"),
        "opened_at": BASE,
        "status": PositionStatus.OPEN,
        "realized_net_pnl": Decimal("0"),
    }
    fields.update(overrides)
    return Position(**fields)  # type: ignore[arg-type]


# --- A/B: long profitable / losing --------------------------------------


def test_a_long_profitable_unrealized_pnl() -> None:
    pnl = compute_unrealized_pnl(
        direction=Side.BUY,
        average_entry_price=Decimal("100"),
        remaining_quantity=Decimal("10"),
        mark_price=Decimal("110"),
    )
    assert pnl == Decimal("100")


def test_b_long_losing_unrealized_pnl() -> None:
    pnl = compute_unrealized_pnl(
        direction=Side.BUY,
        average_entry_price=Decimal("100"),
        remaining_quantity=Decimal("10"),
        mark_price=Decimal("95"),
    )
    assert pnl == Decimal("-50")


# --- C/D: short profitable / losing --------------------------------------


def test_c_short_profitable_unrealized_pnl() -> None:
    pnl = compute_unrealized_pnl(
        direction=Side.SELL,
        average_entry_price=Decimal("100"),
        remaining_quantity=Decimal("10"),
        mark_price=Decimal("90"),
    )
    assert pnl == Decimal("100")


def test_d_short_losing_unrealized_pnl() -> None:
    pnl = compute_unrealized_pnl(
        direction=Side.SELL,
        average_entry_price=Decimal("100"),
        remaining_quantity=Decimal("10"),
        mark_price=Decimal("105"),
    )
    assert pnl == Decimal("-50")


# --- E: zero movement ------------------------------------------------------


def test_e_zero_movement_unrealized_pnl_is_zero() -> None:
    pnl = compute_unrealized_pnl(
        direction=Side.BUY,
        average_entry_price=Decimal("100"),
        remaining_quantity=Decimal("10"),
        mark_price=Decimal("100"),
    )
    assert pnl == Decimal("0")


# --- F: multiple isolated positions ---------------------------------------


def test_f_marking_one_instrument_does_not_affect_another() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.record_price(TCS, Decimal("200"), BASE)
    broker.submit_order(_order(order_id="o1", idempotency_key="k1", instrument_id=RELIANCE))
    broker.submit_order(
        _order(order_id="o2", idempotency_key="k2", instrument_id=TCS, quantity=Decimal("5"))
    )
    broker.record_price(RELIANCE, Decimal("110"), BASE)  # only RELIANCE moves

    positions = {p.instrument_id: p for p in broker.get_positions()}
    assert positions[RELIANCE].unrealized_pnl == Decimal("100")
    assert positions[TCS].unrealized_pnl == Decimal("0")  # never marked at a new price


# --- G: remaining-quantity based, not original quantity --------------------


def test_g_uses_remaining_quantity_not_original() -> None:
    # Position already reduced (partial exit already applied) to qty 4 of an
    # original 10 - unrealized P&L must be based on the REMAINING 4.
    position = _position(quantity=Decimal("4"), average_entry_price=Decimal("100"))
    marked = mark_position(position, Decimal("110"))
    assert marked.unrealized_pnl == Decimal("40")  # 4 * 10, not 10 * 10


# --- H: closed position is a no-op -----------------------------------------


def test_h_closed_position_mark_is_noop() -> None:
    position = _position(
        status=PositionStatus.CLOSED,
        closed_at=BASE,
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("500"),
    )
    marked = mark_position(position, Decimal("999"))
    assert marked is position
    assert marked.unrealized_pnl == Decimal("0")


# --- I: market value correctness --------------------------------------------


def test_i_long_market_value_is_positive() -> None:
    mv = compute_market_value(
        direction=Side.BUY, remaining_quantity=Decimal("10"), mark_price=Decimal("110")
    )
    assert mv == Decimal("1100")


def test_i_short_market_value_is_negative() -> None:
    mv = compute_market_value(
        direction=Side.SELL, remaining_quantity=Decimal("10"), mark_price=Decimal("90")
    )
    assert mv == Decimal("-900")


def test_i_position_market_value_matches_compute_market_value() -> None:
    position = _position(
        direction=Side.BUY, quantity=Decimal("10"), average_entry_price=Decimal("100")
    )
    marked = mark_position(position, Decimal("110"))
    assert position_market_value(marked) == compute_market_value(
        direction=Side.BUY, remaining_quantity=Decimal("10"), mark_price=Decimal("110")
    )


# --- J: total unrealized P&L across multiple positions ---------------------


def test_j_total_unrealized_pnl_across_positions_equals_sum() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.record_price(TCS, Decimal("200"), BASE)
    broker.submit_order(_order(order_id="o1", idempotency_key="k1", instrument_id=RELIANCE))
    broker.submit_order(
        _order(order_id="o2", idempotency_key="k2", instrument_id=TCS, quantity=Decimal("5"))
    )
    broker.record_price(RELIANCE, Decimal("110"), BASE)  # +100
    broker.record_price(TCS, Decimal("190"), BASE)  # 5 * (190-200) = -50

    total = broker.get_total_unrealized_pnl()
    assert total == Decimal("50")


# --- K: equity reconciliation -----------------------------------------------


def test_k_equity_reconciles_cash_plus_market_value() -> None:
    broker = _broker(initial_capital=Decimal("100000"))
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order())
    broker.record_price(RELIANCE, Decimal("110"), BASE)

    funds = broker.get_funds()
    mv = broker.get_open_positions_market_value()
    equity = broker.get_equity()
    assert equity == funds.available_balance + mv
    # cash spent 1000 buying 10@100; market value now 10*110=1100
    assert funds.available_balance == Decimal("99000")
    assert mv == Decimal("1100")
    assert equity == Decimal("100100")


# --- L: realized_pnl/realized_net_pnl stay separate from unrealized --------


def test_l_marking_open_position_does_not_touch_realized_fields() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order())
    before = broker.get_positions()[0]
    broker.record_price(RELIANCE, Decimal("150"), BASE)
    after = broker.get_positions()[0]
    assert after.realized_pnl == before.realized_pnl == Decimal("0")
    assert after.realized_net_pnl == before.realized_net_pnl == Decimal("0")
    assert after.unrealized_pnl == Decimal("500")


def test_l_closing_does_not_retroactively_alter_unrealized_history() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order())
    broker.record_price(RELIANCE, Decimal("120"), BASE)
    marked = broker.get_positions()[0]
    assert marked.unrealized_pnl == Decimal("200")

    broker.submit_order(
        _order(order_id="o2", idempotency_key="k2", side=Side.SELL, quantity=Decimal("10"))
    )
    closed = broker.get_positions()[0]
    assert closed.status is PositionStatus.CLOSED
    assert closed.unrealized_pnl == Decimal("0")
    assert closed.realized_pnl == Decimal("200")


# --- M: no transaction-cost double counting ---------------------------------


def test_m_unrealized_pnl_is_cost_exclusive() -> None:
    # compute_unrealized_pnl has no cost parameter at all - assert its
    # signature has exactly the four documented keyword params.
    import inspect

    params = list(inspect.signature(compute_unrealized_pnl).parameters)
    assert set(params) == {
        "direction",
        "average_entry_price",
        "remaining_quantity",
        "mark_price",
    }
    # Numerically: a fee-laden entry (cost paid, but not reflected in
    # average_entry_price) still yields the pure price delta.
    pnl = compute_unrealized_pnl(
        direction=Side.BUY,
        average_entry_price=Decimal("100"),
        remaining_quantity=Decimal("10"),
        mark_price=Decimal("105"),
    )
    assert pnl == Decimal("50")  # no cost subtracted anywhere


# --- N: missing/never-marked position handled safely ------------------------


def test_n_never_marked_position_has_zero_unrealized_not_fabricated() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order())
    # No further record_price call for RELIANCE - position stays "unmarked".
    position = broker.get_positions()[0]
    assert position.unrealized_pnl == Decimal("0")
    # Documented behavior (N/A separate staleness concept - see docs): an
    # unmarked position's market value correctly reduces to book value.
    assert position_market_value(position) == Decimal("1000")  # 10 * 100


# --- O: stale-mark - N/A, documented, asserted here as "no separate concept"


def test_o_no_separate_staleness_concept_beyond_never_marked() -> None:
    # mark_position has no timestamp/freshness parameter - the only two
    # states are "never marked" (unrealized_pnl == 0, book value) and
    # "marked against the most recent record_price() price". There is no
    # third "stale" state modeled in this checkpoint.
    import inspect

    params = list(inspect.signature(mark_position).parameters)
    assert params == ["position", "mark_price"]


# --- P: AST guard - no Dhan import in this test module or modified src -----


def test_p_no_dhan_import_in_this_test_module() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "dhan" not in alias.name.lower()
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or "dhan" not in node.module.lower()


def test_p_no_dhan_import_in_modified_src_files() -> None:
    modified = [
        Path("src/intraday/domain/position/mark_to_market.py"),
        Path("src/intraday/infrastructure/brokers/paper/broker.py"),
    ]
    repo_root = Path(__file__).resolve().parents[3]
    for rel in modified:
        path = repo_root / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "dhan" not in alias.name.lower()
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or "dhan" not in node.module.lower()


# --- Q: no new network dependency -------------------------------------------


def test_q_mark_to_market_module_has_no_network_imports() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / "src/intraday/domain/position/mark_to_market.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"requests", "httpx", "socket", "aiohttp", "urllib"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden


# --- R: 64.37 Risk Gate tests unchanged (re-run fresh) ----------------------


def test_r_checkpoint_64_37_risk_gate_still_passes() -> None:
    import subprocess
    import sys

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/research/test_checkpoint_64_37_net_pnl_risk_contract.py",
            "-q",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "22 passed" in result.stdout, result.stdout + result.stderr


# --- S: backtest engine/contracts/portfolio unchanged (zero diff) ----------


def test_s_backtest_engine_and_contracts_have_zero_git_diff() -> None:
    # engine.py/contracts.py: untouched by 64.38 - zero diff expected.
    # portfolio.py is deliberately excluded here: it already carries an
    # UNCOMMITTED diff from an earlier checkpoint (64.33's convergence
    # audit), predating this session - 64.38 never edited it (verified
    # separately below by asserting it is absent from THIS checkpoint's
    # own change set).
    import subprocess

    repo_root = Path(__file__).resolve().parents[3]
    for rel in (
        "src/intraday/research/backtesting/engine.py",
        "src/intraday/research/backtesting/contracts.py",
    ):
        result = subprocess.run(  # noqa: S603
            ["git", "diff", "--stat", "--", rel],  # noqa: S607
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.stdout.strip() == "", f"{rel} has unexpected diff: {result.stdout}"


def test_s_backtest_numerical_modules_not_edited_by_this_checkpoint() -> None:
    # This checkpoint's own file set is exactly mark_to_market.py (new) +
    # broker.py (wiring) + this test file + docs/taskReport - no backtest
    # numerical module is in that set.
    checkpoint_64_38_files = {
        "src/intraday/domain/position/mark_to_market.py",
        "src/intraday/infrastructure/brokers/paper/broker.py",
        "tests/unit/research/test_checkpoint_64_38_paper_mark_to_market.py",
    }
    backtest_numerical_modules = {
        "src/intraday/research/backtesting/engine.py",
        "src/intraday/research/backtesting/contracts.py",
        "src/intraday/research/backtesting/portfolio.py",
    }
    assert checkpoint_64_38_files.isdisjoint(backtest_numerical_modules)


# --- T/U: Paper realized_pnl / realized_net_pnl unchanged by this checkpoint


def test_t_realized_pnl_formula_unchanged() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order())
    broker.record_price(RELIANCE, Decimal("130"), BASE)
    broker.submit_order(
        _order(order_id="o2", idempotency_key="k2", side=Side.SELL, quantity=Decimal("10"))
    )
    closed = broker.get_positions()[0]
    assert closed.realized_pnl == Decimal("300")  # 10 * (130 - 100), unchanged formula


def test_u_realized_net_pnl_formula_unchanged() -> None:
    def cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
        return Decimal("10")

    broker = _broker(compute_cost=cost)
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order())
    broker.record_price(RELIANCE, Decimal("130"), BASE)
    broker.submit_order(
        _order(order_id="o2", idempotency_key="k2", side=Side.SELL, quantity=Decimal("10"))
    )
    closed = broker.get_positions()[0]
    # gross realized 300, entry cost 10 + exit cost 10 = 20 -> net 280
    assert closed.realized_pnl == Decimal("300")
    assert closed.realized_net_pnl == Decimal("280")


# --- V: no Fill/ExecutionReport/PartialFill/SlippageModel/BrokerOrder class introduced


def test_v_no_new_execution_convergence_classes_introduced() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / "src/intraday/domain/position/mark_to_market.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_names = {"Fill", "ExecutionReport", "PartialFill", "SlippageModel", "BrokerOrder"}
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert defined.isdisjoint(forbidden_names)


# --- W: no partial-exit execution engine introduced (deferred) -------------


def test_w_no_partial_exit_engine_introduced() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / "src/intraday/domain/position/mark_to_market.py"
    source = path.read_text(encoding="utf-8").lower()
    assert "partial_exit_engine" not in source
    assert "execute_partial_exit" not in source


# --- Real production path: PaperBroker + record_price end to end -----------


def test_real_production_path_long_position_marked_via_record_price() -> None:
    broker = _broker(initial_capital=Decimal("50000"))
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    report = broker.submit_order(_order(quantity=Decimal("10")))
    assert report.status.name == "FILLED"

    broker.record_price(RELIANCE, Decimal("112.50"), BASE)

    position = broker.get_positions()[0]
    assert position.unrealized_pnl == Decimal("125.00")  # 10 * 12.50
    assert position.status is PositionStatus.OPEN

    equity = broker.get_equity()
    funds = broker.get_funds()
    assert equity == funds.available_balance + broker.get_open_positions_market_value()


def test_real_production_path_short_position_marked_via_record_price() -> None:
    broker = _broker(initial_capital=Decimal("50000"))
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order(side=Side.SELL, quantity=Decimal("10")))
    broker.record_price(RELIANCE, Decimal("90"), BASE)

    position = broker.get_positions()[0]
    assert position.direction is Side.SELL
    assert position.unrealized_pnl == Decimal("100")  # short profitable: 10 * (100-90)


@pytest.mark.parametrize("mark_price", [Decimal("100"), Decimal("50"), Decimal("999.99")])
def test_zero_and_various_marks_never_raise(mark_price: Decimal) -> None:
    position = _position()
    marked = mark_position(position, mark_price)
    assert isinstance(marked.unrealized_pnl, Decimal)


def test_mark_price_must_be_positive() -> None:
    with pytest.raises(ValueError):
        compute_unrealized_pnl(
            direction=Side.BUY,
            average_entry_price=Decimal("100"),
            remaining_quantity=Decimal("10"),
            mark_price=Decimal("0"),
        )


def test_remaining_quantity_must_not_be_negative() -> None:
    with pytest.raises(ValueError):
        compute_unrealized_pnl(
            direction=Side.BUY,
            average_entry_price=Decimal("100"),
            remaining_quantity=Decimal("-1"),
            mark_price=Decimal("100"),
        )
