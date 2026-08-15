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
  real, wired kill-switch controls - Checkpoint 35 closed this gap,
  see below.

## Checkpoint 35 update — the loop closed

Every gap named above at Checkpoint 34 was addressed this checkpoint,
except one deliberately deferred item:

- **Automatic ledger persistence: DONE.** `application/services/paper_trading.py::PaperTradingService`
  now accepts an optional `ledger` (`application/repositories/paper_ledger.py::PaperLedgerRepository`)
  and resyncs the FULL current broker state (order + events, every
  trade, every position, funds) after every `submit_order()` call, in
  one atomic transaction (`infrastructure/persistence/paper_ledger_repository.py::DjangoPaperLedgerRepository`).
  Proven with dedicated tests: persistence, reload via a brand-new
  repository instance (simulating a process restart), duplicate-sync
  idempotency, and "ledger is optional, never required."
- **Frontend order submission: DONE.** `PaperTradingPage.tsx` has a
  real order-entry form (MARKET/LIMIT/SL/SL-M, instrument/side/
  quantity/limit/trigger/strategy) wired to `POST .../paper-trading/orders/submit/`.
- **Order/trade/position/funds monitor: DONE.** Real, persisted-data
  tables reading `GET .../paper-trading/{orders,trades,positions,funds}/`.
- **`instrument_id` on `BrokerOrderStatusReport`: DONE.** Added to the
  domain contract; `PaperBroker`/`PaperTradingService` both updated;
  the risk engine's `instruments_with_pending_or_open_orders` check is
  now correctly populated (4 new tests: same-instrument-blocks,
  different-instrument-allowed, filled/cancelled-no-longer-blocks,
  different-idempotency-keys-cannot-bypass).
- **Scheduled end-of-session expiry: PARTIALLY DONE.** The underlying
  function (`PaperBroker.force_expire_end_of_session()`, Checkpoint 34)
  is now exposed via `POST .../paper-trading/expire-session/` and
  persists the resulting state - genuinely usable and tested
  (`test_expire_session_expires_pending_orders`). **What remains
  undone**: no scheduler (Celery beat or equivalent) calls this
  automatically at the market-session boundary - it must be manually
  triggered. This is a direct consequence of the still-unresolved
  Checkpoint 32 runtime-architecture decision (a persistent worker
  process is designed, not implemented) - see
  `docs/architecture/RUNTIME_ARCHITECTURE_DECISION.md`.
- **Live market-data feed into `record_price()`: NOT DONE, by
  deliberate decision, documented per Part 8's own explicit
  instruction.** `PaperBroker.record_price()` remains callable by any
  caller with a real price - this checkpoint did NOT wire the existing
  live quote/bar pipeline (Checkpoints 23-24A) to call it
  automatically. **Reasoning:** that pipeline produces `SAMPLE_BAR`-
  quality data (Checkpoint 25.1/31), and Part 8 explicitly warned
  "do NOT promote SAMPLE_BAR to TRADING_GRADE_BAR merely because paper
  trading needs prices." Wiring it automatically would create an
  implicit, easy-to-miss coupling between an admittedly-imperfect data
  source and the paper broker's fills - acceptable for occasional
  manual/test use (which is how this checkpoint's own test suite and
  the order-entry form's notional-estimate logic use `get_latest_price()`),
  but a genuine automatic feed deserves its own reviewed design (retry/
  staleness/gap handling, mirroring the live-market-data health model
  already built for observation) rather than a quick wire-up under this
  checkpoint's time constraints. **Data used today**: whatever value a
  caller (a test, or an operator manually recording a reference price)
  passes to `record_price()` - explicitly NOT a continuous, automatic
  subscription. **Never used for anything but paper simulation** - no
  code path connects this to LIVE execution, which does not exist.

None of the remaining gaps (unscheduled expiry, no automatic price
feed) allow a real order to be placed — every safety rule this project
operates under remains intact.

## Checkpoint 36 update — strategy-driven paper orders, deliberately not auto-triggered

`application/services/paper_signal_execution.py::PaperSignalExecutionService`
adds the missing last mile: turning one `StrategySignal` (produced by the
existing `StrategyExecutionCoordinator`, Checkpoint 26 — reused verbatim,
never a parallel evaluation framework) into a risk-gated
`PaperTradingService.submit_order()` call, with a deterministic
`signal_id` giving full lineage (strategy version -> signal_id -> order_id
-> trade_id/position_id; see `docs/research/STRATEGY_TO_PAPER_SELECTION.md`
for the complete design and evidence).

**Deliberately NOT built this checkpoint: any automatic trigger.** Nothing
calls `evaluate_and_submit()` against live or aggregated bars on a
schedule or in response to a market-data event. Bars are supplied entirely
by the caller (today: only the test suite). This was a conscious decision,
not an oversight — building an automatic trigger means deciding where the
bars come from, and the only bar source that currently exists for live
instruments is the `SAMPLE_BAR`-quality aggregation pipeline referenced
above. Wiring that pipeline into an operator-triggerable strategy-
execution pathway without a dedicated design review (staleness handling,
what happens mid-evaluation if the feed gaps, how the market-data-quality
classification from Part 8 gets enforced rather than silently ignored)
would be exactly the "premature feature" this checkpoint's own governing
principle says to block. `PaperSignalExecutionService` is real, tested
backend capability; it is not yet a reachable operator or scheduled
action, and this document says so plainly rather than implying otherwise.
