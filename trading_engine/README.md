# trading_engine

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

C. Trading Engine bounded context. The only path from a validated signal to a broker order; centralizes risk (Rule 5.2).

## Depends On

domain, signal_intelligence, infrastructure/brokers (via abstraction only)

## Must Not Depend On

research internals, communication provider SDKs

