# communication

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

E. Communication Layer bounded context. Sole owner of outbound notification delivery via adapters (Rule 5.1: strategies never call Telegram/Discord/WhatsApp directly).

## Depends On

domain/shared_kernel, control_plane/alerts (as a consumer of contracts)

## Must Not Depend On

Strategy logic, risk engine internals

