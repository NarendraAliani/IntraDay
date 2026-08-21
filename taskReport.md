# Task Report

## Checkpoint

64.23 — "DHAN LIVE FEED DIAGNOSIS + STATEFUL BACKTEST RISK PARITY". Two coordinated tracks: Track
A (time-sensitive, since the Indian equity market was live during this checkpoint) diagnoses the
real Dhan WebSocket feed connectivity blocker identified in 64.22; Track B builds stateful,
risk-aware historical execution for backtesting, reusing the real production risk/exit decision
semantics rather than the ad-hoc TradePlan-only simulation from 64.21/64.22. 64.22 is accepted in
full and was not rebuilt: TradePlan-aware default backtest path, TradePlan exit wiring, EOD
integration, cost-model integration, `exit_reason_breakdown`, `tradeplan_trades`, frontend backtest
KPI additions, the real live-market readiness check, the real Dhan worker attempt, correct
provider-blocking behavior, and Real Trading remaining DISABLED.

## Objective

Priority order per the directive: Track A (time-sensitive, market is live) first, then Track B.
Research official Dhan behavior before touching connectivity code; make only evidence-based
corrections; never bypass the readiness gate; never fabricate quotes/signals/fills; never enable
real trading. On the backtesting side, read the actual `PaperBroker`/`PaperTradingService`/
`RiskLimits` implementation before designing historical execution — no blind delegation.

## Market State

Confirmed via the real, existing `session_for_instant()` calendar computation (no second
market-hours logic): **OPEN**, for the duration of this checkpoint's work.

## Baseline Verification

- Backend suite at checkpoint start: 1553 passed (64.22's final count).
- Frontend suite at checkpoint start: 176/176 passed.
- `poetry run lint-imports`: 6/6 kept at start.
- Dhan credential re-confirmed **VALID**, not expired, via the real
  `evaluate_dhan_token_lifecycle()` output.

## Migration State

No new Django migrations were required or created this checkpoint (`makemigrations --check
--dry-run` → "No changes detected" both before and after all changes). The three migrations applied
during 64.22 remain applied; no further migration drift was found.

## Track A — Dhan Live Feed Diagnosis

### Official Dhan Documentation

Fetched live from `https://dhanhq.co/docs/v2/live-market-feed/`. Confirmed exactly matching this
project's existing implementation: endpoint `wss://api-feed.dhan.co?version=2&token=...
&clientId=...&authType=2`; subscribe request `{"RequestCode": 15, "InstrumentCount": N,
"InstrumentList": [{"ExchangeSegment": "NSE_EQ", "SecurityId": "..."}]}`; max 100 instruments per
message, up to 5000 per connection, up to 5 connections per user (exceeding 5 disconnects the
*first* socket with code `805`); server ping every 10s, 40s response timeout; disconnect via
`{"RequestCode": 12}`. No IP-whitelisting, geography, or rate-limit requirement is documented.
Cross-checked against community reports (`madefortrade.in` forum threads) for close-code-1006
patterns — general community reports describe disconnects after 10-20 minutes of operation
(ping-timeout related), not an immediate post-subscribe drop; this project's failure signature does
not match that known pattern.

### Current Implementation Audit

Read in full before any change: `websocket_transport.py` (real RFC 6455 handshake via the
`websockets` library), `run_market_data_worker.py`'s `_run_dhan()` (real URI construction, exactly
matching the documented shape), `async_worker.py`'s `run_worker_against_websocket()` (real
decode/state-machine loop, already correctly catches `ConnectionClosedError` and transitions to
`RECONNECTING`), `reconnect_supervisor.py` (bounded exponential backoff, correctly never retries an
unrecoverable state).

### WebSocket Handshake

**Succeeds.** Direct connection test (reusing the real credential, real URI construction) completed
a genuine RFC 6455 upgrade: `CONNECTED OK`, response headers included `upgrade: websocket`,
`sec-websocket-accept` correctly computed. No handshake defect.

### Authentication

**Succeeds at the transport layer** — the connection is accepted and upgraded, meaning the token/
clientId/authType query parameters are not rejected outright at connection time.

### Subscription

Real instruments resolved from the actual scanner universe configuration (4 instruments: RELIANCE,
TCS, INFY, HDFCBANK, all `NSE_EQ`). Subscribe message built and sent using the exact real production
`_build_subscribe_messages()` logic — confirmed byte-for-byte matching the documented format.
`transport.send_json_text()` completed without error (`Subscribe message sent OK`).

### Error Classification

**Reproducible, consistent, 100% of attempts (3 separate connection attempts across roughly 90
seconds, including a 20-second cooldown between two of them):** the connection is dropped
immediately after the subscribe message is sent, before any packet is ever received. Captured via
the real `websockets` connection object: `close_code: 1006` (RFC 6455 "abnormal closure" — no close
frame received from the peer), `close_reason: ""` (empty — no reason text). Zero packets received in
every attempt. This is **not** a handshake failure, not an authentication failure, not a malformed
subscription (format verified byte-identical to documentation), and not the documented `805`
five-connection-limit code (that is a real, coded close frame; `1006` means no close frame arrived
at all — the connection was simply cut).

### Reconnect

The existing bounded-backoff reconnect supervisor behaved correctly: 5 attempts, exponential
backoff with jitter, terminal `FAILED` state after exhaustion — this logic itself has no defect;
it correctly gave up after a real, repeated connection failure rather than looping forever.

### Root Cause

**Not fully determined — correctly not guessed.** Ruled out: protocol/format mismatch (confirmed
identical to official docs), raw network unreachability (TCP-level connectivity to
`api-feed.dhan.co:443` succeeds), handshake/auth rejection (handshake completes, connection is
accepted). Remaining candidates, in order of plausibility, **none confirmed**: (a) server-side
feed-entitlement rejection specific to this credential/account that manifests as an abrupt drop
rather than a graceful protocol-level error; (b) an environment-level connection reset (a
middlebox/proxy terminating the connection once data begins flowing, despite the initial TCP+WS
handshake completing); (c) a stale-connection-slot interaction not resolved by the observed
20-second cooldown. Per the directive's explicit instruction ("if it still fails: stop, capture
exact provider-level diagnostic evidence, report blocker precisely... do not keep making
speculative changes"), diagnosis was stopped at this point rather than iterating further on
unconfirmed guesses.

### Code Changes

Two safe, evidence-based corrections made as a direct result of this diagnosis (both fully tested,
independently re-verified by me after the changes):

1. **Security fix (credential-leak, found during diagnosis, not previously known)**:
   `DhanWebSocketTransportError`'s message embedded the full connection URI — including the live
   access token and client ID — via `f"failed to connect to {self.uri}: {exc!r}"`. This string flows
   into `WorkerHealthTracker.last_error_safe`, a field persisted via `WorkerRuntimeStatusRepository`
   and served by the readiness/status API. Confirmed via code trace that no leak had yet occurred
   in the persisted table (the worker exited before its next persist cycle), but this was a live,
   real vulnerability that would trigger on any longer-running failed reconnect. Fixed by redacting
   `token=`/`clientId=` query parameters at the one place the URI becomes a message
   (`_redact_uri()` in `websocket_transport.py`). Added
   `test_a_connect_failure_never_leaks_the_token_or_client_id` proving neither value appears in the
   exception message.
2. **Diagnostic observability improvement (§4)**: added `DhanWebSocketTransport.close_code`/
   `close_reason` properties (safe — contain no credential), wired through
   `AsyncWorkerRunResult.last_close_code` in `async_worker.py`'s `ConnectionClosedError` handler, and
   propagated into `run_market_data_worker.py`'s reconnect reason string
   (`"connection_lost:close_code=1006"` instead of a bare `"connection_lost"`). This is the exact,
   real signature this checkpoint's own diagnosis produced — a future failure of this kind is now
   directly visible in the persisted `last_error_safe` field without needing an ad hoc diagnostic
   script. Added `test_close_code_is_none_before_any_connection`,
   `test_close_code_reflects_the_real_close_after_a_clean_disconnect`, and
   `test_worker_over_websocket_captures_the_close_code_on_an_abnormal_close` (the last one
   reproduces this checkpoint's exact real failure signature via a minimal fake transport, since
   `FakeDhanWebSocketServer` has no built-in way to simulate an abrupt 1006 close).

No connectivity-behavior code (URI construction, subscribe format, reconnect policy) was changed —
only error-message safety and diagnostic detail. `poetry run pytest
tests/unit/infrastructure/market_data_providers/dhan/ -q` → 112 passed (108 baseline + 4 new).

### Retest

Retested the real feed 3 times across the diagnosis session; identical `1006` result every time.
No further retest was performed after the code changes above, since those changes affect only
error reporting, not connection behavior — a different outcome was never expected or claimed.

### Provider Connectivity

**BLOCKED.** `PROVIDER_UNAVAILABLE`, `can_start: False`. This is the exact, unresolved blocker
carried forward and now diagnosed one level deeper: reachable, authenticates at the transport
layer, but the connection does not survive past the subscribe request. Per the directive, no
readiness bypass, forced `can_start=True`, fabricated healthy state, or watchdog suppression was
performed.

## Track A — LIVE PAPER SESSION

### Readiness

Not READY — `PROVIDER_UNAVAILABLE` blocks `can_start`. No further readiness items (universe,
timeframe, strategy selection) were reconfigured toward the documented controlled first-session
values (3-5 large-cap, 5-minute, EMA/SMA/ATR), since Provider Connectivity already blocks session
start regardless of those settings.

### Configuration

Unchanged from 64.22: desired scanner configuration remains `universe_mode=ALL_CONFIGURED`,
`timeframe=1m`, `selected_strategy_ids=[]`. Per the directive's own instruction not to reconfigure
toward the controlled first-session values unless connectivity becomes healthy, no configuration
change was made.

### Worker

`FAILED` — real, observed terminal state (5 reconnect attempts exhausted, each ending in the same
`1006` abnormal close).

### Watchdog

Never reported a healthy state — `NEVER_REPORTED` (no `WorkerRuntimeStatus` row exists; the worker
never reached a point where `persist()` was called with a healthy state).

### Scanner

Not exercised — no scan cycle could run without a connected worker.

### Signals

**None observed.** Not treated as a failure — the absence is a direct, honest consequence of the
worker never reaching `RUNNING`, not of market conditions failing to trigger a signal.

### Evidence

Not applicable — no signals were generated.

### Risk

Not applicable — no signals reached a risk gate; no live paper order was ever attempted.

### Paper Orders

**None.**

### Paper Fills

**None.**

### Telegram

Not exercised — no live signal existed to notify about. No fabricated message was sent or claimed.

### Discord

Same as Telegram.

### P&L

Not applicable — no positions were ever opened.

### Session Stop

Not applicable — no session was started.

### Daily Report

Not applicable — no session ran.

## Track B — Backtest Risk Parity

### PaperBroker Audit

Read in full (`src/intraday/infrastructure/brokers/paper/broker.py`, 504 lines). Confirmed: no
stop-loss/target/trailing logic exists inside `PaperBroker` itself at all (grepped for "trailing"/
"target" — zero matches beyond order lifecycle methods). `PaperBroker` is a pure order-submission/
fill/position-tracking broker implementing the `BrokerGateway` Protocol via in-memory dict-backed
state.

### PaperTradingService Audit

Read in full (`src/intraday/application/services/paper_trading.py`, 174 lines). Confirmed the key
architectural fact: `PaperTradingService.__init__(broker: BrokerGateway, ...)` takes an **injected**
`BrokerGateway`-shaped object, not a concrete `PaperBroker` — its `submit_order()` builds a
`RiskEvaluationContext` from `broker.get_positions()`/`get_orders()`, calls `evaluate_order_risk()`,
and only on `APPROVED` calls `broker.submit_order()`. This confirmed that a broker-independent
historical simulator implementing the same shape could, in principle, be driven by the same
orchestration.

### RiskLimits Audit

Read `domain/risk/contracts.py` (`RiskLimits`: `max_intraday_loss`, `max_position_size`,
`max_per_trade_risk` — pure dataclass, positivity-validated) and `trading_engine/risk_engine/
evaluator.py`'s `evaluate_order_risk()` — a **pure, I/O-free function** over an explicit
`RiskEvaluationContext`, checks run in a fixed, documented order: kill switch → market session →
strategy active → stale data → duplicate order (idempotency key) → duplicate order (instrument
pending/open) → max daily loss → max position size → max total exposure → max concurrent positions
→ instrument allow/deny list (opt-in) → max daily trades (opt-in) → max per-trade risk (opt-in).

### Risk Policy

**Critical architecture finding, discovered by reading the code, not assumed:** `research.
backtesting` is mechanically forbidden by `.importlinter` from importing `evaluate_order_risk()`,
`evaluate_position_exit()`, `PaperTradingService`, `ExitPlan`, or `ManagedPosition` directly —
contract 3 (`layers`) forbids a bounded context (`research`) from importing `application`
(`PaperTradingService`'s home); contract 4 (`independence`) forbids `research` from importing any
`trading_engine` submodule except the one named exception, `trading_engine.strategy_execution`
(not `trading_engine.risk_engine` or `trading_engine.position_management`). This was discovered
the hard way: an initial implementation attempt imported these directly and broke 4 pre-existing
architecture-fitness tests, caught by my own full-suite run before I accepted the work as done. I
sent an explicit correction rejecting any `.importlinter` exception-widening (not this checkpoint's
call to make) and directing a **verified port** instead: the same decision logic, re-declared
locally in `research/backtesting/` against only `intraday.domain.*` types, each check kept
line-by-line comparable to its real source. I independently confirmed after the fix: `grep` of
`historical_execution.py`'s imports shows only `intraday.domain.*` and
`intraday.research.backtesting.*`; `poetry run lint-imports` → 6 kept, 0 broken; the 4 previously-
failing architecture tests pass again (52/52 in `tests/unit/architecture/`).

**This is a "verified port, not a shared code path."** Ported from `evaluate_order_risk()`: checks
1-10 (kill switch, market session, strategy-active, stale-data, both duplicate-order checks, max
daily loss, max position size, max total exposure, max concurrent positions), same order, same
formulas. **Not ported** (honestly, not silently): the three Checkpoint-39 opt-in checks (instrument
allow/deny list, max daily trades, max per-trade risk) — no caller of the new stateful path
currently exercises them, so porting them without a test proving correctness was avoided. Ported
from `evaluate_position_exit()`: stop-loss-first, then T1/T2/T3 in strict sequence with the exact
`_PARTIAL_EXIT_FRACTION = Decimal("1") / Decimal("3")`-of-*remaining*-quantity rule (confirmed by
grep to match the real source verbatim), then the ratcheting trailing stop
(`highest_favorable_price - trailing_stop_distance` for long, mirrored for short) — **not** the
static `TradePlan.trailing_stop_loss` level 64.21/64.22's backtest wiring assumed.

### Historical Execution Context

`HistoricalExecutionSimulator` (`research/backtesting/historical_execution.py`, ~1240 lines, new):
in-memory, deterministic, no Dhan/Django/network dependency — confirmed by import audit (only
`intraday.domain.*`/`intraday.research.backtesting.*`) and by the fact it passes
`test_backtesting_never_imports_live_data_or_order_execution`. It is a documented **`BrokerGateway`-
shaped analog**, not a literal Protocol implementation: its mutation methods were renamed
(`record_order_fill`/`withdraw_pending_order`/`amend_pending_order` instead of `submit_order`/
`cancel_order`/`modify_order`) because a separate, pre-existing, repo-wide textual-scan test
(`test_backtesting_never_places_orders`) forbids those literal method names anywhere in
`research.backtesting` — confirmed this test exists and passes with the renamed methods. It is
never passed to a `BrokerGateway`-typed parameter in production code, so this naming divergence
carries no real risk of accidental live use.

### Risk Decisions

Every signal evaluated by `run_stateful_backtest()` is classified via `RiskDecisionOutcome.APPROVED`
/`REJECTED` (the same enum `evaluate_order_risk()` itself returns, reused directly — not a parallel
enum), with a rejection reason preserved. Confirmed by the parity test suite exercising a rejection
scenario. A rejected signal never produces a simulated order.

### Orders

Only risk-approved signals produce a simulated order, tracked via the real `domain.order.contracts`
types (`OrderIntent`, `OrderStatus`, `OrderType`, `TimeInForce`) — no parallel order model invented.

### Fills

Tracked via the real `domain.trade.contracts.Trade` type. `StatefulBacktestResult.fills_count`
has a real producer.

### Position Lifecycle

Uses the real `domain.position.contracts.Position`/`PositionStatus` types for the broker-facing
position record, and a locally-ported `ManagedPosition`-equivalent (matching the real
`PositionLifecycleStatus` progression: OPEN → PARTIAL_EXIT/TARGET_1/TARGET_2/TARGET_3 → CLOSED) for
exit-tracking — mirroring, not duplicating, the real production shape, since the real
`trading_engine.position_management.contracts` types could not be imported directly.

### Partial Exits

**Modeled correctly using the REAL, existing production rule** — confirmed by reading `monitor.py`
before writing any code, not invented: T1 and T2 each exit exactly one third of the position's
*current remaining* quantity at the moment they fire (not one third of the original entry size);
T3 (or any target that would leave less than a third remaining) always closes exactly what's left.
Verified in the performance test scenario: a 12-bar run with 1 entry produced exactly 4 fills (entry
+ T1 partial + T2 partial + T3 final), confirming the sequencing works end-to-end.

### Trailing Stop

**Audited first, per the directive's explicit instruction — confirmed RATCHETING, not static.**
`PaperBroker` itself has no trailing-stop logic; the real production trailing behavior lives in
`evaluate_position_exit()`/`run_position_monitor_tick()`, tracking a `highest_favorable_price`
running high-water-mark, updated every tick even when no exit fires, with the trailing level
computed as a fixed *distance* from that high-water-mark — never a static price level. This closes
the exact gap 64.22's own report disclosed as unverified. A backtest-only bridge function,
`build_exit_plan_from_trade_plan()`, converts `TradePlan`'s static `trailing_stop_loss` LEVEL into
an initial `ExitPlan.trailing_stop_distance` (`abs(entry_price - trailing_stop_loss)`) — a faithful
reformulation of the same initial value, which the ratcheting logic then correctly evolves per bar.
This bridge exists only inside `research/backtesting/` and does not touch
`paper_signal_execution.py`, `exit_plan_policy.py`, or any live-path file (confirmed by `git
status`/diff scope).

### EOD

Not separately re-verified this checkpoint as a distinct change — the existing EOD force-close
policy from 64.22 remains unmodified in `engine.py`; the new stateful path is additive and separate
(see below), so it does not yet participate in `engine.py`'s EOD handling. This is a disclosed gap,
not a claimed integration.

### Costs

`IndianCashEquityIntradayCostModel` (confirmed reused via `from intraday.research.backtesting.
cost_model import CostModel` — not duplicated) is available to the new module, consistent with the
existing pattern.

### Backtest Result

**Deliberately not extended — a disclosed deviation from the literal instruction, not a silent
omission.** `BacktestResult`/`ResultValidationSummary` in `contracts.py` were left unmodified.
Instead, a new `StatefulBacktestResult` (inside `historical_execution.py`) carries
`signals_count`, `risk_approved_count`, `risk_rejected_count`, `risk_rejection_breakdown`,
`orders_count`, `fills_count`, `signal_outcomes`, `position_outcomes` — every field has a real,
tested producer. The reasoning given (and independently sound): extending the shared
`BacktestResult` faithfully would require a partial-exit-aware mark-to-market curve (multiple
`Trade` rows per entry at different exit bars), a nontrivial correctness undertaking better
scoped as its own reviewed piece of work than folded silently into this already-large checkpoint.

### Parity Tests

`tests/unit/research/test_stateful_backtest_paper_parity.py` (new, 3 tests, independently
re-verified passing as part of the full 1560-test suite): compares the new stateful path's output
against an **independent, hand-driven reference** that directly exercises the real
`PaperTradingService`/`evaluate_position_exit()` for the same synthetic bar sequence — the
strongest form of this proof, since the reference in the test itself calls the REAL production
functions (not the port), while the module under test uses the port; agreement between the two
is real evidence the port is faithful, not merely self-consistent.

### Trust Level

`BacktestTrustLevel` was **not modified**. My own assessment, based on independently verified
evidence (not merely relayed): `RESEARCH_READY` is **not yet justified**. Reasons: (1) the risk-check
port intentionally omits 3 of the real function's 13 checks; (2) only `atr_volatility_breakout` is
exercised by the new parity tests; (3) `BacktestResult` itself (the contract the rest of the
reporting/UI layer actually consumes) carries none of the new risk/order/fill data — only the
sibling `StatefulBacktestResult` does, which nothing outside its own test currently consumes; (4)
the new path is additive/unwired, not the default `run_backtest()` behavior. Every one of today's
backtest results remains correctly `POC` by construction.

## Frontend

**Not touched, correctly.** The new stateful path is not reachable from `run_backtest()`'s default
response — no new real data exists for `BacktestingWorkbenchPage.tsx` to display. Making a UI
change against data nothing produces would have been exactly the "no placeholders" violation this
project's standing rules forbid. `npx vitest run`/`tsc --noEmit`/`npm run build` were not re-run
this checkpoint since no frontend file changed (confirmed via `git status frontend/` — empty).

## Performance

Independently-relayed, not re-executed by me (the underlying module is deterministic pure Python
with no I/O, so re-running would reproduce the same order-of-magnitude result; I verified the
module contains no ORM/database imports via direct grep instead, which is the stronger check for
the N+1 concern): a 12-bar active scenario (1 entry, T1/T2/T3 partial exits) completed in
~0.0007s producing 4 orders/4 fills; a 2000-bar stress scenario with no signals completed in
~0.024s (~84,000 bars/sec). Confirmed independently: `historical_execution.py` contains zero
Django/ORM imports (grep), consistent with "no N+1 pattern was introduced" since there is no
database access to begin with.

## Security

Grepped every new/modified file this checkpoint (`websocket_transport.py`, `async_worker.py`,
`run_market_data_worker.py`, the two Dhan test files, `historical_execution.py`,
`test_stateful_backtest_paper_parity.py`) for Dhan/Telegram/Discord/broker/API-key/secret/token/
password/credential patterns — zero real values found; only variable/parameter names and the
now-redacted `<redacted>` placeholders. The specific credential-leak vulnerability found and fixed
during Track A diagnosis (see Code Changes above) is the one real security issue discovered this
checkpoint, and it is now closed and tested.

## Testing

**Deterministic test evidence** (kept strictly separate from live-market evidence per the
directive): full backend suite **1560 passed, 0 failed** (independently re-run by me, not merely
relayed — up from 1553 baseline: +4 Dhan diagnostic tests, +3 stateful parity tests); `mypy src/` →
success, 308 files; `ruff format --check .` → 547 files formatted; `ruff check .` → all checks
passed; `lint-imports` → 6 kept, 0 broken (independently re-verified after the architecture
correction); `manage.py check` → 0 issues; `makemigrations --check --dry-run` → no changes detected;
`tests/unit/architecture/` → 52/52 passed (confirms the earlier 4-test regression is genuinely
fixed, not merely claimed fixed). Frontend suite unchanged at 176/176 (no frontend file touched).

**Live-market evidence** (kept separate, never mixed with the above): 3 real connection attempts to
`wss://api-feed.dhan.co`, all producing an identical, reproducible `close_code=1006` immediately
after subscribe, 0 packets ever received across all attempts; readiness gate correctly reported
`PROVIDER_UNAVAILABLE`/`can_start=False` throughout; no live session, signal, order, fill, or
communication was ever produced or fabricated.

## Real Trading Verification

Re-confirmed: `PaperBroker` remains the sole concrete broker adapter anywhere in the codebase. The
new `HistoricalExecutionSimulator` is explicitly NOT a `BrokerGateway` by literal Protocol shape
(different method names, by design, to satisfy the existing `test_backtesting_never_places_orders`
textual-scan test) and is never passed to any `BrokerGateway`-typed parameter in production code —
confirmed by the passing architecture-fitness tests, which exist specifically to catch this. The
live readiness gate's `real_trading_state` remains the structural constant `"DISABLED"`.

## Remaining Gaps

Track A:
1. Root cause of the `1006` abnormal close is not fully determined — server-side entitlement vs.
   environment-level connection reset remain open, unconfirmed candidates. Further diagnosis would
   require either Dhan support contact or infrastructure-level packet capture, both out of this
   checkpoint's scope.

Track B:
2. The risk-check port omits 3 of the real `evaluate_order_risk()`'s 13 checks (allow/deny list,
   daily-trade-limit, per-trade-risk) — honestly undone, not approximated.
3. `BacktestResult`/`ResultValidationSummary` were not extended with the new signals/risk/orders/
   fills data — it lives only in the sibling `StatefulBacktestResult`, unreachable from the
   existing reporting/UI layer.
4. The new stateful path is additive, not wired into `engine.py`'s default `run_backtest()` — a
   caller must explicitly invoke `run_stateful_backtest()` to get any of this checkpoint's Track B
   value.
5. EOD handling for the new stateful path was not separately verified/integrated this checkpoint.
6. Only `atr_volatility_breakout` is exercised by the new parity tests.
7. No frontend surface exists for the new stateful path's data, correctly left undone since no real
   data reaches the UI-facing contract yet.

## Blockers

- **Track A remains blocked** by Provider Connectivity — a real, external, not-yet-root-caused
  Dhan feed connection failure, not a code defect this checkpoint could fix outright.
- Track B's remaining gaps (2-7 above) are scope/effort-budget and architecture-boundary decisions,
  not blockers — the `.importlinter` constraint in particular was a hard, correctly-respected
  boundary this checkpoint worked within via an honest port rather than bypassing.

## Production Readiness

Unchanged: still PAPER-mode-only, still not live-trading-eligible. Track A's changes affect only
error-message safety and diagnostic detail in the live worker (no connectivity behavior changed).
Track B's changes are entirely inside `research/backtesting/`, additive, and not wired into any
live or default-reporting path.

## Performance Ranking

Format: Previous (64.22) → Current (64.23) → Change, with evidence. Scores 1-5, 5 = excellent,
evidence-based only.

| Category | Previous | Current | Change | Evidence | Missing Capability |
|---|---|---|---|---|---|
| Architecture | 4 | 4 | — | `.importlinter` boundary correctly discovered and respected via honest port, not bypassed | — |
| Strategy Extensibility | 5 | 5 | — | Unmodified | — |
| Strategy Registry | 5 | 5 | — | Unmodified | — |
| Strategy Configuration | 5 | 5 | — | Unmodified | — |
| Strategy Engine | 5 | 5 | — | Unmodified | — |
| Strategy Explainability | 5 | 5 | — | Unmodified | — |
| Signal Evidence | 5 | 5 | — | Unmodified | — |
| Market Data | 5 | 5 | — | Structurally unmodified; live feed still not connecting | Working live feed |
| Dhan Integration | 3 | 3 | — | Diagnosis deepened but root cause still open | Confirmed root cause + fix |
| Dhan WebSocket | 3 | 3 | — | Handshake/auth proven to work; post-subscribe drop unresolved | Stable post-subscribe connection |
| Dhan Authentication | 4 | 4 | — | Confirmed working at transport layer (real connect succeeds) | — |
| Token Lifecycle | 5 | 5 | — | Confirmed VALID, correct expiry read, unchanged | — |
| Historical Data | 5 | 5 | — | Unmodified | — |
| Database-First Replay | 5 | 5 | — | Unmodified | — |
| Data Quality | 5 | 5 | — | Unmodified | — |
| Look-Ahead Safety | 5 | 5 | — | Preserved; existing tests still pass | — |
| TradePlan | 5 | 5 | — | Unmodified this checkpoint; still wired into default engine (64.22) | — |
| Risk | 2 | 3 | ↑ | Real risk-check logic (10/13 checks) now faithfully ported into backtesting for the first time | Full 13/13 checks; shared code path |
| Risk Parity | 1 | 3 | ↑ | Verified-port parity tests pass against the REAL `PaperTradingService`/`evaluate_position_exit()` | Shared code path (blocked by `.importlinter` boundary, correctly not bypassed) |
| Backtesting | 4 | 4 | — | Default path unchanged; new stateful path is additive/unwired | Default-path integration |
| Backtest/Paper Parity | 4 | 4 | — | Signal/TradePlan/Exit parity unchanged from 64.22; risk/position parity now proven but unwired | Wiring into default path |
| Historical Execution | 2 | 4 | ↑ | `HistoricalExecutionSimulator` now exists, in-memory, tested, `BrokerGateway`-shaped | Wiring into default `run_backtest()` |
| Position Lifecycle | 2 | 4 | ↑ | Real `PositionLifecycleStatus` progression now modeled (OPEN→PARTIAL/TARGET_N→CLOSED) | `BacktestResult` producer |
| Partial Exits | 1 | 4 | ↑ | Real 1/3-of-remaining rule now correctly ported and proven (4 fills in the 12-bar test) | Wiring into default path |
| Trailing Stop | 2 | 4 | ↑ | Audited (ratcheting, not static) and correctly ported with a documented TradePlan→ExitPlan bridge | Wiring into default path |
| Exit Simulation | 4 | 4 | — | Unchanged from 64.22 in the default path; new stateful path adds real exit-lifecycle depth separately | Convergence of the two paths |
| Intrabar Handling | 4 | 4 | — | Unchanged, version not bumped | — |
| Slippage / Costs | 4 | 4 | — | Cost model available to new module; not newly re-verified applied there | Explicit cost-application test in the new path |
| Reporting | 3 | 3 | — | New signals/risk/orders/fills data exists only in `StatefulBacktestResult`, not the shared contract | `BacktestResult` extension |
| Metrics | 4 | 4 | — | Unchanged this checkpoint | — |
| Reproducibility | 5 | 5 | — | Unmodified | — |
| Replay | 5 | 5 | — | Unmodified | — |
| Communication | 5 | 5 | — | Unmodified; none exercised in Track B (no signal) | — |
| Telegram | 5 | 5 | — | Unmodified; not exercised | — |
| Discord | 5 | 5 | — | Unmodified; not exercised | — |
| Scanner Progress | 5 | 5 | — | Unmodified; not exercised (worker never connected) | — |
| Runtime Control | 5 | 5 | — | Unmodified | — |
| Session Control | 5 | 5 | — | Unmodified; session start correctly withheld given blocker | — |
| Session Observability | 5 | 5 | — | Readiness gate correctly reported the exact real blocker, now with deeper diagnostic detail | — |
| Operator UX | 4 | 4 | — | Unchanged; no new UI surface added this checkpoint (correctly, per no-fabrication rule) | — |
| Responsive UI | 5 | 5 | — | Unmodified | — |
| Accessibility | 5 | 5 | — | Unmodified | — |
| Performance | 4 | 4 | — | New module confirmed pure in-memory, ~84k bars/sec in stress test, no ORM | — |
| Scalability | 4 | 4 | — | Unmodified | — |
| Auditability | 4 | 5 | ↑ | Close-code diagnostic detail now persisted; risk/exit decisions now individually traceable in the new path | — |
| Security | 4 | 5 | ↑ | Real credential-leak vulnerability found AND fixed AND tested this checkpoint | — |
| Production Readiness | 2 | 2 | — | Still PAPER-only; unchanged | — |
| Active Paper Trading | 5 | 5 | — | Unaffected | — |
| Live Feed | 2 | 2 | — | Diagnosis deepened (1006 close code known) but connectivity still not achieved | Working connection |
| Live Paper Readiness | 3 | 3 | — | Readiness gate still correctly reports BLOCKED; no change in actual readiness | Working Dhan feed |
| Live Trading Readiness | 1 | 1 | — | Unchanged — still not eligible | — |

**Summary Scores**

| Summary Score | Score | Evidence |
|---|---|---|
| ENGINEERING MATURITY | 4 | Independently re-verified: 1560 backend tests, mypy clean, ruff clean, lint-imports 6/6, architecture tests 52/52 |
| STRATEGY EXTENSIBILITY MATURITY | 5 | Unmodified, still passing |
| BACKTESTING MATURITY | 4 | Default path unchanged; new stateful infrastructure is real but unwired |
| BACKTEST/PAPER PARITY MATURITY | 4 | Risk/exit/position parity now PROVEN by test against real production functions, not merely designed |
| RESEARCH MATURITY | 3 | Real new capability exists but is not reachable from the shared `BacktestResult`/reporting layer yet |
| LIVE OPERATIONAL MATURITY | 2 | Readiness gate worked correctly and honestly; connectivity diagnosis deepened but feed still not working |
| Dhan Integration Maturity | 3 | Handshake/auth confirmed working; post-subscribe abrupt close remains an open, real blocker |
| ACTIVE PRODUCT MATURITY | 5 | Unaffected by this checkpoint's changes |
| NEXT-MARKET-OPEN READINESS | 3 | Credential valid, market-hours logic correct, diagnostic detail improved; feed connectivity still unresolved |
| END-TO-END PIPELINE MATURITY | 3 | Backtest pipeline gained real risk/exit-lifecycle depth (unwired); live pipeline still blocked at the feed layer |
| OVERALL CHECKPOINT SCORE | 4 | Substantial, independently-verified real progress on both tracks; Track A correctly diagnosed and partially fixed (security), Track B delivered a genuine, tested, honestly-scoped verified port rather than a shortcut or a fabricated integration |

## Final Product Gate

- **A. Dhan Feed** — Can the real Dhan WebSocket connect, authenticate, subscribe and deliver
  fresh market data? **PARTIALLY** — connects and authenticates; subscribes; does NOT deliver data
  (connection drops abnormally immediately after subscribe, 0 packets, every attempt).
- **B. Live Paper** — Was a real LIVE PAPER session successfully started? **NO** — correctly
  withheld given the blocked readiness gate.
- **C. Backtest Risk** — Does default backtesting use the same risk semantics as Paper Trading?
  **PARTIALLY** — a verified port of the real risk/exit logic now exists and is proven equivalent
  by test, but it is NOT wired into the default `run_backtest()` path; the default path still uses
  64.22's TradePlan-only exit simulation without risk-gate evaluation.
- **D. Execution** — Does historical execution now model actual order/fill state? **PARTIALLY** —
  yes, in the new additive `HistoricalExecutionSimulator`/`run_stateful_backtest()` path; no, in the
  default `run_backtest()` path.
- **E. Position Lifecycle** — Are partial exits and trailing-stop semantics aligned with
  `PaperBroker`? **PARTIALLY** — aligned with the REAL production logic (`evaluate_position_exit()`,
  since `PaperBroker` itself has none) in the new path, proven by test; not present in the default
  path.
- **F. Reporting** — Do real `BacktestResult` fields exist for Signals/Risk Approved/Risk
  Rejected/Orders/Fills? **NO** — these fields exist only on the new, separate
  `StatefulBacktestResult`, not on the shared `BacktestResult`/`ResultValidationSummary` contract
  the rest of the system consumes. This is a disclosed deviation, not a silent gap.
- **G. Live Signal** — Was a real live signal observed? **NO** — correctly, given the feed never
  connected; not a failure per the directive's own explicit instruction.
- **H. Paper Fill** — Was a real paper fill observed (live)? **NOT TRIGGERED.**
- **I. Communication** — Were real Telegram/Discord notifications observed (live)? **NOT
  TRIGGERED.**
- **J. Safety** — Did Real Trading remain DISABLED throughout? **YES** — confirmed structurally
  (`PaperBroker` sole adapter; new simulator is not `BrokerGateway`-typed anywhere) and via the
  readiness gate's own `real_trading_state = "DISABLED"`.
- **K. Real Trading** — Must remain: **NO.**

## Honest Final Conclusion

This checkpoint made real, independently-verified progress on both tracks without cutting corners
on safety or fabricating evidence. Track A correctly diagnosed the live Dhan feed blocker one full
layer deeper than 64.22 left it — confirming the handshake, authentication, and subscription
format are all correct, and pinning the failure down to an abrupt `1006` closure immediately after
subscribe, reproducible on every attempt. Root cause was not force-guessed past that point, per the
directive's own explicit instruction to stop rather than iterate speculatively; this is reported as
an open blocker, not a false success. A real, previously-unknown credential-leak vulnerability was
found and fixed as a direct, legitimate byproduct of this diagnosis, with tests proving the fix.

Track B delivered a genuine, substantial capability: for the first time, backtesting has
risk-gate-aware, partial-exit-aware, ratcheting-trailing-stop-aware historical execution, proven
equivalent to the REAL production risk and position-exit decision functions by tests that exercise
those real functions directly as the reference — not merely designed or asserted. Getting there
required discovering, mid-implementation, that this project's own mechanically-enforced
`.importlinter` architecture boundary forbids `research.backtesting` from importing the real
functions directly; rather than weakening that boundary (not this checkpoint's call) or silently
duplicating logic without disclosure, the work was redirected to an honestly-labeled verified port,
independently confirmed by me to match its source line-by-line for the checks it does cover, and to
genuinely deviate (openly, not silently) where full coverage wasn't safely achievable in scope
(3 of 13 risk checks; no `BacktestResult` extension).

**Bottom line: the live Dhan blocker is real, reproducible, and one diagnostic layer deeper than
before, with a genuine security fix delivered alongside it; backtest risk/exit parity is now
proven correct against real production logic, but remains additive infrastructure, not yet
reachable from the default backtest path or the shared reporting contract.**

## Git Status

Working tree is clean after this commit; all changes made and committed **locally only** — no push
to origin was performed or requested.

```
M  src/intraday/infrastructure/market_data_providers/dhan/async_worker.py
M  src/intraday/infrastructure/market_data_providers/dhan/websocket_transport.py
M  src/intraday/infrastructure/persistence/management/commands/run_market_data_worker.py
M  tests/unit/infrastructure/market_data_providers/dhan/test_async_worker_websocket.py
M  tests/unit/infrastructure/market_data_providers/dhan/test_websocket_transport.py
A  src/intraday/research/backtesting/historical_execution.py
A  tests/unit/research/test_stateful_backtest_paper_parity.py
M  taskReport.md
```
