# domain/trade

> Architecture placeholder — no business logic. Added during the Checkpoint 2 architecture review (Section 5: Signal vs Order vs Position vs Trade).

## Responsibility

Canonical Trade contract: a completed, closed round-trip execution outcome
(entry + exit, realized quantity, realized price(s), fees, realized P&L,
holding duration, linked order(s)/position(s), linked originating signal).
A Trade is distinct from a Signal (candidate decision), an Order
(risk-approved request), and a Position (point-in-time exposure) — it is the
*settled fact* of what actually happened, used to answer "was the execution
poor?" independently of "was the strategy wrong?" (signal_intelligence answers
the latter via theoretical outcome / signal verification). Needed identically
by research/backtesting (simulated trades), trading_engine (live trades) and
reporting — this is why it belongs in the shared kernel rather than inside
any single bounded context.

## Depends On

domain/shared_kernel, domain/order, domain/position, domain/signal (for the originating-signal reference)

## Must Not Depend On

Broker-specific execution report formats, strategy-specific logic
