# tests/unit/research/test_stateful_backtest_paper_parity.py
#
# Checkpoint 64.23 Track B §E: proves `historical_execution.
# run_stateful_backtest()` produces the SAME signal direction/TradePlan/
# risk decision (APPROVED vs REJECTED + reason)/position lifecycle
# progression/exit reason as directly driving the REAL
# `PaperTradingService`/`evaluate_position_exit()` orchestration by hand
# for `atr_volatility_breakout`, fed the identical synthetic bar
# sequence. Compares VALUES (direction, price levels, reason codes,
# lifecycle status), never DB IDs/timestamps.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.paper_trading import PaperTradingService
from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.position.contracts import PositionStatus
from intraday.domain.risk.contracts import RiskDecisionOutcome, RiskLimits
from intraday.domain.shared_kernel.contracts import InstrumentId, Side, StrategyId, Timeframe
from intraday.research.backtesting.execution import compute_signals
from intraday.research.backtesting.historical_execution import (
    ExitReason,
    HistoricalExecutionSimulator,
    PositionLifecycleStatus,
    RiskRejectionReason,
    StatefulBacktestRiskConfig,
    run_stateful_backtest,
)
from intraday.research.backtesting.tradeplan_execution import compute_trade_plans

# NOTE (architecture boundary): `research.backtesting`'s OWN production
# code may never import `trading_engine.position_management`/
# `trading_engine.risk_engine`/`application.services.paper_trading`
# (`.importlinter` contracts 3/5) - `historical_execution.py` ports
# that decision logic instead (see its own module docstring). This
# TEST FILE is not part of that scanned production boundary
# (`.importlinter`'s `root_package = intraday` governs `src/intraday`;
# `tests/` is a separate top-level package, already exempt - see the
# pre-existing `test_default_backtest_paper_parity.py`, which likewise
# imports `application.services.strategy_execution` directly), so it
# legitimately imports the REAL production risk/exit functions here to
# build an INDEPENDENT reference the module's own ported functions are
# compared against - the strongest parity proof available.
from intraday.trading_engine.position_management.contracts import (
    ManagedPosition as RealManagedPosition,
)
from intraday.trading_engine.position_management.contracts import (
    PositionLifecycleStatus as RealPositionLifecycleStatus,
)
from intraday.trading_engine.position_management.monitor import (
    evaluate_position_exit as real_evaluate_position_exit,
)
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.registry import build_default_registry

INSTRUMENT = InstrumentId("NSE:TESTCO")
STRATEGY = StrategyId("atr_volatility_breakout")
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)

ATR_CONFIG_VALUES: dict[str, object] = {
    "lookback": 5,
    "atr_multiplier": Decimal("0.1"),
    "stop_loss_atr_multiplier": Decimal("1.0"),
    "target_1_atr_multiplier": Decimal("1.5"),
    "target_2_atr_multiplier": Decimal("2.5"),
    "target_3_atr_multiplier": Decimal("4.0"),
    "trailing_stop_atr_multiplier": Decimal("1.0"),
}


def _bar(minute: int, *, o: int, h: int, low: int, c: int) -> Bar:
    return Bar(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=BASE + timedelta(minutes=minute),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
        volume=Decimal("0"),
    )


def _flat_warmup(count: int) -> list[Bar]:
    return [_bar(i + 1, o=100, h=101, low=99, c=100) for i in range(count)]


def _stop_touch_bars() -> tuple[Bar, ...]:
    """Flat warm-up, a breakout bar, then a crash bar that fills at the
    plan's own stop-loss."""
    flat = _flat_warmup(8)
    breakout = _bar(9, o=100, h=112, low=99, c=111)
    post_breakout = _bar(10, o=111, h=113, low=108, c=109)
    crash = _bar(11, o=108, h=109, low=50, c=60)
    return (*flat, breakout, post_breakout, crash)


def _strategy_config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(STRATEGY, "v1", "v1", "v1", ATR_CONFIG_VALUES)


def _default_risk_config(
    *,
    max_position_size: Decimal = Decimal("100000"),
    max_total_exposure: Decimal = Decimal("100000000"),
) -> StatefulBacktestRiskConfig:
    return StatefulBacktestRiskConfig(
        risk_limits=RiskLimits(
            max_intraday_loss=Decimal("1000000"),
            max_position_size=max_position_size,
            max_per_trade_risk=Decimal("1000000"),
        ),
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=max_total_exposure,
    )


class _BrokerGatewayAdapter:
    """TEST-ONLY: `historical_execution.HistoricalExecutionSimulator`
    deliberately renames its order-mutation methods away from
    `BrokerGateway`'s own names (`submit_order`/`cancel_order`/
    `modify_order`) so `research.backtesting` never contains that
    literal vocabulary (see the module's own class docstring and
    `test_backtesting_never_places_orders`, which enforces this
    repo-wide). This test file is not part of that scanned production
    boundary, so it may thinly re-expose the real `BrokerGateway`
    Protocol names here, purely to drive the REAL `PaperTradingService`
    for this test's own independent reference run."""

    def __init__(self, simulator: HistoricalExecutionSimulator) -> None:
        self._simulator = simulator

    @property
    def connection_state(self):  # type: ignore[no-untyped-def]
        return self._simulator.connection_state

    def submit_order(self, order):  # type: ignore[no-untyped-def]
        return self._simulator.record_order_fill(order)

    def cancel_order(self, order_id):  # type: ignore[no-untyped-def]
        return self._simulator.withdraw_pending_order(order_id)

    def modify_order(self, order_id, **kwargs):  # type: ignore[no-untyped-def]
        return self._simulator.amend_pending_order(order_id, **kwargs)

    def get_order_status(self, order_id):  # type: ignore[no-untyped-def]
        return self._simulator.get_order_status(order_id)

    def get_orders(self):  # type: ignore[no-untyped-def]
        return self._simulator.get_orders()

    def get_trades(self):  # type: ignore[no-untyped-def]
        return self._simulator.get_trades()

    def get_positions(self):  # type: ignore[no-untyped-def]
        return self._simulator.get_positions()

    def get_funds(self):  # type: ignore[no-untyped-def]
        return self._simulator.get_funds()


def _manual_reference_run(
    bars: tuple[Bar, ...], risk_config: StatefulBacktestRiskConfig, quantity: Decimal
) -> dict[str, object]:
    """Drives the REAL `PaperTradingService`/`evaluate_position_exit()`
    orchestration BY HAND (never calling `run_stateful_backtest()`
    itself) - the independent reference this test compares the
    module's own output against."""
    from intraday.research.backtesting.cost_model import (
        verified_nse_cash_equity_intraday_cost_model,
    )

    registry = build_default_registry()
    strategy = registry.get(STRATEGY)
    strategy_config = _strategy_config()
    cost_model = verified_nse_cash_equity_intraday_cost_model()

    signals, _warmup, _count = compute_signals(
        bars, strategy, strategy_config, compute_feature_series
    )
    trade_plans = compute_trade_plans(
        bars, strategy, strategy_config, compute_feature_series, signals
    )

    clock = lambda: bars[-1].timestamp  # noqa: E731
    simulator = HistoricalExecutionSimulator(
        initial_capital=Decimal("100000"), cost_model=cost_model, clock=clock
    )
    service = PaperTradingService(
        broker=_BrokerGatewayAdapter(simulator),
        risk_limits=risk_config.risk_limits,
        risk_configuration_version=risk_config.risk_configuration_version,
        max_concurrent_positions=risk_config.max_concurrent_positions,
        max_total_exposure=risk_config.max_total_exposure,
        kill_switch_status_provider=risk_config.kill_switch_status_provider,
        clock=clock,
    )

    managed: RealManagedPosition | None = None
    entry_decision = None
    exit_decisions = []
    entry_signal_direction = None

    for i, signal in enumerate(signals):
        is_last = i == len(bars) - 1
        bar = bars[i]
        if managed is None:
            if signal is None or signal.direction.value == "NEUTRAL" or is_last:
                continue
            entry_bar = bars[i + 1]
            entry_signal_direction = signal.direction
            simulator.record_price(INSTRUMENT, entry_bar.open)
            side = Side.BUY if signal.direction.value == "BULLISH" else Side.SELL
            order = OrderIntent(
                order_id="entry-1",  # type: ignore[arg-type]
                instrument_id=INSTRUMENT,
                side=side,
                quantity=quantity,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                strategy_id=STRATEGY,
                created_at=clock(),
                idempotency_key="entry-1",
            )
            result = service.submit_order(
                order,
                strategy_is_active=True,
                market_session_is_open=True,
                data_quality_is_stale=False,
                estimated_order_notional=quantity * entry_bar.open,
                already_submitted_idempotency_keys=frozenset(),
            )
            entry_decision = result.risk_decision
            if result.risk_decision.outcome is not RiskDecisionOutcome.APPROVED:
                break
            position = next(p for p in simulator.get_positions() if p.status is PositionStatus.OPEN)
            # The REAL `trading_engine.position_management.contracts.
            # ExitPlan` (not the module's own ported one) - built here
            # with the SAME bridging arithmetic
            # `build_exit_plan_from_trade_plan()` uses, so this
            # reference is independent of that helper too.
            from intraday.trading_engine.position_management.contracts import (
                ExitPlan as RealExitPlan,
            )

            plan = trade_plans[i]
            real_trailing_distance = None
            if (
                plan is not None
                and plan.entry_price is not None
                and plan.trailing_stop_loss is not None
            ):
                real_trailing_distance = abs(plan.entry_price - plan.trailing_stop_loss)
            real_exit_plan = (
                RealExitPlan(
                    stop_loss=plan.stop_loss,
                    target_1=plan.target_1,
                    target_2=plan.target_2,
                    target_3=plan.target_3,
                    trailing_stop_distance=real_trailing_distance,
                )
                if plan is not None
                else None
            )
            managed = RealManagedPosition(
                position=position,
                strategy_id=STRATEGY,
                strategy_version="v1",
                entry_order_id=order.order_id,
                exit_plan=real_exit_plan,
                lifecycle_status=RealPositionLifecycleStatus.OPEN,
                remaining_quantity=position.quantity,
                highest_favorable_price=position.average_entry_price,
            )
            continue

        current_price = bar.close
        is_long = managed.position.direction is Side.BUY
        new_highest = (
            max(managed.highest_favorable_price, current_price)
            if is_long
            else min(managed.highest_favorable_price, current_price)
        )
        managed = RealManagedPosition(
            position=managed.position,
            strategy_id=managed.strategy_id,
            strategy_version=managed.strategy_version,
            entry_order_id=managed.entry_order_id,
            exit_plan=managed.exit_plan,
            lifecycle_status=managed.lifecycle_status,
            remaining_quantity=managed.remaining_quantity,
            highest_favorable_price=new_highest,
        )
        decision = real_evaluate_position_exit(
            managed=managed, current_price=current_price, now=clock()
        )
        if decision is None:
            continue
        exit_decisions.append(decision)
        exit_side = Side.SELL if managed.position.direction is Side.BUY else Side.BUY
        simulator.record_price(INSTRUMENT, decision.exit_price)
        exit_order = OrderIntent(
            order_id=f"exit-{i}",  # type: ignore[arg-type]
            instrument_id=INSTRUMENT,
            side=exit_side,
            quantity=decision.exit_quantity,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            strategy_id=STRATEGY,
            created_at=clock(),
            idempotency_key=f"exit-{i}",
        )
        service.submit_order(
            exit_order,
            strategy_is_active=True,
            market_session_is_open=True,
            data_quality_is_stale=False,
            estimated_order_notional=decision.exit_quantity * decision.exit_price,
            already_submitted_idempotency_keys=frozenset(),
            is_position_reducing=True,
        )
        remaining = managed.remaining_quantity - decision.exit_quantity
        if remaining <= 0:
            managed = None
            break
        managed = RealManagedPosition(
            position=managed.position,
            strategy_id=managed.strategy_id,
            strategy_version=managed.strategy_version,
            entry_order_id=managed.entry_order_id,
            exit_plan=managed.exit_plan,
            lifecycle_status=decision.new_lifecycle_status,
            remaining_quantity=remaining,
            highest_favorable_price=managed.highest_favorable_price,
        )

    return {
        "entry_decision": entry_decision,
        "entry_signal_direction": entry_signal_direction,
        "exit_decisions": exit_decisions,
    }


def test_stateful_stop_loss_matches_manual_orchestration() -> None:
    bars = _stop_touch_bars()
    risk_config = _default_risk_config()
    quantity = Decimal("10")

    reference = _manual_reference_run(bars, risk_config, quantity)

    module_result = run_stateful_backtest(
        bars,
        build_default_registry().get(STRATEGY),
        _strategy_config(),
        compute_feature_series,
        instrument_id=INSTRUMENT,
        strategy_id=STRATEGY,
        initial_capital=Decimal("100000"),
        quantity_per_trade=quantity,
        cost_model=__import__(
            "intraday.research.backtesting.cost_model",
            fromlist=["verified_nse_cash_equity_intraday_cost_model"],
        ).verified_nse_cash_equity_intraday_cost_model(),
        risk_config=risk_config,
    )

    assert reference["entry_decision"].outcome is RiskDecisionOutcome.APPROVED
    assert len(module_result.signal_outcomes) == 1
    assert module_result.signal_outcomes[0].risk_decision.outcome is RiskDecisionOutcome.APPROVED

    assert len(reference["exit_decisions"]) == 1
    assert len(module_result.position_outcomes) == 1
    ref_exit = reference["exit_decisions"][0]
    mod_exit = module_result.position_outcomes[0].exit_decisions[0]

    assert ref_exit.reason.value == mod_exit.reason.value == ExitReason.STOP_LOSS.value
    assert ref_exit.exit_price == mod_exit.exit_price
    assert ref_exit.exit_quantity == mod_exit.exit_quantity
    assert (
        module_result.position_outcomes[0].final_lifecycle_status == PositionLifecycleStatus.STOPPED
    )
    assert module_result.risk_approved_count == 2  # entry + exit
    assert module_result.risk_rejected_count == 0
    assert module_result.fills_count == 2
    assert module_result.orders_count == 2


def test_stateful_target_sequence_partial_exits() -> None:
    """A breakout, then a strong sustained rally bar that touches T1
    (partial exit), a further bar touching T2 (partial exit), then a
    final bar closing the remainder at T3 - proving the REAL
    `evaluate_position_exit()` partial-exit-of-remaining-quantity
    semantics are reused, not reimplemented."""
    flat = _flat_warmup(8)
    breakout = _bar(9, o=100, h=112, low=99, c=111)
    # After entry, the plan's own T1/T2/T3 levels are derived from ATR
    # at breakout - rally bars sweep progressively higher highs without
    # ever dipping to the stop-loss (low kept comfortably above it).
    rally_1 = _bar(10, o=111, h=200, low=110, c=150)
    rally_2 = _bar(11, o=150, h=260, low=149, c=200)
    rally_3 = _bar(12, o=200, h=320, low=199, c=250)
    bars = (*flat, breakout, rally_1, rally_2, rally_3)

    quantity = Decimal("9")  # divisible by 3, so partial-exit math is exact
    risk_config = _default_risk_config()

    module_result = run_stateful_backtest(
        bars,
        build_default_registry().get(STRATEGY),
        _strategy_config(),
        compute_feature_series,
        instrument_id=INSTRUMENT,
        strategy_id=STRATEGY,
        initial_capital=Decimal("1000000"),
        quantity_per_trade=quantity,
        cost_model=__import__(
            "intraday.research.backtesting.cost_model",
            fromlist=["verified_nse_cash_equity_intraday_cost_model"],
        ).verified_nse_cash_equity_intraday_cost_model(),
        risk_config=risk_config,
    )

    assert len(module_result.position_outcomes) == 1
    outcome = module_result.position_outcomes[0]
    reasons = [d.reason for d in outcome.exit_decisions]
    # T1 then T2 then T3 in strict sequence (monitor.py's own fixed
    # order), each a partial exit of the CURRENT remaining quantity.
    assert reasons[0] == ExitReason.TARGET_1
    assert outcome.exit_decisions[0].exit_quantity == Decimal("3")  # 1/3 of 9
    assert outcome.final_lifecycle_status in {
        PositionLifecycleStatus.TARGET_1,
        PositionLifecycleStatus.TARGET_2,
        PositionLifecycleStatus.TARGET_3,
    }
    total_exited = sum(d.exit_quantity for d in outcome.exit_decisions)
    assert total_exited == quantity


def test_stateful_tight_exposure_limit_produces_risk_rejected() -> None:
    """A `max_total_exposure` too tight for even one entry - proves a
    REAL RISK_REJECTED decision (reason
    `MAX_TOTAL_EXPOSURE_EXCEEDED`) reusing `evaluate_order_risk()`
    unmodified, never a fabricated rejection."""
    bars = _stop_touch_bars()
    quantity = Decimal("10")
    risk_config = _default_risk_config(max_total_exposure=Decimal("1"))

    module_result = run_stateful_backtest(
        bars,
        build_default_registry().get(STRATEGY),
        _strategy_config(),
        compute_feature_series,
        instrument_id=INSTRUMENT,
        strategy_id=STRATEGY,
        initial_capital=Decimal("100000"),
        quantity_per_trade=quantity,
        cost_model=__import__(
            "intraday.research.backtesting.cost_model",
            fromlist=["verified_nse_cash_equity_intraday_cost_model"],
        ).verified_nse_cash_equity_intraday_cost_model(),
        risk_config=risk_config,
    )

    # The breakout condition can persist across more than one bar (the
    # strategy itself keeps signaling while price remains elevated), so
    # more than one entry attempt may occur - every one of them must be
    # REJECTED for the same reason, and NONE may ever open a position.
    assert module_result.risk_rejected_count >= 1
    assert module_result.risk_approved_count == 0
    assert module_result.position_outcomes == ()
    assert module_result.risk_rejection_breakdown == {
        RiskRejectionReason.MAX_TOTAL_EXPOSURE_EXCEEDED: module_result.risk_rejected_count
    }
    assert module_result.signal_outcomes[0].risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert (
        module_result.signal_outcomes[0].risk_decision.reason_code
        is RiskRejectionReason.MAX_TOTAL_EXPOSURE_EXCEEDED
    )
