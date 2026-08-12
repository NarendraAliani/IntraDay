# research/strategy_specifications

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Versioned, technology-neutral strategy **specifications** (rules, parameters,
intended regime) — declarative documents, not executable code (Rule 14).

**Clarified at Checkpoint 2 (Section 4 — Strategy Lifecycle Refinement):** a
specification here is never itself run. It describes intent; the one and
only executable implementation of a given specification lives at
`trading_engine/strategy_execution`, so backtest, paper and live all run the
*same code* (Rule 5.5) and a research artifact can never be silently mistaken
for a production executable. `research/backtesting` invokes the
implementation at `trading_engine/strategy_execution`; it never re-implements
strategy logic locally.

## Depends On

domain/strategy, research/hypotheses

## Must Not Depend On

Broker/execution concerns; must not itself contain runnable strategy code (that belongs to `trading_engine/strategy_execution`)

