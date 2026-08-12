# control_plane/kill_switch

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Global and per-strategy kill-switch authority; can halt trading_engine, cannot be bypassed by AI agents (Rule 5.7).

**Authority boundary, clarified at Checkpoint 2 (Section 10):** the Control
Plane's authority is strictly **binary and supervisory** — it may
stop/allow, disable/enable, and block/unblock — it must never *choose* what
to trade. Concretely, `control_plane/kill_switch` may: halt all trading,
disable an individual strategy (write access to
`trading_engine/strategy_registry`'s state field only, not its logic), block
new orders at `trading_engine/order_management`'s entry point, and act on
`control_plane/reconciliation` failures and `control_plane/market_data_health`
/ `control_plane/broker_health` signals. It must never generate a signal,
size a position, choose an order, or contain strategy logic — doing so would
make it a second trading engine, which is explicitly forbidden.

## Depends On

trading_engine/risk_engine, trading_engine/strategy_registry (state write only), trading_engine/order_management (block-new-orders entry point only), control_plane/reconciliation, control_plane/market_data_health, control_plane/broker_health

## Must Not Depend On

AI agent direct execution access; strategy/signal decision logic (kill_switch decides only whether trading continues, never what to trade)

