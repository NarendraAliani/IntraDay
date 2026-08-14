# control_plane

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

D. Production Control Plane bounded context. Owns operational safety, health, audit and kill-switch authority; independent of and able to halt trading_engine.

## Depends On

domain, trading_engine (observes, does not implement strategy logic)

## Must Not Depend On

research, signal_intelligence internals

## Checkpoint 32 update

Real code for this bounded context lives at `src/intraday/control_plane/`
(this top-level directory remains the original Checkpoint-1 file-structure
placeholder). `market_data_health/` gained no new code this checkpoint;
its existing evidence was structured into
`application/reporting/market_data_quality_report.py`'s
`SYSTEM_HEALTH_REPORT`/`MARKET_DATA_QUALITY_REPORT` catalogue entries -
see [docs/architecture/REPORTING_ARCHITECTURE.md](../docs/architecture/REPORTING_ARCHITECTURE.md).

