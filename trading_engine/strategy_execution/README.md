# trading_engine/strategy_execution

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Sole canonical home for **strategy implementation** — the executable code
satisfying the `domain/strategy` interface — plus the runtime orchestration
that invokes it against live/paper signals; strategies remain isolated per
Rule 5.1.

**Clarified at Checkpoint 2 (Section 4 — Strategy Lifecycle Refinement):**
this directory is the single source of truth for what a strategy *does*.
`research/strategy_specifications` only describes intent (declarative,
non-executable); a strategy's specification is implemented exactly once,
here. `research/backtesting` is granted a narrow, read-only dependency on
the strategy-implementation module of this directory (only that module — not
`order_management`, `execution_management`, `broker_abstraction`,
`risk_engine`, or `session_management`) so that backtests run the identical
code path as live trading (Rule 5.5). This is a deliberate, documented
exception to the general rule that `research/` must not depend on
`trading_engine/` — see [DOMAIN_BOUNDARIES.md](../../docs/architecture/DOMAIN_BOUNDARIES.md).

## Depends On

domain/strategy, signal_intelligence

## Must Not Depend On

Telegram/Discord APIs, database implementation, frontend, auth. `research/` may read only the strategy-implementation module of this directory — this directory must never depend back on `research/`.

