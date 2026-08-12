# scripts/data

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Data-pipeline utility scripts (e.g. instrument-master/exchange-calendar refresh triggers). Implementation deferred to later checkpoints (Celery Beat is the locked scheduling mechanism — see [TECHNOLOGY_MAPPING.md](../../docs/architecture/TECHNOLOGY_MAPPING.md) §5–6); no scripts exist yet.

## Depends On

domain/market_data

## Must Not Depend On

Trading logic

