# communication/adapters/discord

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Discord webhook/bot adapter (implementation deferred to a future checkpoint; interface only so far). Runs within the locked Django/Celery stack (dispatched as a Celery task against `communication/contracts`) — see [TECHNOLOGY_MAPPING.md](../../../docs/architecture/TECHNOLOGY_MAPPING.md) §2, §5.

## Depends On

communication/contracts

## Must Not Depend On

Trading logic

