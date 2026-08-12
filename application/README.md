# application

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Application/interface layer: orchestrates use-cases across bounded contexts and exposes contracts consumed by the frontend (Rule 13). Framework locked at Checkpoint 3: Django + Django REST Framework + Django Channels (see [TECHNOLOGY_MAPPING.md](../docs/architecture/TECHNOLOGY_MAPPING.md) §2).

## Depends On

domain, research, signal_intelligence, trading_engine, control_plane, communication

## Must Not Depend On

frontend implementation details, concrete database technology

