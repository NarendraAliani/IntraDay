# infrastructure/brokers

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Concrete broker adapter implementations of domain/broker; strategies never depend on this directly (Rule 5.3).

## Depends On

domain/broker, trading_engine/broker_abstraction

## Must Not Depend On

Strategy/signal logic

