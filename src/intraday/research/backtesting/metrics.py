# File: src/intraday/research/backtesting/metrics.py
#
# Checkpoint 28: `BacktestMetrics` computation, factored out of
# `engine.py` so `portfolio.py` (multi-instrument) reuses the EXACT same
# formulas rather than re-implementing them - Part 27's non-redundancy
# requirement, carried forward to the portfolio engine.
from __future__ import annotations

from decimal import Decimal

from intraday.research.backtesting.contracts import (
    BacktestMetrics,
    MarkToMarketPoint,
    SimulatedTrade,
)


def max_drawdown_duration_bars(points: tuple[MarkToMarketPoint, ...]) -> int:
    """Longest streak of consecutive bars spent below the running peak
    (Part 5)."""
    longest = 0
    current = 0
    for point in points:
        if point.drawdown > 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def compute_metrics(
    initial_capital: Decimal,
    trades: list[SimulatedTrade] | tuple[SimulatedTrade, ...],
    mtm_curve: tuple[MarkToMarketPoint, ...],
) -> BacktestMetrics:
    """Shared metrics formula - single-instrument (`engine.py`) and
    portfolio (`portfolio.py`) backtests both call this, never a
    per-engine copy. Drawdown is computed from the MARK-TO-MARKET curve
    (Checkpoint 28 Part 5), never merely from trade-close points."""
    total = len(trades)
    winners = [t for t in trades if t.net_pnl > 0]
    losers = [t for t in trades if t.net_pnl < 0]
    gross_profit = sum((t.net_pnl for t in winners), Decimal("0"))
    gross_loss = sum((t.net_pnl for t in losers), Decimal("0"))
    net_pnl = sum((t.net_pnl for t in trades), Decimal("0"))
    win_rate = (Decimal(len(winners)) / total * 100) if total else Decimal("0")
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss != 0 else None
    max_dd = max((p.drawdown for p in mtm_curve), default=Decimal("0"))
    max_dd_percent = max((p.drawdown_percent for p in mtm_curve), default=Decimal("0"))
    max_dd_duration = max_drawdown_duration_bars(mtm_curve)
    average_trade = (net_pnl / total) if total else Decimal("0")
    average_winner = (gross_profit / len(winners)) if winners else None
    average_loser = (gross_loss / len(losers)) if losers else None

    sharpe: Decimal | None = None
    sortino: Decimal | None = None
    if total >= 2:
        returns = [
            (t.net_pnl / (t.entry_price * t.quantity))
            if t.entry_price * t.quantity != 0
            else Decimal("0")
            for t in trades
        ]
        mean_return = sum(returns, Decimal("0")) / total
        variance = sum(((r - mean_return) ** 2 for r in returns), Decimal("0")) / (total - 1)
        std_dev = variance.sqrt() if variance > 0 else Decimal("0")
        if std_dev > 0:
            sharpe = mean_return / std_dev
        downside_returns = [r for r in returns if r < 0]
        if downside_returns:
            downside_variance = sum((r**2 for r in downside_returns), Decimal("0")) / len(
                downside_returns
            )
            downside_dev = downside_variance.sqrt()
            if downside_dev > 0:
                sortino = mean_return / downside_dev

    final_capital = mtm_curve[-1].total_equity if mtm_curve else initial_capital
    return_percent = (
        (final_capital - initial_capital) / initial_capital * 100
        if initial_capital > 0
        else Decimal("0")
    )

    return BacktestMetrics(
        total_trades=total,
        winning_trades=len(winners),
        losing_trades=len(losers),
        win_rate_percent=win_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=net_pnl,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
        max_drawdown_percent=max_dd_percent,
        max_drawdown_duration_bars=max_dd_duration,
        average_trade=average_trade,
        average_winner=average_winner,
        average_loser=average_loser,
        sharpe_ratio_trade_level=sharpe,
        sortino_ratio_trade_level=sortino,
        final_capital=final_capital,
        return_percent=return_percent,
    )
