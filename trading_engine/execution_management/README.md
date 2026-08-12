# trading_engine/execution_management

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Manages order execution mechanics: routing, retries, partial fills, slippage
tracking. Produces closed `domain/trade` records once a round-trip completes.
**Answers "was execution poor?"** — compares realized fill price/quantity/
timing (`domain/trade`) against the risk-approved intent (`domain/order`),
independent of whether the originating signal was itself correct (that
question belongs to `signal_intelligence/signal_verification`; see
Checkpoint 2 Section 5).

## Depends On

trading_engine/order_management, trading_engine/broker_abstraction, domain/trade

## Must Not Depend On

Strategy internals

