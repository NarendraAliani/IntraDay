# Paper Trading Architecture

Checkpoint 34 Part 7-9/12. The first genuine, event-driven paper
trading engine this platform has — not a "signal → pretend buy" toy.

## Architecture

```
                 BrokerGateway (domain.broker, Protocol)
                    /      \
                   /        \
              PaperBroker   DhanBroker (future - not built)
```

`infrastructure/brokers/paper/broker.py::PaperBroker` structurally
implements `domain.broker.contracts.BrokerGateway` — the exact same
interface a future real Dhan adapter would implement:
`submit_order`/`cancel_order`/`modify_order`/`get_order_status`/
`get_orders`/`get_trades`/`get_positions`/`get_funds`/
`connection_state`. `application/services/paper_trading.py::PaperTradingService`
depends only on this Protocol, never on `PaperBroker` directly — it
would work unchanged against `DhanBroker` once one exists.

## Execution model (documented explicitly, never silently invented)

- **MARKET** orders fill immediately against the latest price observed
  via `record_price()` — analogous to the backtest engine's own
  next-bar-open rule (`research/backtesting/engine.py`), never the
  price at the moment a strategy *decided* to trade (which would be
  look-ahead). A MARKET order submitted before any price has been
  recorded for its instrument is **REJECTED**, never filled at a
  fabricated price.
- **LIMIT** orders remain `PENDING` until a subsequent `record_price()`
  observes a price at or better than the limit (BUY: `price <= limit`;
  SELL: `price >= limit`), then fill AT THE LIMIT PRICE — never a
  better price is fabricated.
- **STOP_LOSS_MARKET** orders remain `PENDING` until price crosses the
  trigger, then fill immediately at that price.
- **STOP_LOSS** (stop-limit) orders remain `PENDING` (even after
  triggering) until a price is both past the trigger AND fillable
  against the limit — proven adversarially by
  `test_stop_loss_limit_waits_for_fillable_price_after_trigger`
  (a gap-down past the trigger that does not also clear the limit
  price stays PENDING, triggered, not silently filled at a worse
  price).
- **Partial fills**: a configurable `partial_fill_ratio` (default `1`,
  full fill) applies to the REMAINING quantity on every fill attempt —
  geometric, not linear, so repeated partial fills asymptotically
  approach (never silently jump to) full.
- **Slippage**: a configurable flat `slippage_percent`, applied
  symmetrically against the trader (BUY pays more, SELL receives
  less) — the same style of flat-percentage MODEL ASSUMPTION already
  disclosed for backtesting (Checkpoint 27-29), reused, not
  reinvented.
- **Costs**: an injected `compute_cost(is_buy, notional) -> Decimal`
  callable — the caller (not this module) is expected to inject the
  SAME verified `IndianCashEquityIntradayCostModel` already used by
  backtesting (Checkpoint 29). `infrastructure.brokers.paper` never
  imports `research.backtesting.cost_model` directly — the injection
  pattern mirrors Checkpoint 26/27's own feature-computation
  injection, keeping bounded-context independence intact.
- **End-of-data handling**: `force_expire_end_of_session()` explicitly
  transitions every still-`PENDING`/`PARTIALLY_FILLED` order to
  `EXPIRED` — mirrors the backtest engine's own end-of-series
  force-close discipline (Checkpoint 27). Nothing is silently left in
  limbo. **Not yet wired to any scheduler** — see the Gaps section.

## Why Django-free and in-memory

`PaperBroker` holds all state (orders/trades/positions/funds/prices) in
plain Python objects, with zero Django dependency — mirrors every
other `infrastructure/brokers`/`infrastructure/market_data_providers`
client in this project (plain Python, framework-free). This makes it
trivially unit-testable without a database (19 tests,
`tests/unit/infrastructure/brokers/paper/test_paper_broker.py`, all
pass with zero DB fixtures) and mirrors how a real Dhan adapter's own
in-memory request/response handling would look.

**The persistent ledger is a separate concern** (Part 12's own "keep
Order/Trade/Position as distinct concepts"): `PaperOrderRecord`,
`PaperTradeRecord`, `PaperPositionRecord`, `PaperFundsRecord` (Django
models, migration `0010`) exist as the durable, queryable record —
the CALLER (a future API/scheduler) is responsible for persisting
whatever `PaperBroker` reports into these tables, exactly how a real
Dhan adapter's reported state would need to be persisted locally too.
**This checkpoint created the schema and the broker; it did not yet
wire automatic persistence between them** — see Gaps.

## Position / Trade bookkeeping

Reuses `domain.position.Position`/`domain.trade.Trade` verbatim
(Checkpoint 5) — never a paper-specific parallel shape. Opposite-side
fills correctly close (fully or partially) an existing position,
computing `realized_pnl` and recording a `Trade`; same-side fills
blend the average entry price. Proven by
`test_opposite_side_order_closes_position_and_records_trade`.

## Orchestration (risk-gated, never bypassable)

See `docs/architecture/RISK_ENGINE_ARCHITECTURE.md`'s "Orchestration
order" section — `PaperTradingService.submit_order()` is the ONE
non-bypassable entry point: kill switch → risk engine →
`PaperBroker.submit_order()`, mechanically proven by
`tests/unit/architecture/test_paper_trading_architecture_fitness.py`.

## What this checkpoint did NOT build (explicit, honest gaps)

- **No frontend order-submission control.** The Paper Trading page
  (`frontend/src/features/paper-trading/PaperTradingPage.tsx`) shows
  real, wired kill-switch controls and honest `CapabilityStatus`
  placeholders for everything else — no UI action constructs and
  submits an `OrderIntent` yet.
- **No automatic ledger persistence.** `PaperOrderRecord`/etc. exist as
  schema; nothing writes to them automatically after a
  `PaperTradingService.submit_order()` call yet.
- **No scheduled `force_expire_end_of_session()` trigger.**
- **No live market-data feed into `record_price()`.** A real
  integration would need to wire the existing (SAMPLE_BAR-quality)
  live quote/bar pipeline (Checkpoints 23-24A) into
  `PaperBroker.record_price()` — not done this checkpoint.
- **`BrokerOrderStatusReport` does not carry `instrument_id`** — so
  the risk engine's "instrument already has a pending order" check
  (`instruments_with_pending_or_open_orders`) is currently always
  empty when called from `PaperTradingService`; the idempotency-key
  check remains the real, enforced duplicate-order protection. Honestly
  disclosed in the service's own code comment, not silently ignored.

None of these gaps allow a real order to be placed — every safety rule
this checkpoint operated under remains intact.
