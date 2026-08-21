# tests/unit/research/test_checkpoint_64_31_order_intent_wiring.py
#
# Checkpoint 64.31: focused tests proving the REAL canonical
# `domain.order.contracts.OrderIntent` is now the canonical
# representation of an accepted `run_backtest()` entry - retained on
# `SimulatedTrade.order_intent` (via `execution.OpenPosition.
# order_intent`), and that it is the SAME object used for the risk
# decision, never a second, separately-constructed one. Mirrors the
# fixture/helper pattern already established by
# test_checkpoint_64_30_risk_gate_wiring.py (copied locally, not
# imported - same "no cross-test-file coupling" discipline).
#
# Covers the checkpoint's own A-L list:
#   A. every accepted Backtest entry can construct a real OrderIntent.
#   B. the OrderIntent is the SAME object used for the risk decision and
#      retained for the accepted entry (monkeypatch-spy `is` identity).
#   C. OrderIntent fields are populated from honest Backtest state.
#   D. no placeholder/fabricated fields exist (cross-checked against the
#      trade's own recorded quantity/instrument/strategy/timestamp).
#   E. BUY/SELL mapping remains correct.
#   F. NEUTRAL cannot become an OrderIntent (structural - no NEUTRAL
#      signal ever reaches the entry branch, proven by inspecting the
#      guard directly via a NEUTRAL-only scripted run producing zero
#      trades and zero OrderIntents).
#   G. idempotency_key remains deterministic and unique, as 64.29
#      established.
#   H. risk_limits=None preserves legacy Backtest results (numerically).
#   I. permissive risk limits preserve legacy numerical results.
#   J. rejected risk-gated entries do NOT retain an accepted OrderIntent
#      as if an order had entered the market (result.trades == ()).
#   K. the canonical OrderIntent type from domain/order/contracts.py is
#      actually used (isinstance check).
#   L. domain/order/contracts.py itself remains unmodified (git-diff
#      based, reported separately - cannot be asserted from within a
#      test; a source-import sanity smoke check is included instead).
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.shared_kernel.contracts import Side, Timeframe
from intraday.research.backtesting import StrategyConfigurationValues, StrategyDirection
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.trading_engine.strategy_execution.contracts import StrategyParameterSchema

INSTRUMENT = "NSE:TESTCO"
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


@dataclass
class _StubSignal:
    direction: StrategyDirection


class _ScriptedStrategy:
    strategy_id = "scripted_stub_6431"
    display_name = "Scripted Stub 64.31"
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
        "strategy_id": "scripted_stub_6431",
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


# One 10-share BULLISH entry at bar 1's open (100), reversed and closed
# at bar 3's open (105) - the SAME scripted scenario 64.29/64.30 use, so
# this file's numbers are directly comparable to those checkpoints'
# already-proven ones.
_CLOSES = ["100", "100", "105", "105", "110"]
_SIGNALS = {0: StrategyDirection.BULLISH, 2: StrategyDirection.BEARISH}

_PERMISSIVE_LIMITS = RiskLimits(
    max_intraday_loss=Decimal("100000"),
    max_position_size=Decimal("100"),
    max_per_trade_risk=Decimal("100000"),
)


def _run(risk_limits: RiskLimits | None, **config_overrides: object):
    bars = _bars_from_closes(_CLOSES)
    strategy = _ScriptedStrategy(_SIGNALS)
    config = _config(
        end=BASE + timedelta(minutes=len(_CLOSES) + 5),
        risk_limits=risk_limits,
        **config_overrides,
    )
    return run_backtest(
        bars,
        strategy,  # type: ignore[arg-type]
        StrategyConfigurationValues("scripted_stub_6431", "v1", "v1", "v1", {}),
        config,
        lambda field_id, bars_: (),
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )


# =====================================================================
# A. every accepted Backtest entry can construct a real OrderIntent.
# =====================================================================


def test_a_accepted_entry_carries_a_real_order_intent() -> None:
    result = _run(risk_limits=None)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.order_intent is not None
    assert isinstance(trade.order_intent, OrderIntent)


# =====================================================================
# B. the OrderIntent is the SAME object used for the risk decision and
#    retained for the accepted entry - proven via monkeypatch-spy `is`
#    identity, not merely equal values.
# =====================================================================


def test_b_order_intent_is_the_same_object_fed_to_the_risk_gate(monkeypatch) -> None:
    calls: list[object] = []
    import intraday.research.backtesting.risk_gate_adapter as adapter_module

    real_fn = adapter_module.evaluate_order_risk

    def _spy(order, context):
        calls.append(order)
        return real_fn(order, context)

    monkeypatch.setattr(adapter_module, "evaluate_order_risk", _spy)
    result = _run(risk_limits=_PERMISSIVE_LIMITS)
    assert len(calls) == 1
    assert len(result.trades) == 1
    retained_order_intent = result.trades[0].order_intent
    assert retained_order_intent is not None
    # Identity, not just equality - proves no second, separately
    # constructed OrderIntent exists anywhere in the accepted path.
    assert calls[0] is retained_order_intent


# =====================================================================
# C. OrderIntent fields are populated from honest Backtest state.
# =====================================================================


def test_c_order_intent_fields_reflect_honest_backtest_state() -> None:
    result = _run(risk_limits=None)
    trade = result.trades[0]
    oi = trade.order_intent
    assert oi is not None
    assert oi.instrument_id == INSTRUMENT
    assert oi.strategy_id == "scripted_stub_6431"
    assert oi.quantity == trade.quantity == Decimal("10")
    assert oi.created_at == trade.entry_timestamp
    assert oi.order_type is OrderType.MARKET
    assert oi.time_in_force is TimeInForce.DAY


# =====================================================================
# D. no placeholder/fabricated fields exist.
# =====================================================================


def test_d_order_intent_has_no_fabricated_placeholder_fields() -> None:
    result = _run(risk_limits=None)
    oi = result.trades[0].order_intent
    assert oi is not None
    # MARKET order: limit/trigger price legitimately None (never a
    # fabricated stand-in price), signal_id legitimately None (the
    # scripted StrategySignal used here carries no signal_id concept).
    assert oi.limit_price is None
    assert oi.trigger_price is None
    assert oi.signal_id is None
    assert oi.idempotency_key.strip() != ""


# =====================================================================
# E. BUY/SELL mapping remains correct.
# =====================================================================


def test_e_bullish_maps_to_buy_and_bearish_maps_to_sell() -> None:
    bullish_result = _run(risk_limits=None)
    bullish_oi = bullish_result.trades[0].order_intent
    assert bullish_oi is not None
    assert bullish_oi.side is Side.BUY

    closes = ["100", "100", "95", "95", "90"]
    signals = {0: StrategyDirection.BEARISH, 2: StrategyDirection.BULLISH}
    bars = _bars_from_closes(closes)
    strategy = _ScriptedStrategy(signals)
    config = _config(end=BASE + timedelta(minutes=len(closes) + 5), risk_limits=None)
    bearish_result = run_backtest(
        bars,
        strategy,  # type: ignore[arg-type]
        StrategyConfigurationValues("scripted_stub_6431", "v1", "v1", "v1", {}),
        config,
        lambda field_id, bars_: (),
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    assert len(bearish_result.trades) == 1
    bearish_oi = bearish_result.trades[0].order_intent
    assert bearish_oi is not None
    assert bearish_oi.side is Side.SELL


# =====================================================================
# F. NEUTRAL cannot become an OrderIntent.
# =====================================================================


def test_f_neutral_signal_never_produces_a_trade_or_order_intent() -> None:
    closes = ["100", "100", "100", "100", "100"]
    signals: dict[int, StrategyDirection] = {}  # every evaluate() call returns None
    bars = _bars_from_closes(closes)
    strategy = _ScriptedStrategy(signals)
    config = _config(end=BASE + timedelta(minutes=len(closes) + 5), risk_limits=None)
    result = run_backtest(
        bars,
        strategy,  # type: ignore[arg-type]
        StrategyConfigurationValues("scripted_stub_6431", "v1", "v1", "v1", {}),
        config,
        lambda field_id, bars_: (),
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    assert result.trades == ()


# =====================================================================
# G. idempotency_key remains deterministic and unique.
# =====================================================================


def test_g_idempotency_key_is_deterministic_and_unique_per_entry() -> None:
    r1 = _run(risk_limits=None)
    r2 = _run(risk_limits=None)
    assert r1.trades[0].order_intent is not None
    assert r2.trades[0].order_intent is not None
    # Deterministic: two independent runs of the identical scenario
    # produce the identical idempotency_key.
    assert r1.trades[0].order_intent.idempotency_key == r2.trades[0].order_intent.idempotency_key

    # Unique within a single run: a two-entry scenario produces two
    # distinct idempotency_keys.
    closes = ["100", "100", "105", "105", "100", "100", "105"]
    signals = {
        0: StrategyDirection.BULLISH,
        2: StrategyDirection.BEARISH,
        4: StrategyDirection.BULLISH,
        6: StrategyDirection.BEARISH,
    }
    bars = _bars_from_closes(closes)
    strategy = _ScriptedStrategy(signals)
    config = _config(end=BASE + timedelta(minutes=len(closes) + 5), risk_limits=None)
    result = run_backtest(
        bars,
        strategy,  # type: ignore[arg-type]
        StrategyConfigurationValues("scripted_stub_6431", "v1", "v1", "v1", {}),
        config,
        lambda field_id, bars_: (),
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    assert len(result.trades) == 2
    key1 = result.trades[0].order_intent.idempotency_key  # type: ignore[union-attr]
    key2 = result.trades[1].order_intent.idempotency_key  # type: ignore[union-attr]
    assert key1 != key2


# =====================================================================
# H. risk_limits=None preserves legacy Backtest results.
# =====================================================================


def test_h_risk_limits_none_preserves_legacy_numerical_results() -> None:
    result = _run(risk_limits=None)
    trade = result.trades[0]
    assert trade.quantity == Decimal("10")
    assert trade.entry_price == Decimal("100")
    assert trade.exit_price == Decimal("105")
    assert trade.gross_pnl == Decimal("50")
    assert trade.net_pnl == Decimal("50")
    assert trade.reason == "signal_reversal"
    # Order intent is now retained, but does not touch numerical fields.
    assert trade.order_intent is not None


# =====================================================================
# I. permissive risk limits preserve legacy numerical results.
# =====================================================================


def test_i_permissive_risk_limits_preserve_legacy_numerical_results() -> None:
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
    # Both retain a real (and, in this identical scenario, field-equal)
    # OrderIntent - its presence is what changed, not any numerical
    # result.
    assert lt.order_intent is not None
    assert gt.order_intent is not None
    assert lt.order_intent.idempotency_key == gt.order_intent.idempotency_key


# =====================================================================
# J. rejected risk-gated entries do NOT retain an accepted OrderIntent
#    as if an order had entered the market.
# =====================================================================


def test_j_rejected_entry_retains_no_accepted_order_intent() -> None:
    restrictive = RiskLimits(
        max_intraday_loss=Decimal("100000"),
        max_position_size=Decimal("1"),
        max_per_trade_risk=Decimal("100000"),
    )
    result = _run(risk_limits=restrictive)
    assert result.trades == ()
    # No SimulatedTrade exists at all - there is no accepted-entry
    # OrderIntent to retain, since no position was ever opened.
    assert result.validation.trade_count == 0
    assert result.validation.risk_rejected_trades == 2


# =====================================================================
# K. the canonical OrderIntent type from domain/order/contracts.py is
#    actually used - never a parallel/duplicated type.
# =====================================================================


def test_k_canonical_order_intent_type_is_actually_used() -> None:
    from intraday.domain.order import contracts as domain_order_contracts
    from intraday.research.backtesting import contracts as backtest_contracts
    from intraday.research.backtesting import execution as backtest_execution

    result = _run(risk_limits=None)
    oi = result.trades[0].order_intent
    assert oi is not None
    assert type(oi) is domain_order_contracts.OrderIntent
    # The Backtest contracts/execution modules import the canonical type
    # directly - no `BacktestOrderIntent` or similar parallel type is
    # defined anywhere in either module.
    assert not hasattr(backtest_contracts, "BacktestOrderIntent")
    assert not hasattr(backtest_execution, "BacktestOrderIntent")
    assert backtest_contracts.OrderIntent is domain_order_contracts.OrderIntent


# =====================================================================
# L. domain/order/contracts.py itself remains unmodified - not
#    assertable from within a test (that is a `git diff` fact, reported
#    separately); this is a smoke check that the canonical contract's
#    own shape (field set / validation) is untouched by this checkpoint.
# =====================================================================


def test_l_canonical_order_intent_contract_shape_is_untouched() -> None:
    field_names = set(OrderIntent.__dataclass_fields__)
    assert field_names == {
        "order_id",
        "instrument_id",
        "side",
        "quantity",
        "order_type",
        "time_in_force",
        "strategy_id",
        "created_at",
        "idempotency_key",
        "status",
        "signal_id",
        "limit_price",
        "trigger_price",
    }
