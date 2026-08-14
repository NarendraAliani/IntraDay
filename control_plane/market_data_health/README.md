# control_plane/market_data_health

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Detects stale/missing/anomalous market data feeds.

## Depends On

domain/market_data

## Must Not Depend On

Strategy logic

## Checkpoint 23 update

`src/intraday/control_plane/market_data_health/` now has real content:
`contracts.py` (the `MarketDataHealthState` vocabulary - `CONNECTED_FRESH`/
`CONNECTED_STALE`/`DISCONNECTED`/`AUTHENTICATION_FAILED`/`ERROR`/
`MARKET_CLOSED`) and `evaluator.py` (a pure classification function).
Supervisory only, per this README's own original responsibility - it
detects stale/missing feed conditions, it never generates a signal or
makes a trading decision. See
[LIVE_MARKET_DATA_ARCHITECTURE.md](../../docs/architecture/LIVE_MARKET_DATA_ARCHITECTURE.md)
for the full health model.

