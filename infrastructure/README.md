# infrastructure

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Technology-specific adapters implementing domain interfaces (Rule 5.3). Technology locked at Checkpoint 3 — see [TECHNOLOGY_MAPPING.md](../docs/architecture/TECHNOLOGY_MAPPING.md): PostgreSQL/TimescaleDB + Redis for persistence, Celery for messaging/async, Dhan as first broker.

## Depends On

domain

## Must Not Depend On

Strategy logic, frontend

