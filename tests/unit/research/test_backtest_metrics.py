# tests/unit/research/test_backtest_metrics.py
#
# Checkpoint 64.21 §11: coverage for the new Expectancy/Maximum
# Consecutive Losses/Risk-Reward metrics added to `compute_metrics()`.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.research.backtesting.contracts import MarkToMarketPoint, SimulatedTrade
from intraday.research.backtesting.metrics import compute_metrics, max_consecutive_losses

INSTRUMENT = "NSE:TESTCO"
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


def _trade(*, index: int, net_pnl: str) -> SimulatedTrade:
    entry = BASE + timedelta(minutes=index)
    return SimulatedTrade(
        trade_id=f"trade-{index}",
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.ONE_MINUTE,
        direction="LONG",  # type: ignore[arg-type]
        entry_timestamp=entry,
        entry_price=Decimal("100"),
        exit_timestamp=entry + timedelta(minutes=1),
        exit_price=Decimal("100") + Decimal(net_pnl),
        quantity=Decimal("1"),
        gross_pnl=Decimal(net_pnl),
        costs=Decimal("0"),
        net_pnl=Decimal(net_pnl),
        reason="SIGNAL_REVERSAL",
    )


def _mtm(trades: list[SimulatedTrade]) -> tuple[MarkToMarketPoint, ...]:
    initial_capital = Decimal("100000")
    realized = Decimal("0")
    points = []
    for trade in trades:
        realized += trade.net_pnl
        equity = initial_capital + realized
        points.append(
            MarkToMarketPoint(
                timestamp=trade.exit_timestamp,
                realized_pnl=realized,
                unrealized_pnl=Decimal("0"),
                total_equity=equity,
                peak_equity=equity,
                drawdown=Decimal("0"),
                drawdown_percent=Decimal("0"),
            )
        )
    return tuple(points)


def test_max_consecutive_losses_counts_the_longest_streak_in_trade_order() -> None:
    trades = [
        _trade(index=0, net_pnl="10"),
        _trade(index=1, net_pnl="-5"),
        _trade(index=2, net_pnl="-5"),
        _trade(index=3, net_pnl="-5"),
        _trade(index=4, net_pnl="10"),
        _trade(index=5, net_pnl="-5"),
    ]

    assert max_consecutive_losses(trades) == 3


def test_max_consecutive_losses_is_zero_with_no_losing_trades() -> None:
    trades = [_trade(index=0, net_pnl="10"), _trade(index=1, net_pnl="5")]
    assert max_consecutive_losses(trades) == 0


def test_expectancy_and_risk_reward_are_computed_from_real_winners_and_losers() -> None:
    trades = [
        _trade(index=0, net_pnl="20"),  # winner
        _trade(index=1, net_pnl="20"),  # winner
        _trade(index=2, net_pnl="-10"),  # loser
    ]
    metrics = compute_metrics(Decimal("100000"), trades, _mtm(trades))

    # average_winner = 20, average_loser = -10, win_rate = 2/3
    assert metrics.expectancy is not None
    expected_expectancy = (Decimal(2) / 3 * Decimal(20)) + (Decimal(1) / 3 * Decimal(-10))
    assert metrics.expectancy == expected_expectancy
    assert metrics.risk_reward_ratio == Decimal(2)  # 20 / abs(-10)
    assert metrics.max_consecutive_losses == 1


def test_expectancy_and_risk_reward_are_none_with_no_losing_trades() -> None:
    """Matches average_winner/average_loser's own "None when the
    category is empty" convention - never a fabricated substitute."""
    trades = [_trade(index=0, net_pnl="10")]
    metrics = compute_metrics(Decimal("100000"), trades, _mtm(trades))

    assert metrics.expectancy is None
    assert metrics.risk_reward_ratio is None
    assert metrics.max_consecutive_losses == 0


def test_expectancy_and_risk_reward_are_none_with_no_trades_at_all() -> None:
    metrics = compute_metrics(Decimal("100000"), [], ())

    assert metrics.expectancy is None
    assert metrics.risk_reward_ratio is None
    assert metrics.max_consecutive_losses == 0
