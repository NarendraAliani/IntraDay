# tests/unit/research/test_checkpoint_64_32_position_lifecycle_wiring.py
#
# Checkpoint 64.32: focused tests proving the REAL canonical
# `position_lifecycle.BacktestPosition`/`BacktestPositionLifecycleStatus`
# (Checkpoint 64.29's previously-unwired adapter, still completely
# unmodified by this checkpoint) now genuinely reflects the real
# `run_backtest()` position state - `execution.OpenPosition.
# position_lifecycle` and `contracts.SimulatedTrade.position_lifecycle` -
# never a second, parallel lifecycle vocabulary. Mirrors the
# fixture/helper pattern already established by
# test_checkpoint_64_31_order_intent_wiring.py (copied locally, not
# imported - same "no cross-test-file coupling" discipline).
#
# Covers the checkpoint's own A-N list:
#   A. a newly accepted entry starts with canonical OPEN lifecycle state.
#   B. a position that remains open across bars has HELD lifecycle state.
#   C. a normally closed Backtest position results in CLOSED lifecycle
#      state.
#   D. the lifecycle state reflects actual existing engine state rather
#      than independently determining it (no fabricated HELD state when
#      the engine itself never held the position across a bar).
#   E. no lifecycle state is created for a rejected risk-gated entry.
#   F. the same canonical lifecycle representation is retained from
#      OpenPosition into the final SimulatedTrade (field continuity).
#   G. the canonical lifecycle type from position_lifecycle.py is
#      actually used (isinstance checks).
#   H. no second lifecycle vocabulary exists.
#   I. existing OrderIntent retention from 64.31 remains intact.
#   J. risk_limits=None preserves existing numerical Backtest results.
#   K. permissive risk limits preserve existing numerical Backtest
#      results.
#   L. existing exit behavior remains unchanged.
#   M. existing P&L remains unchanged.
#   N. the canonical position lifecycle source file remains unmodified
#      (not assertable via git diff from inside a test - a shape/smoke
#      check is included instead, reported separately alongside the
#      actual `git diff` evidence).
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderIntent
from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.research.backtesting import StrategyConfigurationValues, StrategyDirection
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.contracts import SimulatedTrade as _SimulatedTradeType
from intraday.research.backtesting.engine import run_backtest
from intraday.research.backtesting.position_lifecycle import (
    BacktestPosition,
    BacktestPositionLifecycleStatus,
)
from intraday.trading_engine.strategy_execution.contracts import StrategyParameterSchema

INSTRUMENT = "NSE:TESTCO"
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


@dataclass
class _StubSignal:
    direction: StrategyDirection


class _ScriptedStrategy:
    strategy_id = "scripted_stub_6432"
    display_name = "Scripted Stub 64.32"
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
        "strategy_id": "scripted_stub_6432",
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


# Held-across-bars scenario (same one 64.29/64.30/64.31 use): a 10-share
# BULLISH entry at bar 1's open (100), which survives bar 1 fully (no
# signal at index 1) before being reversed and closed at bar 3's open
# (105) - the position is open across bars 1 and 2 before closing, so it
# genuinely passes through HELD.
_CLOSES = ["100", "100", "105", "105", "110"]
_SIGNALS = {0: StrategyDirection.BULLISH, 2: StrategyDirection.BEARISH}

# Immediate-reversal scenario: BULLISH at bar 0, BEARISH already queued
# at bar 1 (the very next signal) - the position never survives a full
# extra bar before its reversal is detected, so it must close directly
# from OPEN, never fabricating an intermediate HELD.
_IMMEDIATE_CLOSES = ["100", "100", "95", "95"]
_IMMEDIATE_SIGNALS = {0: StrategyDirection.BULLISH, 1: StrategyDirection.BEARISH}

_PERMISSIVE_LIMITS = RiskLimits(
    max_intraday_loss=Decimal("100000"),
    max_position_size=Decimal("100"),
    max_per_trade_risk=Decimal("100000"),
)


def _run(risk_limits: RiskLimits | None, closes=None, signals=None, **config_overrides: object):
    closes = closes if closes is not None else _CLOSES
    signals = signals if signals is not None else _SIGNALS
    bars = _bars_from_closes(closes)
    strategy = _ScriptedStrategy(signals)
    config = _config(
        end=BASE + timedelta(minutes=len(closes) + 5),
        risk_limits=risk_limits,
        **config_overrides,
    )
    return run_backtest(
        bars,
        strategy,  # type: ignore[arg-type]
        StrategyConfigurationValues("scripted_stub_6432", "v1", "v1", "v1", {}),
        config,
        lambda field_id, bars_: (),
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )


# =====================================================================
# A. a newly accepted entry starts with canonical OPEN lifecycle state.
# =====================================================================


def test_a_newly_accepted_entry_starts_open(monkeypatch) -> None:
    import intraday.research.backtesting.engine as engine_module

    real_fn = engine_module.open_backtest_position
    captured: list[BacktestPosition] = []

    def _spy(**kwargs):
        result = real_fn(**kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(engine_module, "open_backtest_position", _spy)
    result = _run(risk_limits=None)
    assert len(result.trades) == 1
    assert len(captured) == 1
    assert captured[0].lifecycle_status is BacktestPositionLifecycleStatus.OPEN


# =====================================================================
# B. a position that remains open across bars has HELD lifecycle state.
# =====================================================================


def test_b_position_open_across_bars_reaches_held(monkeypatch) -> None:
    import intraday.research.backtesting.engine as engine_module

    real_fn = engine_module.hold_backtest_position
    captured: list[tuple[BacktestPositionLifecycleStatus, BacktestPosition]] = []

    def _spy(position):
        input_status = position.lifecycle_status
        result = real_fn(position)
        captured.append((input_status, result))
        return result

    monkeypatch.setattr(engine_module, "hold_backtest_position", _spy)
    result = _run(risk_limits=None)
    assert len(result.trades) == 1
    # The held-across-bars scenario transitions OPEN -> HELD exactly
    # once (bar index 2, the first bar strictly after the entry bar).
    assert len(captured) == 1
    input_status, returned = captured[0]
    assert input_status is BacktestPositionLifecycleStatus.OPEN
    assert returned.lifecycle_status is BacktestPositionLifecycleStatus.HELD


# =====================================================================
# C. a normally closed Backtest position results in CLOSED lifecycle
#    state.
# =====================================================================


def test_c_closed_position_has_closed_lifecycle_state() -> None:
    result = _run(risk_limits=None)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.position_lifecycle is not None
    assert trade.position_lifecycle.lifecycle_status is BacktestPositionLifecycleStatus.CLOSED


# =====================================================================
# D. the lifecycle state reflects actual existing engine state rather
#    than independently determining it - no fabricated HELD state when
#    the engine itself never held the position across a bar.
# =====================================================================


def test_d_lifecycle_reflects_engine_state_not_independent_decision(monkeypatch) -> None:
    import intraday.research.backtesting.engine as engine_module

    real_fn = engine_module.hold_backtest_position
    calls: list[object] = []

    def _spy(position):
        calls.append(position)
        return real_fn(position)

    monkeypatch.setattr(engine_module, "hold_backtest_position", _spy)
    result = _run(risk_limits=None, closes=_IMMEDIATE_CLOSES, signals=_IMMEDIATE_SIGNALS)
    assert len(result.trades) == 1
    trade = result.trades[0]
    # Closed directly - the engine itself never let this position
    # survive a bar past its own entry, so `hold_backtest_position()`
    # must never have been invoked, and the final state is CLOSED
    # (reached from OPEN, not from a fabricated HELD).
    assert len(calls) == 0
    assert trade.position_lifecycle is not None
    assert trade.position_lifecycle.lifecycle_status is BacktestPositionLifecycleStatus.CLOSED


# =====================================================================
# E. no lifecycle state is created for a rejected risk-gated entry.
# =====================================================================


def test_e_no_lifecycle_state_for_rejected_entry(monkeypatch) -> None:
    import intraday.research.backtesting.engine as engine_module

    real_fn = engine_module.open_backtest_position
    calls: list[object] = []

    def _spy(**kwargs):
        calls.append(kwargs)
        return real_fn(**kwargs)

    monkeypatch.setattr(engine_module, "open_backtest_position", _spy)
    restrictive = RiskLimits(
        max_intraday_loss=Decimal("100000"),
        max_position_size=Decimal("1"),
        max_per_trade_risk=Decimal("100000"),
    )
    result = _run(risk_limits=restrictive)
    assert result.trades == ()
    assert result.validation.risk_rejected_trades == 2
    assert len(calls) == 0


# =====================================================================
# F. the same canonical lifecycle representation is retained from
#    OpenPosition into the final SimulatedTrade (field continuity -
#    BacktestPosition is frozen, so a fresh CLOSED instance is
#    necessarily constructed, but it must originate from the SAME
#    OpenPosition.position_lifecycle, never an independent one).
# =====================================================================


def test_f_lifecycle_representation_retained_from_open_position(monkeypatch) -> None:
    import intraday.research.backtesting.engine as engine_module

    real_fn = engine_module.close_backtest_position
    captured: list[BacktestPosition] = []

    def _spy(position):
        captured.append(position)
        return real_fn(position)

    monkeypatch.setattr(engine_module, "close_backtest_position", _spy)
    result = _run(risk_limits=None)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert len(captured) == 1
    open_side = captured[0]
    closed_side = trade.position_lifecycle
    assert closed_side is not None
    # Field continuity proves the CLOSED snapshot originates from the
    # SAME position, not an independently fabricated one.
    assert open_side.position_id == closed_side.position_id
    assert open_side.direction == closed_side.direction
    assert open_side.original_quantity == closed_side.original_quantity
    assert open_side.entry_price == closed_side.entry_price
    assert open_side.entry_timestamp == closed_side.entry_timestamp
    # `BacktestPosition` is a frozen dataclass - `close_backtest_position`
    # necessarily returns a NEW object, so whole-object `is` identity
    # does not and should not hold here (see this module's own
    # docstring). The honest continuity proof is field equality above,
    # plus the fact `close_backtest_position` was invoked exactly once
    # with exactly the object that had been carried on
    # `OpenPosition.position_lifecycle`.
    assert open_side is not closed_side
    # The lifecycle_status ENUM MEMBER, by contrast, genuinely is a
    # singleton - `is` identity is meaningful and holds there.
    assert closed_side.lifecycle_status is BacktestPositionLifecycleStatus.CLOSED


# =====================================================================
# G. the canonical lifecycle type from position_lifecycle.py is
#    actually used.
# =====================================================================


def test_g_canonical_lifecycle_type_is_actually_used() -> None:
    result = _run(risk_limits=None)
    trade = result.trades[0]
    assert trade.position_lifecycle is not None
    assert isinstance(trade.position_lifecycle, BacktestPosition)
    assert isinstance(trade.position_lifecycle.lifecycle_status, BacktestPositionLifecycleStatus)


# =====================================================================
# H. no second lifecycle vocabulary exists.
# =====================================================================


def test_h_no_second_lifecycle_vocabulary_exists() -> None:
    from intraday.research.backtesting import contracts as backtest_contracts
    from intraday.research.backtesting import execution as backtest_execution

    for forbidden in (
        "BacktestPositionStatus",
        "PositionState",
        "PositionLifecycleState",
        "EnginePositionStatus",
    ):
        assert not hasattr(backtest_contracts, forbidden)
        assert not hasattr(backtest_execution, forbidden)
    assert backtest_contracts.BacktestPosition is BacktestPosition
    assert backtest_execution.BacktestPosition is BacktestPosition


# =====================================================================
# I. existing OrderIntent retention from 64.31 remains intact.
# =====================================================================


def test_i_order_intent_retention_from_64_31_remains_intact() -> None:
    result = _run(risk_limits=None)
    trade = result.trades[0]
    assert trade.order_intent is not None
    assert isinstance(trade.order_intent, OrderIntent)
    assert trade.order_intent.quantity == trade.quantity


# =====================================================================
# J. risk_limits=None preserves existing numerical Backtest results.
# =====================================================================


def test_j_risk_limits_none_preserves_legacy_numerical_results() -> None:
    result = _run(risk_limits=None)
    trade = result.trades[0]
    assert trade.quantity == Decimal("10")
    assert trade.entry_price == Decimal("100")
    assert trade.exit_price == Decimal("105")
    assert trade.gross_pnl == Decimal("50")
    assert trade.net_pnl == Decimal("50")
    assert trade.reason == "signal_reversal"


# =====================================================================
# K. permissive risk limits preserve existing numerical Backtest
#    results.
# =====================================================================


def test_k_permissive_risk_limits_preserve_legacy_numerical_results() -> None:
    legacy = _run(risk_limits=None)
    gated = _run(risk_limits=_PERMISSIVE_LIMITS)
    lt, gt = legacy.trades[0], gated.trades[0]
    assert lt.entry_price == gt.entry_price
    assert lt.exit_price == gt.exit_price
    assert lt.quantity == gt.quantity
    assert lt.reason == gt.reason
    assert lt.gross_pnl == gt.gross_pnl
    assert lt.net_pnl == gt.net_pnl
    assert legacy.equity_curve == gated.equity_curve
    assert legacy.metrics == gated.metrics
    assert lt.position_lifecycle is not None
    assert gt.position_lifecycle is not None
    assert lt.position_lifecycle.lifecycle_status is gt.position_lifecycle.lifecycle_status


# =====================================================================
# L. existing exit behavior remains unchanged.
# =====================================================================


def test_l_exit_behavior_unchanged() -> None:
    result = _run(risk_limits=None)
    trade = result.trades[0]
    assert trade.reason == "signal_reversal"
    assert trade.exit_timestamp == BASE + timedelta(minutes=3)
    assert trade.exit_price == Decimal("105")


# =====================================================================
# M. existing P&L remains unchanged.
# =====================================================================


def test_m_pnl_unchanged() -> None:
    result = _run(risk_limits=None)
    trade = result.trades[0]
    assert trade.gross_pnl == Decimal("50")
    assert trade.costs == Decimal("0")
    assert trade.net_pnl == Decimal("50")


# =====================================================================
# N. the canonical position lifecycle source file remains unmodified -
#    not assertable via git diff from inside a test (reported
#    separately); this is a shape/smoke check that the canonical
#    module's own vocabulary and function signatures are untouched.
# =====================================================================


def test_n_canonical_lifecycle_source_shape_is_untouched() -> None:
    from intraday.research.backtesting import position_lifecycle as pl

    assert {member.value for member in BacktestPositionLifecycleStatus} == {
        "OPEN",
        "HELD",
        "CLOSED",
    }
    field_names = set(BacktestPosition.__dataclass_fields__)
    assert field_names == {
        "position_id",
        "direction",
        "original_quantity",
        "remaining_quantity",
        "entry_price",
        "entry_timestamp",
        "lifecycle_status",
    }
    assert hasattr(pl, "open_backtest_position")
    assert hasattr(pl, "hold_backtest_position")
    assert hasattr(pl, "close_backtest_position")
    assert _SimulatedTradeType is not None  # import-sanity smoke check
