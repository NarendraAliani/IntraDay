# Task Report

## Checkpoint

Checkpoint 64.1 — Live Market-Data Runtime Implementation + Recovery +
Watchdog + Dynamic Subscription (partial) + Paper Signal Pipeline (not
reached). This file OVERWRITES the previous `taskReport.md` per this
checkpoint's own instruction.

## Objective

Per the explicit directive: do not wait for a fresh Dhan token to
implement everything that can be built and tested deterministically.
Implement the production Dhan provider path, connection state handling,
reconnect-with-backoff, a watchdog, and move toward the dynamic
subscription/live signal pipeline — without ever placing a real order.

**Honest scope statement up front**: the full 27-section brief remains
genuinely multi-week work. This checkpoint implemented the highest-
leverage, most foundational pieces that were both (a) directly enabled by
Checkpoint 64's own findings and (b) genuinely completable and testable
without a live connection. It did NOT reach the dashboard, live-scanner
UI wiring, event-driven communication, new reports, full-day simulation,
or performance benchmarking — each named explicitly below, not silently
dropped.

## Previous Checkpoint Findings

From Checkpoint 64 (unchanged, re-confirmed, not repeated live this
round per the explicit "do not repeatedly attempt live connections with
an expired token" instruction):
1. The real Dhan WebSocket endpoint (`wss://api-feed.dhan.co`) is reachable — the RFC 6455 handshake genuinely succeeded.
2. The transport (`DhanWebSocketTransport`) works against the real endpoint, not just a local test server.
3. This environment's configured Dhan access token is EXPIRED (verified by decoding its own `exp` claim).
4. The Settings page's "Connected" badge was stale relative to that real expiry — fixed with a live token-state evaluator.
5. The live-quote universe is no longer architecturally capped at 4 symbols (scrip-master fallback added).

## Readiness Gate

Re-traced against the code AFTER this checkpoint's own changes:

| Component | Exists | Tested | Integrated | Notes |
|---|---|---|---|---|
| Real Dhan provider (`--provider dhan`) | **New this checkpoint** | Yes (credential/token-gating refusal paths — never a real network call in tests) | Yes (`manage.py run_market_data_worker`) | Market data only; refuses to connect without a usable token |
| Connection state machine | Pre-existing (Checkpoint 53's `WorkerState`) | Yes | Yes, reused unmodified | Already matched Checkpoint 64.1's own requested vocabulary almost exactly — no new state machine was built, the existing one was reused |
| Token lifecycle (extended) | Extended this checkpoint | Yes (26 tests total across both token files) | Partial (Settings API/UI show the claims-only states; renewal is not auto-invoked anywhere yet) | `RENEWED`/`AUTH_FAILURE`/`OPERATOR_ACTION_REQUIRED` added; real `/v2/RenewToken` client built and unit-tested (never exercised against a real active token — none exists in this environment) |
| Reconnect-with-backoff | **New this checkpoint** | Yes (6 tests, deterministic fake sleep/transport) | Yes (wraps `--provider dhan`) | Bounded exponential backoff + jitter; never retries an unrecoverable auth/token failure |
| Watchdog | **New this checkpoint** (`control_plane/market_data_watchdog`) | Yes (10 tests) | **No** — not yet wired into the running worker's own loop to produce a live snapshot; the evaluator exists and is correct, nothing calls it periodically yet | Pure evaluator only |
| Dynamic subscription manager | Partial (Checkpoint 64 widened symbol resolution) | Yes | Partial — `--provider dhan` now subscribes to the FULL configured `observation_universe()` (capped at Dhan's documented 100-per-message limit) | Still NOT watchlist/strategy-universe-driven — no UI selection propagates to it |
| Live signal pipeline wiring | Unchanged | — | **No** | `_QuoteSink` persists quotes/bars; nothing calls the strategy/risk/paper pipeline from the live worker yet |
| Operator dashboard | Unchanged | — | No | Not built |
| Reports | Unchanged | — | No | Not built |
| Full-day simulation | Unchanged | — | No | Not built |
| Performance benchmarking | Unchanged | — | No | Not attempted |

## Implementation

### Real Dhan Provider
`manage.py run_market_data_worker --provider dhan` (new). Reuses the
EXISTING `DhanWebSocketTransport`/`packet_decoder`/`packet_to_quote`/
`BarAggregationService`/`_QuoteSink` pipeline verbatim — no second
WebSocket implementation. Builds the real Dhan URI
(`wss://api-feed.dhan.co?version=2&token=...&clientId=...&authType=2`,
verified against Dhan's own docs at Checkpoint 64) and sends the real
documented subscribe request (`RequestCode: 15`) for the full configured
`observation_universe()`, capped at Dhan's documented 100-instruments-
per-message limit (subscribing more than 100 in one message is a named,
undone gap — see Remaining Gaps). **Market data only** — this command
has no code path to any order-placement API, mechanically verified by
the pre-existing `test_live_market_data_boundaries.py` (re-run this
checkpoint, still passing, still scans this entire directory).

**Refuses to connect at all** if: (a) no Dhan credentials are configured, or (b) the token's own claims report anything other than `VALID`/`EXPIRING_SOON`. Both refusal paths are unit-tested (a real, well-formed-but-expired JWT is used to prove case (b) — never a real network call).

### Connection State Machine
Not rebuilt. Checkpoint 53's existing `WorkerState`/`WorkerEvent`/
`apply_event()` already covers almost exactly the vocabulary this
checkpoint's own brief asked for (`STARTING`/`CONNECTING`/`RUNNING`/
`DEGRADED`/`RECONNECTING`/`AUTH_FAILED`/`TOKEN_EXPIRED`/`STOPPING`/
`FAILED`, plus an exhaustive legal-transition table and an
`UNTRUSTWORTHY_STATES` set) — reused verbatim by the new reconnect
supervisor, never duplicated.

### Token Lifecycle
Extended `TokenLifecycleState` with `RENEWED`, `AUTH_FAILURE`,
`OPERATOR_ACTION_REQUIRED` (no `RENEWING` — no async job exists for it,
adding an unreachable state was rejected as dishonest). New
`attempt_dhan_token_renewal()` orchestrates: `EXPIRED`/`MALFORMED`/
`UNCONFIGURED` → `OPERATOR_ACTION_REQUIRED` (never attempts renewal —
Dhan's own docs say renewing an expired token always fails);
`EXPIRING_SOON` → attempts a real renewal call via an injected
`TokenRenewer` Protocol → `RENEWED` or `AUTH_FAILURE`. The real Dhan
`/v2/RenewToken` client (`token_renewal_client.py`) is built and unit-
tested against the documented response shape — **never exercised
against a real active token**, since this environment's only configured
token is already expired and Dhan's endpoint is documented to reject
renewal of an expired one. Not wired into any scheduled task or UI
button yet (see Remaining Gaps).

### Reconnect
New `reconnect_supervisor.py::run_worker_with_reconnect()` — a
transport-agnostic outer loop around one connection attempt at a time
(`connect_and_run: Callable[[], Awaitable[AsyncWorkerRunResult]]`).
Bounded exponential backoff with jitter
(`min(initial * 2**(attempt-1), max) * (0.5 + jitter*0.5)`), a hard
`max_attempts` cap, and an explicit refusal to ever retry an
unrecoverable state (`AUTH_FAILED`/`TOKEN_EXPIRED`/`FAILED`) — proven
directly by a test that fails the connection with `TOKEN_EXPIRED` and
asserts `connect_and_run` was called exactly once. A `stop_event` set
mid-backoff stops immediately without a further attempt.

### Watchdog
New bounded context `control_plane/market_data_watchdog` (deliberately
separate from the pre-existing `market_data_health`, which is scoped to
the REST-polling refresh pattern and cannot express packet/quote/bar-
level continuous-worker staleness). Pure evaluator,
`evaluate_market_data_watchdog()`: precedence token-unusable → FAILED,
connection-state FAILED → FAILED, connection-state
disconnected/reconnecting/stopping → DISCONNECTED, no packet ever
received → DISCONNECTED, packet older than 30s (chosen inside Dhan's
own documented 40s hard-close window) → STALE, no bar ever closed or
bar older than a configurable threshold → DEGRADED, otherwise HEALTHY.
**Not yet wired into the running worker** — the evaluator exists and is
tested, but nothing in `run_market_data_worker.py` calls it periodically
to produce a live snapshot yet (see Remaining Gaps).

### Subscription Manager
Partial. `--provider dhan` now subscribes to the entire configured
`observation_universe()` (real scrip-master-backed, per Checkpoint 64),
not a hardcoded 4-symbol list — capped at Dhan's documented 100-per-
message limit (a universe larger than 100 is truncated to the first 100
today, named as a real, undone gap, not silently handled). Still NOT a
dynamic, watchlist/strategy-universe-driven selector with an operator-
facing UI — that remains undone.

### Live Signal Pipeline
**Not implemented this checkpoint.** `_QuoteSink` still only persists
quotes and aggregates bars — nothing calls the strategy engine, risk
engine, or `PaperBroker` from the live worker. This is the single
largest remaining gap and the correctly-named next increment once the
provider/reconnect/watchdog foundation above is in place.

### Communication
Not implemented this checkpoint.

### Dashboard
Not implemented this checkpoint.

### Reports
Not implemented this checkpoint.

## Full-Day Simulation

Not built this checkpoint — still blocked on the live signal pipeline
above not existing yet; simulating a pipeline that doesn't route
signals would not be a genuine simulation.

## Failure Injection

Only the pieces that exist were tested against injected failure:
reconnect supervisor (network-loss-then-recovery, permanent failure,
unrecoverable auth failure, mid-backoff stop), watchdog (every state
transition), and the `--provider dhan` credential/token-gating refusal
paths. NOT tested: heartbeat timeout mid-connection, DB/Redis outage,
malformed/duplicate/delayed packets in the reconnect context (the
underlying decoder-level cases were already covered by pre-existing
Checkpoint 53/57 tests, not re-covered here), worker restart.

## Performance Measurements

Not attempted this checkpoint (still explicitly out of scope until the
live signal pipeline exists — measuring latency through a pipeline that
doesn't yet route signals would not produce meaningful numbers).

## Tests

- Backend: **1342 passed** (up from 1314 — 28 new/changed: 8 watchdog, 6 reconnect supervisor, 8 token-lifecycle/renewal orchestration, 5 renewal-client, 2 dhan-provider-refusal in the management command test file, plus the existing unsupported-provider test updated since `dhan` is now a real choice).
- `ruff format --check` / `ruff check`: clean.
- `mypy src/`: clean, 278 source files.
- `lint-imports`: 6/6 contracts kept (the new `market_data_watchdog` bounded context and the new infrastructure modules all respect the existing layering).
- `python manage.py check`: clean.
- `python manage.py makemigrations --check --dry-run`: no changes (no model fields changed this checkpoint).
- No test was weakened to pass; the one pre-existing test that needed changing (`test_command_rejects_an_unsupported_provider`) needed it because `dhan` genuinely became a supported value, not because a real behavior was removed.
- Frontend: unchanged this checkpoint (no frontend work was done) — the 127 tests from Checkpoint 64 remain valid and were not touched.

## Real Dhan Verification

**Deliberately NOT repeated this checkpoint**, per the explicit
instruction not to repeatedly attempt live connections with a known-
expired token. `--provider dhan`'s credential/token-gating refusal logic
was proven with a real, well-formed-but-expired JWT fixture (never a
real network call) — this is the correct, bounded way to prove "the
worker refuses to pretend it is connected" without needing a live
connection attempt. `REAL-DHAN-VERIFICATION = BLOCKED` (unchanged from
Checkpoint 64 — configured token still expired). When a fresh token is
available, `python manage.py run_market_data_worker --provider dhan` is
now the real, ready-to-run command to perform that verification through
— nothing further needs to be built first to attempt it.

## Blockers

1. **The configured Dhan access token remains expired** (unchanged from Checkpoint 64) — `--provider dhan` will correctly refuse to connect until a fresh token is configured. This is now a real, working refusal, not a missing capability.
2. The live signal pipeline (bar → strategy → signal → risk → paper order) is not wired to the live worker — even with a fresh token, a live connection today produces persisted quotes/bars only, not paper trades.
3. The watchdog is not yet wired into the running worker's own loop — it exists and is correct but produces no live snapshot yet.

## Remaining Gaps

Named explicitly, not silently dropped:
- Live signal pipeline wiring (bar → strategy → risk → PaperBroker from the live worker) — the single largest remaining gap.
- Watchdog wired into the actual running worker loop (periodic snapshot + an API endpoint/UI surface).
- Dynamic, watchlist/strategy-universe-driven subscription selection with an operator-facing UI (today: the full configured universe, capped at 100 instruments, with no UI control).
- Subscribing to more than 100 instruments (would need batching into multiple subscribe messages — not implemented).
- Automatic token renewal actually invoked on a schedule or from a UI action (the renewal client + orchestration exist and are tested; nothing calls them yet).
- Signal/execution separation as a first-class communication model.
- Event-driven (SignalGenerated → ... → PositionClosed) communication architecture.
- Real-time operator dashboard.
- User-controlled live scanner UI wired to the runtime.
- Full-day deterministic paper session simulation with injected disconnect.
- Gap reconciliation on reconnect (using the existing DB-first historical pipeline to backfill a disconnect gap) — not attempted.
- Performance/load testing at any scale.
- Full-signal latency tracing (tick → notification timestamp chain).
- New report types (Signal Report, Paper Trading Report, Risk Decision Report, System Health Report, Daily Session Report).

## Production Readiness

**"Can I start this before market open, leave it running in PAPER mode,
and trust it to connect to Dhan, detect stale data, recover from
disconnects, generate real signals, apply risk, create paper trades,
publish signals, maintain positions, reconcile, complete EOD?"**

**Answer: NO.**

Exact blockers, in priority order:
1. The configured Dhan credential is expired — no live connection is possible until a fresh token is configured (unchanged from Checkpoint 64, now correctly and safely REFUSED rather than silently attempted).
2. Even with a fresh token, the live worker does not yet call the strategy/risk/paper pipeline at all — a live connection today would persist quotes and bars, not generate paper trades.
3. The watchdog exists but is not wired into the running worker to produce a live health signal an operator or dashboard could actually see.
4. No operator dashboard or live-scanner UI exists to control or observe any of this.

## Performance Ranking

| Area | Previous score | Current score | Change | Evidence / remaining gap |
|---|---:|---:|---|---|
| Architecture | 9.2 | 9.3 | ↑ | New bounded context (watchdog) added cleanly, respecting existing layering; reconnect supervisor is genuinely transport-agnostic, reused nothing duplicated |
| Market Data (real feed) | 3.5 | 4.5 | ↑ | Real provider now exists and is wired into the actual worker command; still never received real data (token expired) |
| Dhan Integration | 3.5 | 5.0 | ↑ | Real WebSocket connect proven (Checkpoint 64); real RenewToken client built (untested against a live token); real production provider now callable |
| Historical Data | 7.5 | 7.5 | — | Unchanged this checkpoint |
| Backtesting | 8.0 | 8.0 | — | Unchanged |
| Bar Engine | — | 6.0 | new | Aggregation logic unchanged and real, but still only ever fed synthetic/local data |
| Strategy Engine | 8.0 | 8.0 | — | Unchanged; still not reachable from the live worker |
| Signal Pipeline (live) | — | 1.0 | new | Exists for backtesting only; zero live wiring |
| Risk Engine | 8.5 | 8.5 | — | Unchanged; still not reachable from the live worker |
| Paper Trading | 8.5 | 8.5 | — | Unchanged; still not reachable from the live worker |
| Communication | — | 2.0 | new | Existing Telegram/Discord infra real (pre-session); no live/event wiring |
| Token Lifecycle | 2.5 | 5.5 | ↑ | Real evaluator + real (untested-live) renewal client + orchestration, all tested; not yet auto-invoked anywhere |
| Reconnect | 3.0 | 6.0 | ↑ | Real, tested, bounded backoff supervisor now exists and is wired into `--provider dhan`; never exercised against a real disconnect (no live connection reached RUNNING) |
| Watchdog | 2.0 | 4.5 | ↑ | Real, tested pure evaluator exists; not wired into any running process yet |
| Observability | 4.5 | 4.5 | — | No new API/UI surface added for any of this checkpoint's new signals |
| Frontend | 7.0 | 7.0 | — | Untouched this checkpoint |
| Reports | 4.5 | 4.5 | — | Unchanged |
| Performance | 2.0 | 2.0 | — | Not attempted |
| Scalability | 2.0 | 2.0 | — | Not attempted; 100-instrument subscribe cap now a known, real limit |
| Security | — | 8.0 | new | No secret ever printed/logged/committed this checkpoint either; renewal client headers verified against docs, never logged |
| Production Readiness | 4.5 | 4.5 | — | Still blocked on the same fundamentals |
| Active Paper Trading | 5.8 | 5.8 | — | Unchanged — live wiring is what would move this |
| Live Trading Readiness | 1.0 | 1.0 | — | By design — real order placement remains untouched |

Scores did not increase merely because code was added — Reconnect,
Watchdog, and Dhan Integration moved up because each now has real,
tested, wired-in behavior reachable from the actual production command,
not just a design. Strategy/Risk/Paper/Backtesting stayed flat because
nothing about them changed. Live Trading Readiness stayed at 1.0
deliberately.

## Honest Final Conclusion

This checkpoint moved the live-market-data runtime from "transport
proven reachable" (Checkpoint 64) to "a real, safe, reconnect-capable,
credential-aware production provider exists and is wired into the actual
operator command" — genuinely new, tested capability, not a repeat of
the readiness gate. What it did NOT do, honestly: connect the live
worker to the strategy/risk/paper pipeline at all (the single largest
remaining gap), wire the watchdog into a running process, build any
operator-facing dashboard or live-scanner control, or attempt
performance/load testing. The correct next increment, now that this
foundation exists, is the live signal pipeline wiring — everything
downstream of it (strategy, risk, paper broker, position management,
reconciliation, EOD) already exists and is tested; it needs to be
CALLED from `_QuoteSink`'s bar-aggregation output, not rebuilt.
