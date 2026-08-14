# File: src/intraday/research/backtesting/serialization.py
#
# Checkpoint 27: pure `BacktestResult` <-> JSON-safe `dict` conversion.
# Lives in `research.backtesting` (no Django/infrastructure dependency)
# so the persistence layer only ever moves an already-JSON-safe dict,
# never a Decimal/datetime/enum-bearing dataclass, into a JSONField -
# the same separation of concerns `StrategyConfigurationRecord`'s own
# JSONField already established.
from __future__ import annotations

from decimal import Decimal

from intraday.research.backtesting.contracts import BacktestResult


def _dec(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def to_json_dict(result: BacktestResult) -> dict[str, object]:
    config = result.configuration
    return {
        "backtest_id": result.backtest_id,
        "generated_at": result.generated_at.isoformat(),
        "configuration": {
            "instrument_id": config.instrument_id,
            "timeframe": config.timeframe.value,
            "start": config.start.isoformat(),
            "end": config.end.isoformat(),
            "strategy_id": config.strategy_id,
            "specification_version": config.specification_version,
            "code_version": config.code_version,
            "configuration_version": config.configuration_version,
            "initial_capital": _dec(config.initial_capital),
            "position_sizing_mode": config.position_sizing_mode.value,
            "position_size_value": _dec(config.position_size_value),
            "max_concurrent_positions": config.max_concurrent_positions,
            "brokerage_percent": _dec(config.brokerage_percent),
            "slippage_percent": _dec(config.slippage_percent),
        },
        "trades": [
            {
                "trade_id": t.trade_id,
                "strategy_id": t.strategy_id,
                "specification_version": t.specification_version,
                "code_version": t.code_version,
                "configuration_version": t.configuration_version,
                "instrument_id": t.instrument_id,
                "timeframe": t.timeframe.value,
                "direction": t.direction.value,
                "entry_timestamp": t.entry_timestamp.isoformat(),
                "entry_price": _dec(t.entry_price),
                "exit_timestamp": t.exit_timestamp.isoformat(),
                "exit_price": _dec(t.exit_price),
                "quantity": _dec(t.quantity),
                "gross_pnl": _dec(t.gross_pnl),
                "costs": _dec(t.costs),
                "net_pnl": _dec(t.net_pnl),
                "reason": t.reason,
                "mfe": _dec(t.mfe),
                "mae": _dec(t.mae),
            }
            for t in result.trades
        ],
        "equity_curve": [
            {
                "timestamp": p.timestamp.isoformat(),
                "balance": _dec(p.balance),
                "cumulative_pnl": _dec(p.cumulative_pnl),
                "drawdown": _dec(p.drawdown),
                "drawdown_percent": _dec(p.drawdown_percent),
            }
            for p in result.equity_curve
        ],
        "metrics": {
            "total_trades": result.metrics.total_trades,
            "winning_trades": result.metrics.winning_trades,
            "losing_trades": result.metrics.losing_trades,
            "win_rate_percent": _dec(result.metrics.win_rate_percent),
            "gross_profit": _dec(result.metrics.gross_profit),
            "gross_loss": _dec(result.metrics.gross_loss),
            "net_pnl": _dec(result.metrics.net_pnl),
            "profit_factor": _dec(result.metrics.profit_factor),
            "max_drawdown": _dec(result.metrics.max_drawdown),
            "max_drawdown_percent": _dec(result.metrics.max_drawdown_percent),
            "average_trade": _dec(result.metrics.average_trade),
            "average_winner": _dec(result.metrics.average_winner),
            "average_loser": _dec(result.metrics.average_loser),
            "sharpe_ratio_trade_level": _dec(result.metrics.sharpe_ratio_trade_level),
            "sortino_ratio_trade_level": _dec(result.metrics.sortino_ratio_trade_level),
            "final_capital": _dec(result.metrics.final_capital),
            "return_percent": _dec(result.metrics.return_percent),
        },
        "data_quality": {
            "data_source": result.data_quality.data_source,
            "data_quality": result.data_quality.data_quality.value,
            "bar_count": result.data_quality.bar_count,
            "missing_bar_note": result.data_quality.missing_bar_note,
            "transaction_cost_assumption": result.data_quality.transaction_cost_assumption,
            "slippage_assumption": result.data_quality.slippage_assumption,
            "survivorship_bias_note": result.data_quality.survivorship_bias_note,
        },
    }
