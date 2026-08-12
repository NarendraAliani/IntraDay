# trading_engine/order_management

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Owns canonical order lifecycle from risk-approved intent to broker submission.

## Depends On

domain/order, trading_engine/risk_engine

## Must Not Depend On

Concrete broker SDKs (only via broker_abstraction)

