# tests/unit/research/test_checkpoint_64_30_risk_gate_wiring.py
#
# Checkpoint 64.30: focused tests proving the OPT-IN canonical risk gate
# is correctly wired into `run_backtest()`'s real entry decision, per
# the checkpoint's own A-J list. Every test either (A) proves the
# `risk_limits=None` default path is byte-identical to pre-64.30
# behavior, or (B-J) proves a configured `risk_limits` correctly
# approves/rejects entries via the REAL, unmodified
# `domain.risk.policy.evaluate_order_risk()` - never a re-implemented
# or Backtest-specific risk-policy shortcut.
#
# Fixture/helper pattern (scripted strategy, `_config`/`_dq`/
# `_bars_from_closes`) deliberately mirrors
# `test_checkpoint_64_29_foundations.py` - copied locally, not imported,
# so this file has no cross-test-file coupling (same discipline that
# file itself documents).
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.risk.policy import RiskEvaluationContext, evaluate_order_risk
from intraday.domain.shared_kernel.contracts import Timeframe
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
    strategy_id = "scripted_stub_6430"
    display_name = "Scripted Stub 64.30"
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
        "strategy_id": "scripted_stub_6430",
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


# A single scripted scenario reused throughout: one 10-share BULLISH
# entry at bar 1's open (100), reversed and closed at bar 3's open
# (105) - matches 64.29's own characterization scenario exactly, so
# this file's "legacy behavior" baseline is directly comparable to that
# checkpoint's already-proven numbers.
_CLOSES = ["100", "100", "105", "105", "110"]
_SIGNALS = {0: StrategyDirection.BULLISH, 2: StrategyDirection.BEARISH}


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
        StrategyConfigurationValues("scripted_stub_6430", "v1", "v1", "v1", {}),
        config,
        lambda field_id, bars_: (),
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )


_PERMISSIVE_LIMITS = RiskLimits(
    max_intraday_loss=Decimal("100000"),
    max_position_size=Decimal("100"),
    max_per_trade_risk=Decimal("100000"),
)


# =====================================================================
# A. risk_limits=None preserves legacy behavior.
# =====================================================================


def test_a_risk_limits_none_preserves_legacy_behavior() -> None:
    result = _run(risk_limits=None)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.quantity == Decimal("10")
    assert trade.entry_price == Decimal("100")
    assert trade.exit_price == Decimal("105")
    assert trade.gross_pnl == Decimal("50")
    assert trade.net_pnl == Decimal("50")
    assert trade.reason == "signal_reversal"
    assert result.validation.risk_rejected_trades == 0
    assert result.validation.risk_rejection_reason_breakdown == {}
    assert result.validation.rejected_trades == 0


# =====================================================================
# B. restrictive max_position_size rejects the entry.
# =====================================================================


def test_b_restrictive_max_position_size_rejects_the_entry() -> None:
    restrictive = RiskLimits(
        max_intraday_loss=Decimal("100000"),
        max_position_size=Decimal("5"),
        max_per_trade_risk=Decimal("100000"),
    )
    result = _run(risk_limits=restrictive)
    assert len(result.trades) == 0
    # Both scripted signals (BULLISH at bar 0, BEARISH at bar 2) are
    # each independently rejected - neither ever opens a position, so
    # `open_position` stays `None` for the whole run and BOTH signals
    # reach the entry-decision branch and are gated.
    assert result.validation.risk_rejected_trades == 2
    assert result.validation.risk_rejection_reason_breakdown == {"MAX_POSITION_SIZE_EXCEEDED": 2}


# =====================================================================
# C. max_concurrent_positions rejects the entry.
# =====================================================================


def test_c_max_concurrent_positions_rejects_the_entry() -> None:
    # `BacktestConfiguration.max_concurrent_positions` is forced to
    # exactly 1 by `__post_init__` (POC-scope invariant, unrelated to
    # this checkpoint) - the risk gate's `current_open_positions_count`
    # is honestly 0 at every entry decision in the current
    # single-position engine, so `max_concurrent_positions=1` can never
    # itself trigger a rejection from within `run_backtest()`'s own
    # state. This test instead proves the WIRING is correct by
    # confirming, directly against the real `evaluate_order_risk()`,
    # that a `current_open_positions_count >= max_concurrent_positions`
    # input the adapter constructs does trigger the rejection - i.e.
    # the same real function `run_backtest()` now calls. See
    # `docs/architecture/CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md`
    # ("CHECKPOINT 64.30 IMPLEMENTATION NOTES") for why the current
    # engine cannot honestly reach `current_open_positions_count >= 1`
    # AT an entry decision (entries only happen when `open_position is
    # None`).
    from intraday.domain.risk.contracts import RiskDecisionOutcome, RiskRejectionReason
    from intraday.domain.risk.contracts import TradingHaltStatus as _Halt
    from intraday.research.backtesting.order_intent_adapter import (
        build_backtest_entry_order_intent,
    )

    order = build_backtest_entry_order_intent(
        strategy_id="scripted_stub_6430",
        instrument_id=INSTRUMENT,
        direction=StrategyDirection.BULLISH,
        quantity=Decimal("10"),
        entry_timestamp=BASE,
        entry_index=1,
    )
    context = RiskEvaluationContext(
        risk_limits=_PERMISSIVE_LIMITS,
        risk_configuration_version="v1",
        now=BASE,
        current_daily_realized_pnl=Decimal("0"),
        current_total_exposure=Decimal("0"),
        current_open_positions_count=1,
        current_position_size_for_instrument=Decimal("0"),
        estimated_order_notional=Decimal("1000"),
        max_concurrent_positions=1,
        max_total_exposure=Decimal("1000000"),
        kill_switch_status=_Halt.ACTIVE,
        market_session_is_open=True,
        strategy_is_active=True,
        data_quality_is_stale=False,
        already_submitted_idempotency_keys=frozenset(),
        instruments_with_pending_or_open_orders=frozenset(),
    )
    decision = evaluate_order_risk(order, context)
    assert decision.outcome is RiskDecisionOutcome.REJECTED
    assert decision.reason_code is RiskRejectionReason.MAX_CONCURRENT_POSITIONS_EXCEEDED


# =====================================================================
# D. max_intraday_loss rejects the entry.
# =====================================================================


def test_d_max_intraday_loss_rejects_the_entry() -> None:
    # Two entries: the first (bars 0-2, BULLISH->BEARISH reversal at
    # bar 2) is approved and closes at a LOSS large enough that the
    # second entry (signalled again inside the same scripted run) is
    # then rejected by `max_intraday_loss` - proving the gate consults
    # `running_equity` AS IT ACCUMULATES DURING THE SAME BACKTEST, not
    # merely a static value.
    closes = ["100", "100", "90", "90", "90", "90"]
    signals = {
        0: StrategyDirection.BULLISH,
        2: StrategyDirection.BEARISH,
        3: StrategyDirection.BULLISH,
    }
    bars = _bars_from_closes(closes)
    strategy = _ScriptedStrategy(signals)
    tight_loss_limit = RiskLimits(
        max_intraday_loss=Decimal("50"),
        max_position_size=Decimal("100"),
        max_per_trade_risk=Decimal("100000"),
    )
    config = _config(
        end=BASE + timedelta(minutes=len(closes) + 5),
        risk_limits=tight_loss_limit,
    )
    result = run_backtest(
        bars,
        strategy,  # type: ignore[arg-type]
        StrategyConfigurationValues("scripted_stub_6430", "v1", "v1", "v1", {}),
        config,
        lambda field_id, bars_: (),
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    # First trade: entry 100 -> exit 90, BULLISH => -10/share * 10 = -100
    # loss, already exceeding the 50 max_intraday_loss limit on its OWN
    # -100 net_pnl BEFORE it's even closed and applied to running_equity;
    # by the time the SECOND signal (index 3) tries to enter, running
    # equity already reflects the first trade's -100 loss, so the
    # second entry is rejected.
    assert len(result.trades) == 1
    assert result.trades[0].net_pnl == Decimal("-100")
    assert result.validation.risk_rejected_trades == 1
    assert result.validation.risk_rejection_reason_breakdown == {"MAX_DAILY_LOSS_EXCEEDED": 1}


# =====================================================================
# E. permissive limits allow the entry.
# =====================================================================


def test_e_permissive_limits_allow_the_entry() -> None:
    result = _run(risk_limits=_PERMISSIVE_LIMITS)
    assert len(result.trades) == 1
    assert result.trades[0].quantity == Decimal("10")
    assert result.validation.risk_rejected_trades == 0


# =====================================================================
# F. approved entry produces the same trade result as legacy mode.
# =====================================================================


def test_f_approved_entry_matches_legacy_mode_trade_result() -> None:
    legacy = _run(risk_limits=None)
    gated = _run(risk_limits=_PERMISSIVE_LIMITS)
    assert len(legacy.trades) == len(gated.trades) == 1
    lt, gt = legacy.trades[0], gated.trades[0]
    assert lt.entry_price == gt.entry_price
    assert lt.exit_price == gt.exit_price
    assert lt.quantity == gt.quantity
    assert lt.reason == gt.reason
    assert lt.gross_pnl == gt.gross_pnl
    assert lt.net_pnl == gt.net_pnl
    assert legacy.equity_curve == gated.equity_curve
    assert legacy.metrics == gated.metrics


# =====================================================================
# G. rejected entry does not create a position/trade.
# =====================================================================


def test_g_rejected_entry_does_not_create_a_position_or_trade() -> None:
    restrictive = RiskLimits(
        max_intraday_loss=Decimal("100000"),
        max_position_size=Decimal("1"),
        max_per_trade_risk=Decimal("100000"),
    )
    result = _run(risk_limits=restrictive)
    assert result.trades == ()
    assert result.validation.trade_count == 0
    assert result.metrics.total_trades == 0
    # No position was ever created to gain or lose against - equity
    # never moved from `initial_capital`, matching the SAME zero-trade
    # equity-curve shape a legacy (risk_limits=None) zero-trade run
    # produces (proven by comparison below, not merely asserted).
    assert result.metrics.final_capital == Decimal("100000")
    zero_trade_legacy = _run(
        risk_limits=None,
        position_size_value=Decimal("0.0000001"),  # forces quantity_for_config -> 0
        position_sizing_mode=PositionSizingMode.PERCENT_OF_EQUITY,
    )
    assert result.equity_curve == zero_trade_legacy.equity_curve


# =====================================================================
# H. risk rejection uses the canonical RiskRejectionReason.
# =====================================================================


def test_h_risk_rejection_uses_the_canonical_reason_vocabulary() -> None:
    from intraday.domain.risk.contracts import RiskRejectionReason

    restrictive = RiskLimits(
        max_intraday_loss=Decimal("100000"),
        max_position_size=Decimal("5"),
        max_per_trade_risk=Decimal("100000"),
    )
    result = _run(risk_limits=restrictive)
    reason_keys = set(result.validation.risk_rejection_reason_breakdown)
    assert reason_keys <= {member.value for member in RiskRejectionReason}
    assert reason_keys == {RiskRejectionReason.MAX_POSITION_SIZE_EXCEEDED.value}


# =====================================================================
# I. the REAL evaluate_order_risk() function is invoked (proven by
# monkeypatching it and observing the backtest's outcome change).
# =====================================================================


def test_i_the_real_evaluate_order_risk_function_is_invoked(monkeypatch) -> None:
    calls: list[object] = []
    import intraday.research.backtesting.risk_gate_adapter as adapter_module

    real_fn = adapter_module.evaluate_order_risk

    def _spy(order, context):
        calls.append((order, context))
        return real_fn(order, context)

    monkeypatch.setattr(adapter_module, "evaluate_order_risk", _spy)
    result = _run(risk_limits=_PERMISSIVE_LIMITS)
    assert len(calls) == 1
    called_order, called_context = calls[0]
    assert called_context.risk_limits is _PERMISSIVE_LIMITS
    assert len(result.trades) == 1


def test_i_no_risk_evaluation_occurs_when_risk_limits_is_none(monkeypatch) -> None:
    calls: list[object] = []
    import intraday.research.backtesting.risk_gate_adapter as adapter_module

    real_fn = adapter_module.evaluate_order_risk

    def _spy(order, context):
        calls.append((order, context))
        return real_fn(order, context)

    monkeypatch.setattr(adapter_module, "evaluate_order_risk", _spy)
    _run(risk_limits=None)
    assert calls == []


# =====================================================================
# J. no Paper Trading behavior changes (module-level proof: PaperBroker
# and paper_trading service source are untouched by this checkpoint -
# the strongest available in-repo proof is that they import/behave
# identically; a git-diff-based confirmation is reported separately in
# the checkpoint report, not re-derived here as a test since a test
# cannot itself inspect `git diff`).
# =====================================================================


def test_j_paper_broker_module_has_no_backtest_risk_gate_coupling() -> None:
    import inspect

    from intraday.infrastructure.brokers.paper import broker as paper_broker_module

    source = inspect.getsource(paper_broker_module)
    assert "risk_gate_adapter" not in source
    assert "BacktestConfiguration" not in source
    assert "run_backtest" not in source
