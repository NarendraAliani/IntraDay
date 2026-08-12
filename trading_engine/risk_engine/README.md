# trading_engine/risk_engine

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Centralized Risk Engine that every signal must pass through before order creation (Rule 5.2, non-bypassable).

## Depends On

domain/risk, domain/signal, domain/portfolio

## Must Not Depend On

Any strategy-specific logic

