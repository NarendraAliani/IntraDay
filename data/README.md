# data

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Logical data-domain boundaries (Section 11): distinguishes market, historical, cache, trading-state, research, analytics and audit data so storage technology can be decided later without redesigning consumers.

**Three-way data-ownership model, clarified at Checkpoint 2 (Section 6):**

| Layer | Answers | Example |
|---|---|---|
| `domain/` | What does this data *mean*, business-wise? (schema, invariants) | "A Bar has open/high/low/close/volume for one instrument+timeframe" |
| `data/` (this layer) | What *lifecycle/retention* category does an instance of that meaning belong to? | "This Bar is `historical_data`: append-only, immutable once written" vs. "this Bar is `market_data`: live, ephemeral until archived" |
| `infrastructure/persistence` | How is it *physically* stored/retrieved? (Checkpoint 3: PostgreSQL/TimescaleDB for durable data, Parquet for bulk research data, Redis for `cache_transient` — see [TECHNOLOGY_MAPPING.md](../docs/architecture/TECHNOLOGY_MAPPING.md) §4–5) | TimescaleDB hypertables for `historical_data`'s immutability, Redis for `cache_transient`'s disposability |

Each `data/*` category's README states the lifecycle semantics
`infrastructure/persistence` must respect (immutable/append-only, disposable/
recomputable, durable/consistency-critical, etc.) — the physical technology
choice is downstream of and constrained by that semantic, never the reverse.

## Depends On

domain

## Must Not Depend On

Being coupled to persistence implementation details (PostgreSQL/TimescaleDB/Redis are `infrastructure/persistence`'s concern, not this layer's — see TECHNOLOGY_MAPPING.md §4)

