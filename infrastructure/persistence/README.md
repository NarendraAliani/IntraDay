# infrastructure/persistence

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Concrete storage technology implementations for the logical boundaries defined in data/. Technology locked at Checkpoint 3: PostgreSQL (system of record) + TimescaleDB extension (historical/time-series market data) + Parquet files (bulk research datasets) + Redis (cache_transient only) — see [TECHNOLOGY_MAPPING.md](../../docs/architecture/TECHNOLOGY_MAPPING.md) §4.

## Depends On

domain, data

## Must Not Depend On

Strategy/domain logic depending back on it directly (must go through repository interfaces in domain)

