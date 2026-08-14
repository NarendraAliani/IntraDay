# research

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

A. Quant Research Lab bounded context. Owns the full idea-to-production research lifecycle (Section 6). Strategies are proposed and validated here before promotion to trading_engine.

## Depends On

domain, data/research_data, data/historical_data

## Must Not Depend On

trading_engine (no live execution), infrastructure/brokers, communication

## Checkpoint 32 update

Real code for this bounded context lives at `src/intraday/research/`
(this top-level directory remains the original Checkpoint-1 file-structure
placeholder). No new research/backtesting logic was added this
checkpoint - `application/reporting/backtest_report.py` only maps
existing `BacktestResult` data into the shared report-metadata
contract. See [docs/architecture/REPORTING_ARCHITECTURE.md](../docs/architecture/REPORTING_ARCHITECTURE.md).

