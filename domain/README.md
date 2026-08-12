# domain

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Shared canonical domain contracts (entities, value objects, interfaces) forming the ubiquitous language of the platform. Pure, technology-neutral definitions with no framework or infra dependencies.

**Minimum viable shared kernel — 14 contracts (revised at Checkpoint 2 — see [ARCHITECTURE_DECISIONS.md](../docs/architecture/ARCHITECTURE_DECISIONS.md) #11; count verified at Checkpoint 3 §29):**
`shared_kernel`, `market_data`, `instrument`, `universe`, `feature`, `strategy`,
`signal`, `risk`, `portfolio`, `order`, `position`, `trade`, `broker`,
`session` — each included only because it is consumed identically by two or
more bounded contexts (most often to preserve backtest/paper/live parity,
Rule 5.5) and rarely changes. `experiment` was deliberately **removed** from
the shared kernel at Checkpoint 2: it is a research-lifecycle concept
consumed by exactly one bounded context (`research/`) plus references-only
elsewhere, so its full contract now lives at `research/experiments`; only a
generic version/lineage identifier primitive remains here, in
`shared_kernel`. Do not add a new top-level `domain/` package for a concept
consumed by only one bounded context — put it there instead and reference it
by id.

## Depends On

Nothing (innermost layer)

## Must Not Depend On

research, signal_intelligence, trading_engine, control_plane, communication, application, infrastructure, frontend

