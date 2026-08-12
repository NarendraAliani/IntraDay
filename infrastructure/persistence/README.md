# infrastructure/persistence

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Concrete storage technology implementations for the logical boundaries defined in data/. Technology locked at Checkpoint 3: PostgreSQL (system of record) + TimescaleDB extension (historical/time-series market data) + Parquet files (bulk research datasets) + Redis (cache_transient only) — see [TECHNOLOGY_MAPPING.md](../../docs/architecture/TECHNOLOGY_MAPPING.md) §4.

**Implemented at Checkpoint 7:** `src/intraday/infrastructure/persistence/`
is now a real Django app (`models.py`, `repositories.py`, migrations) —
the only place in the codebase where Django ORM rows are translated to/from
domain and application dataclasses. Implements the Protocol interfaces
declared in `application/repositories`. See
[PERSISTENCE_ARCHITECTURE.md](../../docs/architecture/PERSISTENCE_ARCHITECTURE.md).

## Depends On

domain, data, application/repositories (implements its Protocol interfaces), application/config_schema (RiskConfigurationRecord)

## Must Not Depend On

Strategy/domain logic depending back on it directly — must go through the repository interfaces in `application/repositories`, never call this package's Django models directly (mechanically enforced by `.importlinter` contract #6: application must not depend on infrastructure)

