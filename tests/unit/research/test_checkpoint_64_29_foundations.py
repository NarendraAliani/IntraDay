# tests/unit/research/test_checkpoint_64_29_foundations.py
#
# Checkpoint 64.29: characterization + unit tests for the three
# standalone, UNWIRED foundation targets built this checkpoint:
#   1. `risk_gate_adapter.py` - proves (a) `run_backtest()` today does
#      NOT apply the canonical risk gate to any entry (the honest gap),
#      and (b) the adapter itself correctly builds a real
#      `RiskEvaluationContext` and calls the real, unmodified
#      `evaluate_order_risk()`.
#   2. `order_intent_adapter.py` - proves a real `OrderIntent` can be
#      built from backtest entry-decision state, honestly.
#   3. `position_lifecycle.py` - proves the OPEN/HELD/CLOSED invariant.
#
# None of these tests touch `run_backtest()`'s own control flow, only
# call it as a read-only oracle (same discipline as
# `test_mark_to_market_accounting.py`, 64.26/64.27).
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderType, TimeInForce
from intraday.domain.risk.contracts import RiskDecisionOutcome, RiskLimits, RiskRejectionReason
from intraday.domain.shared_kernel.contracts import Side, Timeframe
from intraday.research.backtesting import StrategyConfigurationValues, StrategyDirection
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.research.backtesting.order_intent_adapter import (
    backtest_direction_to_side,
    build_backtest_entry_order_intent,
)
from intraday.research.backtesting.position_lifecycle import (
    BacktestPositionLifecycleStatus,
    close_backtest_position,
    hold_backtest_position,
    open_backtest_position,
)
from intraday.research.backtesting.risk_gate_adapter import (
    BacktestRiskGateInputs,
    evaluate_backtest_entry_risk,
)
from intraday.trading_engine.strategy_execution.contracts import StrategyParameterSchema

INSTRUMENT = "NSE:TESTCO"
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


# --- Minimal scripted strategy (same shape as
# test_mark_to_market_accounting.py's own `_ScriptedStrategy`, copied
# locally so this file has no cross-test-file coupling). ------------
@dataclass
class _StubSignal:
    direction: StrategyDirection


class _ScriptedStrategy:
    strategy_id = "scripted_stub_6429"
    display_name = "Scripted Stub 64.29"
    specification_version = "v1"
    code_version = "v1"

    def __init__(self, signals_by_index: dict[int, StrategyDirection]) -> None:
        self._signals_by_index = signals_by_index
        self._index = -1

    def parameter_schema(self) -> StrategyParameterSchema:
        return StrategyParameterSchema(strategy_id=self.strategy_id, parameters=())

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        return ()

    def evaluate(self, bar: Bar, feature_values: dict, config: StrategyConfigurationValues):
        self._index += 1
        direction = self._signals_by_index.get(self._index)
        if direction is None:
            return None
        from intraday.trading_engine.strategy_execution.contracts import StrategySignal

        return StrategySignal(
            strategy_id=self.strategy_id,
            specification_version=self.specification_version,
            code_version=self.code_version,
            configuration_version="v1",
            instrument_id=bar.instrument_id,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            direction=direction,
            price=bar.close,
        )


def _bars_from_closes(closes: list[str]) -> tuple[Bar, ...]:
    bars = []
    for i, c in enumerate(closes):
        price = Decimal(c)
        bars.append(
            Bar(
                instrument_id=INSTRUMENT,
                timeframe=Timeframe.ONE_MINUTE,
                timestamp=BASE + timedelta(minutes=i),
                open=price,
                high=price + Decimal("5"),
                low=price - Decimal("5"),
                close=price,
                volume=Decimal("0"),
            )
        )
    return tuple(bars)


def _dq(bar_count: int) -> DataQualityDisclosure:
    return DataQualityDisclosure(
        data_source="fixture",
        data_quality=DataQualityLabel.FIXTURE_OR_HISTORICAL,
        bar_count=bar_count,
        missing_bar_note="none",
        transaction_cost_assumption="flat pct",
        slippage_assumption="flat pct",
        survivorship_bias_note="n/a",
    )


def _config(**overrides: object) -> BacktestConfiguration:
    defaults: dict[str, object] = {
        "instrument_id": INSTRUMENT,
        "timeframe": Timeframe.ONE_MINUTE,
        "start": BASE,
        "end": BASE + timedelta(minutes=40),
        "strategy_id": "scripted_stub_6429",
        "specification_version": "v1",
        "code_version": "v1",
        "configuration_version": "v1",
        "initial_capital": Decimal("100000"),
        "position_sizing_mode": PositionSizingMode.FIXED_QUANTITY,
        "position_size_value": Decimal("10"),
        "brokerage_percent": Decimal("0"),
        "slippage_percent": Decimal("0"),
    }
    defaults.update(overrides)
    return BacktestConfiguration(**defaults)  # type: ignore[arg-type]


# =====================================================================
# Target 1a - characterization: `run_backtest()` does NOT apply the
# canonical risk gate. A `RiskLimits` restrictive enough to reject a
# 10-share order via the REAL `evaluate_order_risk()` is constructed;
# the SAME backtest, with the SAME quantity, is proven to still enter
# the trade - because no risk gate exists in the backtest path today.
# =====================================================================


def test_backtest_enters_a_trade_that_the_real_risk_gate_would_have_rejected() -> None:
    closes = ["100", "100", "105", "105", "110"]
    signals = {0: StrategyDirection.BULLISH, 2: StrategyDirection.BEARISH}
    bars = _bars_from_closes(closes)
    strategy = _ScriptedStrategy(signals)
    result = run_backtest(
        bars,
        strategy,  # type: ignore[arg-type]
        StrategyConfigurationValues("scripted_stub_6429", "v1", "v1", "v1", {}),
        _config(end=BASE + timedelta(minutes=len(closes) + 5)),
        lambda field_id, bars_: (),
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )

    # The backtest entered and closed exactly one 10-share trade -
    # `run_backtest()` never even considered a risk decision.
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.quantity == Decimal("10")

    # Now prove a REAL risk evaluation, using the SAME order the
    # backtest implicitly placed, would have been REJECTED - a
    # `max_position_size` of 5 is well below the 10-share quantity the
    # backtest actually entered.
    restrictive_limits = RiskLimits(
        max_intraday_loss=Decimal("100000"),
        max_position_size=Decimal("5"),
        max_per_trade_risk=Decimal("100000"),
    )
    order = build_backtest_entry_order_intent(
        strategy_id="scripted_stub_6429",
        instrument_id=INSTRUMENT,
        direction=trade.direction,
        quantity=trade.quantity,
        entry_timestamp=trade.entry_timestamp,
        entry_index=0,
    )
    inputs = BacktestRiskGateInputs(
        risk_limits=restrictive_limits,
        risk_configuration_version="test-v1",
        now=trade.entry_timestamp,
        cumulative_closed_trade_net_pnl=Decimal("0"),
        current_open_positions_count=0,
        current_position_size_for_instrument=Decimal("0"),
        estimated_order_notional=trade.entry_price * trade.quantity,
        max_concurrent_positions=1,
        max_total_exposure=Decimal("1000000"),
        current_total_exposure=Decimal("0"),
    )
    decision = evaluate_backtest_entry_risk(order, inputs)

    assert decision.outcome is RiskDecisionOutcome.REJECTED
    assert decision.reason_code is RiskRejectionReason.MAX_POSITION_SIZE_EXCEEDED

    # The characterization, stated precisely: the backtest ENTERED this
    # exact 10-share trade, even though the real, canonical risk policy
    # would have REJECTED it. This is the honest gap Checkpoint 64.28
    # identified and this checkpoint proves mechanically, not merely by
    # citation - `run_backtest()` itself was never modified or called
    # differently; the same `result.trades[0]` is used for both halves
    # of this proof.


# =====================================================================
# Target 1b - the adapter itself, in isolation: correct APPROVED and
# REJECTED paths, using the REAL `evaluate_order_risk()`.
# =====================================================================


def _permissive_inputs(**overrides: object) -> BacktestRiskGateInputs:
    defaults: dict[str, object] = dict(  # noqa: C408
        risk_limits=RiskLimits(
            max_intraday_loss=Decimal("50000"),
            max_position_size=Decimal("100"),
            max_per_trade_risk=Decimal("50000"),
        ),
        risk_configuration_version="test-v1",
        now=BASE,
        cumulative_closed_trade_net_pnl=Decimal("0"),
        current_open_positions_count=0,
        current_position_size_for_instrument=Decimal("0"),
        estimated_order_notional=Decimal("1000"),
        max_concurrent_positions=1,
        max_total_exposure=Decimal("1000000"),
        current_total_exposure=Decimal("0"),
    )
    defaults.update(overrides)
    return BacktestRiskGateInputs(**defaults)  # type: ignore[arg-type]


def _entry_order(**overrides: object):
    defaults: dict[str, object] = dict(  # noqa: C408
        strategy_id="scripted_stub_6429",
        instrument_id=INSTRUMENT,
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_timestamp=BASE,
        entry_index=0,
    )
    defaults.update(overrides)
    return build_backtest_entry_order_intent(**defaults)  # type: ignore[arg-type]


def test_adapter_approves_an_order_within_permissive_limits() -> None:
    decision = evaluate_backtest_entry_risk(_entry_order(), _permissive_inputs())
    assert decision.outcome is RiskDecisionOutcome.APPROVED
    assert decision.reason_code is None


def test_adapter_rejects_on_max_daily_loss_using_cumulative_net_pnl() -> None:
    # The adapter feeds `cumulative_closed_trade_net_pnl` into
    # `current_daily_realized_pnl` - a loss of exactly the configured
    # max must reject, proving the wiring (not merely the field name)
    # is correct.
    inputs = _permissive_inputs(
        cumulative_closed_trade_net_pnl=Decimal("-50000"),
        risk_limits=RiskLimits(
            max_intraday_loss=Decimal("50000"),
            max_position_size=Decimal("100"),
            max_per_trade_risk=Decimal("50000"),
        ),
    )
    decision = evaluate_backtest_entry_risk(_entry_order(), inputs)
    assert decision.outcome is RiskDecisionOutcome.REJECTED
    assert decision.reason_code is RiskRejectionReason.MAX_DAILY_LOSS_EXCEEDED


def test_adapter_rejects_on_max_concurrent_positions() -> None:
    inputs = _permissive_inputs(current_open_positions_count=1, max_concurrent_positions=1)
    decision = evaluate_backtest_entry_risk(_entry_order(), inputs)
    assert decision.outcome is RiskDecisionOutcome.REJECTED
    assert decision.reason_code is RiskRejectionReason.MAX_CONCURRENT_POSITIONS_EXCEEDED


# =====================================================================
# Target 2 - OrderIntent adapter, standalone unit tests.
# =====================================================================


def test_build_backtest_entry_order_intent_is_a_real_honest_order_intent() -> None:
    order = build_backtest_entry_order_intent(
        strategy_id="scripted_stub_6429",
        instrument_id=INSTRUMENT,
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_timestamp=BASE,
        entry_index=3,
    )
    assert order.instrument_id == INSTRUMENT
    assert order.side is Side.BUY
    assert order.quantity == Decimal("10")
    assert order.order_type is OrderType.MARKET
    assert order.time_in_force is TimeInForce.DAY
    assert order.strategy_id == "scripted_stub_6429"
    assert order.created_at == BASE
    assert order.idempotency_key  # non-empty, required by the contract
    assert order.signal_id is None
    assert order.limit_price is None
    assert order.trigger_price is None


def test_build_backtest_entry_order_intent_bearish_maps_to_sell() -> None:
    order = build_backtest_entry_order_intent(
        strategy_id="scripted_stub_6429",
        instrument_id=INSTRUMENT,
        direction=StrategyDirection.BEARISH,
        quantity=Decimal("5"),
        entry_timestamp=BASE,
        entry_index=0,
    )
    assert order.side is Side.SELL


def test_backtest_direction_to_side_rejects_neutral() -> None:
    with pytest.raises(ValueError, match="NEUTRAL"):
        backtest_direction_to_side(StrategyDirection.NEUTRAL)


def test_two_different_entry_indices_produce_different_idempotency_keys() -> None:
    order_a = build_backtest_entry_order_intent(
        strategy_id="scripted_stub_6429",
        instrument_id=INSTRUMENT,
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_timestamp=BASE,
        entry_index=0,
    )
    order_b = build_backtest_entry_order_intent(
        strategy_id="scripted_stub_6429",
        instrument_id=INSTRUMENT,
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_timestamp=BASE,
        entry_index=1,
    )
    assert order_a.idempotency_key != order_b.idempotency_key
    assert order_a.order_id != order_b.order_id


# =====================================================================
# Target 3 - BacktestPosition OPEN -> HELD -> CLOSED lifecycle +
# invariant.
# =====================================================================


def test_open_backtest_position_starts_open_full_remaining() -> None:
    pos = open_backtest_position(
        position_id="p1",
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        entry_timestamp=BASE,
    )
    assert pos.lifecycle_status is BacktestPositionLifecycleStatus.OPEN
    assert pos.original_quantity == Decimal("10")
    assert pos.remaining_quantity == Decimal("10")
    assert pos.exited_quantity == Decimal("0")
    assert pos.original_quantity == pos.exited_quantity + pos.remaining_quantity


def test_hold_transitions_open_to_held_without_changing_quantity() -> None:
    pos = open_backtest_position(
        position_id="p1",
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        entry_timestamp=BASE,
    )
    held = hold_backtest_position(pos)
    assert held.lifecycle_status is BacktestPositionLifecycleStatus.HELD
    assert held.remaining_quantity == Decimal("10")
    assert held.exited_quantity == Decimal("0")
    assert held.original_quantity == held.exited_quantity + held.remaining_quantity


def test_hold_is_idempotent_when_already_held() -> None:
    pos = open_backtest_position(
        position_id="p1",
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        entry_timestamp=BASE,
    )
    held_once = hold_backtest_position(pos)
    held_twice = hold_backtest_position(held_once)
    assert held_twice.lifecycle_status is BacktestPositionLifecycleStatus.HELD


def test_close_fully_exits_the_entire_remaining_quantity() -> None:
    pos = open_backtest_position(
        position_id="p1",
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        entry_timestamp=BASE,
    )
    held = hold_backtest_position(pos)
    closed = close_backtest_position(held)
    assert closed.lifecycle_status is BacktestPositionLifecycleStatus.CLOSED
    assert closed.remaining_quantity == Decimal("0")
    assert closed.exited_quantity == closed.original_quantity == Decimal("10")
    assert closed.original_quantity == closed.exited_quantity + closed.remaining_quantity


def test_close_directly_from_open_also_works_full_close_only() -> None:
    pos = open_backtest_position(
        position_id="p1",
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("7"),
        entry_price=Decimal("50"),
        entry_timestamp=BASE,
    )
    closed = close_backtest_position(pos)
    assert closed.lifecycle_status is BacktestPositionLifecycleStatus.CLOSED
    assert closed.exited_quantity == Decimal("7")
    assert closed.remaining_quantity == Decimal("0")


def test_cannot_hold_a_closed_position() -> None:
    pos = open_backtest_position(
        position_id="p1",
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        entry_timestamp=BASE,
    )
    closed = close_backtest_position(pos)
    with pytest.raises(ValueError, match="CLOSED"):
        hold_backtest_position(closed)


def test_cannot_close_an_already_closed_position() -> None:
    pos = open_backtest_position(
        position_id="p1",
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        entry_timestamp=BASE,
    )
    closed = close_backtest_position(pos)
    with pytest.raises(ValueError, match="already CLOSED"):
        close_backtest_position(closed)


def test_partial_remaining_quantity_while_open_violates_the_full_close_only_invariant() -> None:
    # Directly constructing an "OPEN but partially exited" BacktestPosition
    # must be rejected - the current engine has no partial-exit
    # capability, so this shape must never be representable as valid.
    from intraday.research.backtesting.position_lifecycle import BacktestPosition

    with pytest.raises(ValueError, match="exited_quantity must be 0"):
        BacktestPosition(
            position_id="p1",
            direction=StrategyDirection.BULLISH,
            original_quantity=Decimal("10"),
            remaining_quantity=Decimal("6"),  # implies exited_quantity == 4
            entry_price=Decimal("100"),
            entry_timestamp=BASE,
            lifecycle_status=BacktestPositionLifecycleStatus.OPEN,
        )


def test_closed_with_nonzero_remaining_violates_the_full_close_only_invariant() -> None:
    from intraday.research.backtesting.position_lifecycle import BacktestPosition

    with pytest.raises(ValueError, match="exited_quantity must equal original_quantity"):
        BacktestPosition(
            position_id="p1",
            direction=StrategyDirection.BULLISH,
            original_quantity=Decimal("10"),
            remaining_quantity=Decimal("3"),  # CLOSED must have remaining == 0
            entry_price=Decimal("100"),
            entry_timestamp=BASE,
            lifecycle_status=BacktestPositionLifecycleStatus.CLOSED,
        )
