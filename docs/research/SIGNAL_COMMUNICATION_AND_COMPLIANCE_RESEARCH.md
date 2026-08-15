# Signal Communication & Compliance Research (Checkpoint 37 Part 2)

Confidence tags: `VERIFIED_PRIMARY` (fetched directly from the
authoritative source), `VERIFIED_SECONDARY` (corroborated via
reputable secondary sources; primary not directly fetched this
session), `UNKNOWN`.

## A. Dhan order lifecycle API — re-confirmed, one new fact

Prior checkpoints (33/34) already fetched Dhan's order-lifecycle
documentation directly (`VERIFIED_PRIMARY`) and it remains the
authoritative source for `EXECUTION_RESEARCH.md`'s findings — not
re-fetched again this checkpoint to avoid duplicating work.

**New this checkpoint** (`VERIFIED_SECONDARY`, via `dhan.co/support` and
`docs.dhanhq.co/api/v2/guides/rate-limits`):

- **Order modification limit**: each order can be modified **up to 25
  times** — a hard ceiling this project's `OrderIntent`/order-lifecycle
  handling does not currently track or enforce (no code path counts
  modification attempts). Relevant only once order MODIFICATION is
  implemented (currently: only submission and cancellation-adjacent
  concepts exist in the domain model).
- **Rate limits** (per-second, per API category): Non-trading APIs 20
  req/s; **Order APIs 10 req/s**; Data APIs 5 req/s; Quote APIs 1
  req/s. No rate-limiting/backoff logic exists anywhere in
  `infrastructure/brokers/dhan` today — a real concern for a future
  `DhanBroker` adapter under any burst-order scenario (a strategy
  producing many signals in the same evaluation tick), not yet a
  concern for `PaperBroker` (in-memory, no external rate limit).

## B. SEBI algo trading framework — CRITICAL, previously untracked finding

**`VERIFIED_SECONDARY`** — multiple reputable trading-industry sources
(Angel One, AlgoBulls, TradeJini, uTradeAlgos) independently report the
same timeline and provisions; the primary SEBI circular itself was not
directly fetched this session. **This finding should be verified
against the primary SEBI circular before any real-order capability is
built**, but given the current date (2026-08-15) is well past the
reported deadlines, it cannot be dismissed as speculative.

Reported facts:

- SEBI's retail algo-trading framework became **mandatory for all
  stock brokers in India on 2026-04-01** — a date that has already
  passed as of this checkpoint.
- **Every order placed by an algorithm must carry an exchange-assigned
  Algo-ID**, letting exchanges trace every automated order back to its
  source strategy.
- **Brokers are responsible for every algo running through their
  platform** — an algo provider (this project, if it ever executes
  real orders) cannot connect directly to an exchange; it must operate
  through a broker (Dhan) that has registered the strategy.
- A **10 orders/second (per exchange, per calendar second) threshold**
  exists below which no formal algo registration is required; above
  it, the strategy must be registered through the broker.
- Providers of "black box" algos must hold a **SEBI Research Analyst
  (RA) license** and disclose performance metrics periodically.
- **API access requires a whitelisted static IP, mandatory 2FA via
  OAuth-based login, and a daily automatic logout before the next
  market pre-open** — the static-IP requirement corroborates this
  project's own prior finding (`DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md`)
  that live/order APIs need a static IP, now with an explicit
  regulatory (not just Dhan-operational) basis.

### Why this matters to THIS project specifically

Nothing in `trading_engine/broker_abstraction`, `domain.order`, or any
other module currently has a concept of an "Algo-ID," strategy
registration status, or a broker-side registration check. **This is a
new, previously-undocumented P0-class blocker for real order placement**
that existed before this checkpoint but was not tracked anywhere in
this project's gap registers, because no prior checkpoint's research
looked specifically at SEBI's algo framework. It is added to
`ACTIVE_PRODUCT_GAP_REGISTER.md` (Checkpoint 36) as a new P0 row this
checkpoint, since gap registers are living documents.

**This does not block PAPER trading** — PAPER mode never reaches a real
exchange and has no Algo-ID to carry. It is a hard blocker for any
future LIVE-trading checkpoint, and should be verified against SEBI's
actual circular text (not secondary sources) before that checkpoint is
attempted.

## C. Production trading-system operational practices — applied, not re-researched

This checkpoint's Part 3-7 implementation (the Signal Communication
Engine) directly applies two of the operational practices Part 2(D)
names, using patterns already established in this project rather than
new research:

- **Idempotency**: `(signal_id, event_id, channel)` as the
  communication-ledger dedup key — the same pattern this project
  already uses for order idempotency keys (Checkpoint 5) and
  deterministic backtest/signal IDs (Checkpoints 27, 36).
- **Auditability**: every delivery attempt (sent, failed, or
  duplicate-skipped) is persisted, never silently dropped — mirrors
  this project's existing "every risk decision is recorded, even on
  rejection" discipline (`domain.risk.RiskDecision`).

Retry policies, clock synchronization, and disaster/restart recovery
for the communication engine specifically were **not** implemented this
checkpoint (see `ACTIVE_PRODUCT_GAP_REGISTER.md` — communication-ledger
retry logic is `MISSING`, `retry_count` is tracked as a field but never
incremented by any automatic retry loop, since none exists).
