# research/backtesting

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Baseline and subsequent backtest runs against canonical market-data/feature/strategy contracts (Rule 5.5 parity).

**Clarified at Checkpoint 2:** to guarantee it runs the identical strategy
code path as live trading, this directory holds a narrow, read-only
dependency on the strategy-implementation module of
`trading_engine/strategy_execution` (and no other part of `trading_engine`).
This is a deliberate, documented exception — see
[DOMAIN_BOUNDARIES.md](../../docs/architecture/DOMAIN_BOUNDARIES.md) — and
must never become a two-way dependency.

## Depends On

domain, data/historical_data, research/strategy_specifications, trading_engine/strategy_execution (strategy-implementation module only)

## Must Not Depend On

infrastructure/brokers, trading_engine/order_management, trading_engine/execution_management, trading_engine/broker_abstraction, trading_engine/risk_engine, trading_engine/session_management

