# domain/broker

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Broker abstraction contract (interface) that concrete broker adapters must implement (Rule 5.3). Contains no Dhan-specific or any other broker-specific logic.

## Depends On

domain/shared_kernel, domain/order, domain/instrument

## Must Not Depend On

Dhan SDK, Zerodha SDK, Angel One SDK, or any concrete broker library

