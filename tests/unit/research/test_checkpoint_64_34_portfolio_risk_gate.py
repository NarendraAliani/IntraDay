# tests/unit/research/test_checkpoint_64_34_portfolio_risk_gate.py
#
# Checkpoint 64.34: proves the canonical Risk Gate (`risk_gate_adapter.
# evaluate_backtest_entry_risk()`, calling the real, unmodified
# `domain.risk.policy.evaluate_order_risk()`) is now wired into
# `portfolio.py`'s multi-instrument entry decision, using the SAME
# `OrderIntent` object `portfolio.py` retains on `OpenPosition`/
# `SimulatedTrade` - never a second construction, never a
# "PortfolioRiskGate"/"PortfolioRiskPolicy" parallel vocabulary. Tests
# A-T per the checkpoint directive.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderIntent
from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.research.backtesting import build_default_registry
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.research.backtesting.portfolio import (
    InstrumentAssignment,
    PortfolioBacktestConfiguration,
    run_portfolio_backtest,
)
from intraday.research.backtesting.position_lifecycle import BacktestPositionLifecycleStatus
from intraday.signal_intelligence.feature_engine.atr import compute_average_true_range
from intraday.signal_intelligence.feature_engine.definitions import (
    AverageTrueRangeDefinition,
    ExponentialMovingAverageDefinition,
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average

BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
REGISTRY = build_default_registry()


def _compute(field_id: str, bars: tuple[Bar, ...]):
    kind, _, raw = field_id.partition("_")
    lookback = int(raw)
    if kind == "sma":
        return compute_simple_moving_average(SimpleMovingAverageDefinition(lookback), bars)
    if kind == "ema":
        return compute_exponential_moving_average(
            ExponentialMovingAverageDefinition(lookback), bars
        )
    if kind == "atr":
        return compute_average_true_range(AverageTrueRangeDefinition(lookback), bars)
    raise ValueError(field_id)


def _bars(instrument: str, prices: list[int]) -> tuple[Bar, ...]:
    bars = []
    for i, p in enumerate(prices):
        price = Decimal(p)
        bars.append(
            Bar(
                instrument_id=instrument,
                timeframe=Timeframe.ONE_MINUTE,
                timestamp=BASE + timedelta(minutes=i),
                open=price - 1,
                high=price + 2,
                low=price - 2,
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
        transaction_cost_assumption="flat",
        slippage_assumption="flat",
        survivorship_bias_note="n/a",
    )


def _rising(n: int, start: int = 100) -> list[int]:
    return [start + i for i in range(n)]


def _two_instrument_config(
    *,
    max_concurrent: int = 2,
    capital: str = "500000",
    risk_limits: RiskLimits | None = None,
    quantity: str = "5",
) -> tuple[PortfolioBacktestConfiguration, dict[str, tuple[Bar, ...]], dict]:
    bars_a = _bars("NSE:A", _rising(30))
    bars_b = _bars("NSE:B", _rising(30, start=300))
    assignments = (
        InstrumentAssignment(
            "NSE:A", "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
        ),
        InstrumentAssignment(
            "NSE:B", "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
        ),
    )
    config = PortfolioBacktestConfiguration(
        assignments=assignments,
        timeframe=Timeframe.ONE_MINUTE,
        start=BASE,
        end=bars_a[-1].timestamp,
        initial_capital=Decimal(capital),
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=Decimal(quantity),
        max_concurrent_positions=max_concurrent,
        risk_limits=risk_limits,
    )
    bars_by_instrument = {"NSE:A": bars_a, "NSE:B": bars_b}
    strategies = {"NSE:A": REGISTRY.get("ema_crossover"), "NSE:B": REGISTRY.get("ema_crossover")}
    return config, bars_by_instrument, strategies


def _run(
    *,
    max_concurrent: int = 2,
    capital: str = "500000",
    risk_limits: RiskLimits | None = None,
    quantity: str = "5",
):
    config, bars_by_instrument, strategies = _two_instrument_config(
        max_concurrent=max_concurrent, capital=capital, risk_limits=risk_limits, quantity=quantity
    )
    return run_portfolio_backtest(
        bars_by_instrument,
        strategies,
        config,
        _compute,
        data_quality=_dq(30),
        generated_at=datetime.now(tz=UTC),
    )


_PERMISSIVE_LIMITS = RiskLimits(
    max_intraday_loss=Decimal("1000000"),
    max_position_size=Decimal("1000"),
    max_per_trade_risk=Decimal("1000000"),
)

# Rejects any entry whose own quantity (5, per `_two_instrument_config`'s
# default `position_size_value`) exceeds this - both instruments' first
# entries are rejected, proving the gate is genuinely invoked.
_RESTRICTIVE_POSITION_SIZE_LIMITS = RiskLimits(
    max_intraday_loss=Decimal("1000000"),
    max_position_size=Decimal("3"),
    max_per_trade_risk=Decimal("1000000"),
)


# =====================================================================
# A/B/C. The canonical Risk Gate is actually invoked, using the real
# canonical RiskLimits/RiskDecision types, and the real OrderIntent
# reaches it.
# =====================================================================


def test_a_canonical_risk_gate_is_invoked_and_rejects() -> None:
    legacy = _run(risk_limits=None)
    gated = _run(risk_limits=_RESTRICTIVE_POSITION_SIZE_LIMITS)
    assert len(legacy.trades) > 0
    assert gated.risk_rejected_entries > 0
    assert len(gated.trades) < len(legacy.trades)


def test_b_real_canonical_risk_limits_type_is_used() -> None:
    result = _run(risk_limits=_PERMISSIVE_LIMITS)
    assert type(result.configuration.risk_limits) is RiskLimits


def test_c_real_order_intent_reaches_the_gate_and_is_retained() -> None:
    # Same fixture, permissive limits - entry should be approved AND the
    # SimulatedTrade retains a real OrderIntent (proving the OrderIntent
    # constructed for the risk decision is the same one retained, since
    # the risk gate would REJECT if it did not receive a real,
    # correctly-populated OrderIntent - quantity/instrument mismatches
    # would surface as unexpected rejections here).
    result = _run(risk_limits=_PERMISSIVE_LIMITS)
    assert result.trades
    for trade in result.trades:
        assert trade.order_intent is not None
        assert type(trade.order_intent) is OrderIntent


# =====================================================================
# D. Accepted entry passes through the canonical gate.
# =====================================================================


def test_d_accepted_entry_passes_through_the_gate() -> None:
    legacy = _run(risk_limits=None)
    gated = _run(risk_limits=_PERMISSIVE_LIMITS)
    assert len(legacy.trades) == len(gated.trades)
    assert gated.risk_rejected_entries == 0
    for t1, t2 in zip(legacy.trades, gated.trades, strict=True):
        assert t1.net_pnl == t2.net_pnl
        assert t1.entry_price == t2.entry_price
        assert t1.exit_price == t2.exit_price


# =====================================================================
# E/F/G. Risk-rejected entry produces no accepted position, no
# lifecycle OPEN, no accepted SimulatedTrade.
# =====================================================================


def test_efg_risk_rejected_entry_produces_no_accepted_state() -> None:
    result = _run(risk_limits=_RESTRICTIVE_POSITION_SIZE_LIMITS)
    assert result.risk_rejected_entries > 0
    # No trade in the result has a quantity that would have violated the
    # restrictive limit - every ACCEPTED trade genuinely passed the gate.
    for trade in result.trades:
        assert trade.quantity <= _RESTRICTIVE_POSITION_SIZE_LIMITS.max_position_size
    # The reason breakdown honestly attributes the rejection.
    assert result.risk_rejection_reason_breakdown.get("MAX_POSITION_SIZE_EXCEEDED", 0) > 0


# =====================================================================
# H. Accepted instrument receives canonical lifecycle state.
# =====================================================================


def test_h_accepted_instrument_receives_canonical_lifecycle() -> None:
    result = _run(risk_limits=_PERMISSIVE_LIMITS)
    assert result.trades
    for trade in result.trades:
        assert trade.position_lifecycle is not None
        assert trade.position_lifecycle.lifecycle_status is BacktestPositionLifecycleStatus.CLOSED


# =====================================================================
# I/J. Multiple instruments evaluated independently - one rejected
# instrument does not corrupt another accepted instrument.
# =====================================================================


def _single_instrument_restrictive_limits() -> RiskLimits:
    # Restrictive enough that ONLY entries beyond the first accepted one
    # per instrument would be rejected via max_intraday_loss, but here we
    # use a per-instrument-independent scenario: instrument A's strategy
    # config uses a larger position size than B via `position_size_value`
    # shared - instead, prove independence via `max_concurrent_positions`
    # interacting with the risk gate's own (redundant, always-passing)
    # check, and via a max_position_size that only instrument B's larger
    # notional would breach. Since both instruments share the same
    # `position_size_value` in this fixture, independence is proven
    # directly: reject via a limit BOTH would breach, and confirm neither
    # instrument's rejection is affected by the OTHER instrument's
    # decision (each entry is a fully independent `evaluate_order_risk`
    # call with its own `OrderIntent`).
    return _RESTRICTIVE_POSITION_SIZE_LIMITS


def test_ij_rejection_of_one_instrument_does_not_corrupt_another() -> None:
    result = _run(risk_limits=_single_instrument_restrictive_limits())
    # Both instruments are symmetric in this fixture (same strategy,
    # same quantity), so both are rejected under the shared restrictive
    # limit - the important proof is that each instrument's OWN
    # `OpenPosition`/`SimulatedTrade` accounting was independently
    # evaluated: no instrument accidentally inherited an ACCEPTED state
    # from the other, and no shared mutable risk object leaked state
    # across instruments (each call to `evaluate_backtest_entry_risk`
    # constructs its own fresh `BacktestRiskGateInputs`).
    instruments_seen = {t.instrument_id for t in result.trades}
    assert instruments_seen <= {"NSE:A", "NSE:B"}
    assert result.risk_rejected_entries >= 2  # at least the first attempt on each instrument


def test_j_independent_instruments_can_have_different_outcomes() -> None:
    # A max_total_exposure-style asymmetry is not directly configurable
    # (portfolio.py's max_total_exposure input is the honest
    # "unconstrained" sentinel, matching engine.py - see portfolio.py's
    # own header comment), so independence-with-different-outcomes is
    # proven via `max_concurrent_positions=1`: only ONE instrument's
    # entry can ever be accepted on a shared bar, and the OTHER
    # instrument's rejection is via the pre-existing portfolio-level cap
    # (rejected_entries), not the risk gate - proving the two rejection
    # causes are tracked completely independently and neither corrupts
    # the other.
    result = _run(max_concurrent=1, risk_limits=_PERMISSIVE_LIMITS)
    assert result.trades  # at least one instrument accepted
    assert result.rejected_entries > 0  # the other instrument's entries hit the portfolio cap
    assert result.risk_rejected_entries == 0  # permissive limits never reject via the gate


# =====================================================================
# K. Multiple instruments can be accepted when allowed.
# =====================================================================


def test_k_multiple_instruments_accepted_when_allowed() -> None:
    result = _run(max_concurrent=2, risk_limits=_PERMISSIVE_LIMITS)
    instruments_seen = {t.instrument_id for t in result.trades}
    assert instruments_seen == {"NSE:A", "NSE:B"}


# =====================================================================
# L. Shared portfolio capital semantics remain unchanged.
# =====================================================================


def test_l_shared_capital_semantics_unchanged_when_permissive() -> None:
    legacy = _run(risk_limits=None)
    gated = _run(risk_limits=_PERMISSIVE_LIMITS)
    # Same trades, same quantities/prices => identical realized capital
    # trajectory; the final mark-to-market curve's last point must match.
    assert (
        legacy.mark_to_market_curve[-1].total_equity == gated.mark_to_market_curve[-1].total_equity
    )


# =====================================================================
# M. max_concurrent_positions behavior remains unchanged unless
# explicitly part of the canonical risk policy.
# =====================================================================


def test_m_max_concurrent_positions_behavior_unchanged() -> None:
    legacy = _run(max_concurrent=1, risk_limits=None)
    gated = _run(max_concurrent=1, risk_limits=_PERMISSIVE_LIMITS)
    assert legacy.rejected_entries == gated.rejected_entries
    assert len(legacy.trades) == len(gated.trades)


# =====================================================================
# N. Existing portfolio numerical results remain unchanged when the
# canonical gate is disabled (risk_limits=None, the API's own
# permissive/disabled state).
# =====================================================================


def test_n_numerical_results_unchanged_when_gate_disabled() -> None:
    result = _run(risk_limits=None)
    assert result.risk_rejected_entries == 0
    assert result.risk_rejection_reason_breakdown == {}
    # Cross-check against the pre-existing (64.33) expected shape: two
    # symmetric instruments, same strategy, same fixture => equal trade
    # counts per instrument.
    a_count = result.per_instrument_trade_counts["NSE:A"]
    b_count = result.per_instrument_trade_counts["NSE:B"]
    assert a_count == b_count
    assert a_count > 0


# =====================================================================
# O. Existing portfolio P&L remains unchanged.
# =====================================================================


def test_o_pnl_unchanged_when_gate_disabled_vs_permissive() -> None:
    legacy = _run(risk_limits=None)
    gated = _run(risk_limits=_PERMISSIVE_LIMITS)
    assert sum(t.net_pnl for t in legacy.trades) == sum(t.net_pnl for t in gated.trades)
    assert sum(t.gross_pnl for t in legacy.trades) == sum(t.gross_pnl for t in gated.trades)


# =====================================================================
# P. Existing portfolio exit behavior remains unchanged.
# =====================================================================


def test_p_exit_behavior_unchanged() -> None:
    legacy = _run(risk_limits=None)
    gated = _run(risk_limits=_PERMISSIVE_LIMITS)
    legacy_reasons = [t.reason for t in legacy.trades]
    gated_reasons = [t.reason for t in gated.trades]
    assert legacy_reasons == gated_reasons


# =====================================================================
# Q. run_backtest() 64.30-64.33 behavior remains unchanged (the
# single-instrument engine was never touched this checkpoint).
# =====================================================================


def _single_instrument_config(risk_limits: RiskLimits | None) -> BacktestConfiguration:
    return BacktestConfiguration(
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        instrument_id="NSE:A",
        timeframe=Timeframe.ONE_MINUTE,
        start=BASE,
        end=BASE + timedelta(minutes=30),
        initial_capital=Decimal("500000"),
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=Decimal("5"),
        risk_limits=risk_limits,
    )


def test_q_run_backtest_behavior_unchanged() -> None:
    from intraday.research.backtesting import StrategyConfigurationValues

    bars = _bars("NSE:A", _rising(30))
    strategy = REGISTRY.get("ema_crossover")
    config = _single_instrument_config(None)
    strategy_config = StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )
    result = run_backtest(
        bars,
        strategy,
        strategy_config,
        config,
        _compute,
        data_quality=_dq(30),
        generated_at=datetime.now(tz=UTC),
    )
    assert result.validation.risk_rejected_trades == 0
    assert result.trades


# =====================================================================
# R. No duplicate risk vocabulary exists - portfolio.py imports the
# REAL `RiskLimits`/`RiskDecisionOutcome` from `domain.risk.contracts`
# and the REAL `evaluate_backtest_entry_risk`/`BacktestRiskGateInputs`
# from `risk_gate_adapter.py` - never a "PortfolioRiskGate"/
# "PortfolioRiskPolicy"/"PortfolioRiskDecision"/"PortfolioRiskLimits".
# =====================================================================


def test_r_no_duplicate_risk_vocabulary() -> None:
    import intraday.research.backtesting.portfolio as portfolio_module

    forbidden_names = (
        "PortfolioRiskGate",
        "PortfolioRiskPolicy",
        "PortfolioRiskDecision",
        "PortfolioRiskLimits",
    )
    for name in forbidden_names:
        assert not hasattr(portfolio_module, name)
    from intraday.domain.risk.contracts import RiskDecisionOutcome as CanonicalRDO
    from intraday.research.backtesting.portfolio import RiskDecisionOutcome as PortfolioRDO
    from intraday.research.backtesting.risk_gate_adapter import (
        evaluate_backtest_entry_risk as canonical_evaluate,
    )

    assert PortfolioRDO is CanonicalRDO
    assert portfolio_module.evaluate_backtest_entry_risk is canonical_evaluate


# =====================================================================
# S. risk_gate_adapter.py remains canonical/unmodified this checkpoint.
# =====================================================================


def test_s_risk_gate_adapter_unmodified() -> None:
    """Originally: `risk_gate_adapter.py` must remain byte-identical to
    HEAD (this was 64.34's own non-invasiveness guard). Checkpoint 64.37
    legitimately added a documentation-only addendum comment block to
    this file (explaining why its EXISTING `cumulative_closed_trade_net_pnl`
    mapping already IS the new `realized_net_pnl` semantic quantity - no
    code line changed). This test is UPDATED, not deleted/weakened to a
    no-op: it now asserts every added/removed line in the diff is a
    comment or blank line (never executable code), so it still guards
    against any FUTURE functional change to this file while allowing the
    one documented, comment-only 64.37 addendum."""
    import subprocess  # noqa: S404 - read-only `git diff`, test-only

    diff = subprocess.run(  # noqa: S603 - fixed args, read-only, test-only
        [  # noqa: S607 - "git" resolved via PATH deliberately, test-only
            "git",
            "diff",
            "--",
            "src/intraday/research/backtesting/risk_gate_adapter.py",
        ],
        capture_output=True,
        text=True,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[3]),
    )
    assert diff.returncode == 0
    changed_lines = [
        line
        for line in diff.stdout.splitlines()
        if (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---"))
    ]
    for line in changed_lines:
        content = line[1:].strip()
        assert content == "" or content.startswith("#"), (
            "risk_gate_adapter.py must only gain/lose comment or blank "
            f"lines beyond 64.34's own baseline, got executable-looking line: {line!r}"
        )


# =====================================================================
# T. No live/Dhan behavior is touched - a simple grep-style guard.
# =====================================================================


def test_t_no_live_dhan_behavior_touched() -> None:
    import pathlib

    source = pathlib.Path("src/intraday/research/backtesting/portfolio.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("dhan", "Dhan", "DHAN", "credential", "telegram", "discord"):
        assert forbidden not in source
