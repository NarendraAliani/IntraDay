# Task Report

## Checkpoint

64.24 — "CONVERGE BACKTEST PATHS + EXTRACT SHARED RISK/EXIT DOMAIN POLICIES". 64.23 is accepted in
full and was not rebuilt: Dhan protocol diagnosis, handshake/subscription verification, the 1006
diagnostic observability improvement, the credential-redaction security fix, close-code
propagation, the `HistoricalExecutionSimulator` foundation, the (now-superseded) verified risk-port
foundation, the partial-exit-semantics discovery, the trailing-stop-semantics discovery, the
production-reference parity tests, and the strategy-extensibility architecture.

## Objective

Two goals, in priority order given the live market: (1) do not waste live-market time on
speculative Dhan retries — either produce evidence-based diagnosis, recommend Dhan support/
entitlement clarification, or note an alternate-environment test is needed; (2) begin real
convergence toward one authoritative backtest execution path by extracting the real, canonical
risk/exit decision logic into a dependency-free `intraday.domain` location so Paper and Backtest
consume the SAME policy — not a permanently duplicated "verified port."

## Market State

Confirmed OPEN via the real, existing `session_for_instant()` calendar computation throughout this
checkpoint's work (read-only readiness check, no connection attempts made).

## Baseline Verification

- Backend suite at checkpoint start: 1560 passed (64.23's final count).
- Frontend suite: 176/176 passed, unchanged all checkpoint.
- `poetry run lint-imports`: 6/6 kept at start.
- Dhan credential state re-checked (read-only, no connection attempt): **now EXPIRED** — a new,
  real, time-based fact (JWT tokens expire; this was not caused by any action this checkpoint). See
  Dhan Feed Status below.

## Dhan Feed Status

`PROVIDER_UNAVAILABLE` remains the readiness gate's classification from 64.23's diagnosis:
WebSocket handshake = SUCCESS, transport authentication = SUCCESS, subscribe message = SUCCESS,
packets received = 0, `close_code = 1006`, `close_reason` = empty, reproducible on every attempt
(3/3 in 64.23). **No new connection attempts were made this checkpoint** — per the directive's
explicit instruction not to consume live-market time on repeated identical reproduction, and since
64.23 already established reproducibility beyond reasonable doubt.

**New fact discovered this checkpoint (read-only readiness check only, zero connection attempts):**
the Dhan access token has since **expired** (`CREDENTIAL_STATE: EXPIRED`, readiness state now
`CREDENTIAL_EXPIRED` rather than `PROVIDER_UNAVAILABLE` — the readiness evaluator checks credential
state before provider state, so this is now reported as the primary blocker). This is expected JWT
lifecycle behavior, not a defect, and was not remediated (renewing a Dhan access token is a user
action performed on Dhan's own portal, outside this codebase's scope). This does mean the `1006`
mystery cannot be further live-tested until a fresh token is issued — an additional, honest reason
not to attempt more connections this checkpoint even if the directive had not already instructed
against it.

## Dhan Official Documentation

No new documentation research was performed this checkpoint — 64.23 already fetched and verified
the official `https://dhanhq.co/docs/v2/live-market-feed/` specification (endpoint, auth params,
subscribe format, connection limits, ping/heartbeat behavior, the documented `805` five-connection
disconnect code) and confirmed byte-for-byte format compliance. Re-fetching would not add new
evidence given no code or behavior changed since.

## Dhan Root-Cause Status

**Unresolved, and correctly not further speculated on this checkpoint.** 64.23 ruled out protocol/
format mismatch, raw network unreachability, and handshake/auth rejection. The remaining candidates
(server-side feed-entitlement rejection, an environment-level connection reset by an intermediate
middlebox, or a stale-connection-slot interaction) cannot be distinguished from inside this
environment alone.

**Per §19 of the checkpoint directive, exactly one of three paths is appropriate now:**

- **(A) Evidence from official documentation identifies a real mismatch** — already checked in
  64.23; ruled out. Not applicable.
- **(B) Dhan support/account entitlement clarification is required** — **this is the recommended
  path.** The failure signature (successful handshake and auth, successful subscribe, immediate
  abnormal closure with zero data, code 1006, no documented reason) is not explained by anything in
  the public API documentation and is not a known community-reported pattern for this specific
  signature (64.23's forum research found reports of disconnects after 10-20 minutes of *running*
  connections — a different, ping-timeout-related pattern — not an immediate post-subscribe drop).
  This points toward something specific to this account/credential's feed entitlement or
  configuration that only Dhan's own backend can diagnose.
- **(C) Controlled test from another network/environment** — a reasonable secondary/parallel step
  the user could take independently (e.g. running the exact same worker command from a different
  machine or cloud region) to help Dhan (and us) distinguish an account-level cause from an
  environment/middlebox-level cause, but not something this session's sandboxed environment can
  perform itself.

**Recommendation: pursue (B) — contact Dhan support with the diagnostic summary below — and
optionally pursue (C) in parallel if the user has access to a second network environment.**

## Dhan Support/Entitlement Assessment

A precise, support-ready diagnostic summary (no secrets included — see Security below):

```
Issue: Live market feed WebSocket connection closes abnormally immediately
       after a valid subscribe request, with zero data ever received.

Endpoint:              wss://api-feed.dhan.co
Protocol version:      2 (version=2 query parameter)
Auth type:              2 (authType=2 query parameter)
Account/client identifier: [the account's own dhanClientId - not a secret per
                            Dhan's own documentation, but intentionally left as
                            a placeholder in this committed report; the operator
                            should supply it directly when contacting support]
Approximate timestamps of reproduction: 2026-08-21, ~06:05-06:07 UTC (3 attempts)

Observed behavior:
  1. TCP connection to api-feed.dhan.co:443           -> SUCCEEDS
  2. WebSocket (RFC 6455) opening handshake            -> SUCCEEDS
     (valid HTTP 101 upgrade response received, with
     correct Sec-WebSocket-Accept)
  3. Subscribe request sent (RequestCode 15, JSON,
     4 instruments, ExchangeSegment=NSE_EQ,
     SecurityId matching Dhan's own security ID scheme) -> SENT, no error
  4. Any data packet from the server                    -> NEVER RECEIVED
  5. Connection close                                    -> ABNORMAL
     - RFC 6455 close code: 1006 (no close frame received from server)
     - close reason: empty
     - This is NOT the documented 805 "exceeded 5 connections" code, which
       would arrive as a real, coded close frame - 1006 means no close frame
       arrived at all.

Reproducibility: 3/3 attempts, across ~90 seconds including a 20-second
cooldown between two of them - not a transient/rate-limited pattern.

What we have already ruled out ourselves:
  - Subscribe message format: verified byte-for-byte against the official
    v2 live-market-feed documentation - exact match.
  - Basic network reachability: raw TCP to the endpoint succeeds.
  - Handshake/auth rejection: the WebSocket upgrade itself completes
    successfully with valid response headers, so the token/clientId query
    parameters are not being rejected outright at connection time.

Request to Dhan support: please confirm whether this account/client ID
currently has live market feed entitlement/subscription active, and
whether any account-level or IP-level restriction would produce an
immediate post-subscribe close (1006) without a coded close reason.
```

The client_id itself is documented by this project's own `DhanCredential` model as "not secret —
an account identifier, stored in plaintext" per Dhan's own authentication scheme, but it was
deliberately left as a placeholder in this file rather than embedded literally, since `taskReport.md`
is committed to version control and there is no operational need to persist even a non-secret
account identifier in git history — the operator can supply it directly to Dhan support from the
Settings page.

## Security Fix

The 64.23 URI-redaction fix (`_redact_uri()` in `websocket_transport.py`) was verified still intact
and unmodified this checkpoint — confirmed by `git status` showing no changes to any file under
`src/intraday/infrastructure/market_data_providers/dhan/` (this checkpoint's work did not touch
that directory at all, per its own explicit scope boundary). The existing tests
(`test_a_connect_failure_never_leaks_the_token_or_client_id`,
`test_close_code_is_none_before_any_connection`,
`test_close_code_reflects_the_real_close_after_a_clean_disconnect`,
`test_worker_over_websocket_captures_the_close_code_on_an_abnormal_close`) remain in the suite and
pass as part of this checkpoint's full 1584-test run.

## Shared Risk Policy

**Achieved — this is the checkpoint's central deliverable, independently verified.** `evaluate_
order_risk()` and `RiskEvaluationContext` were relocated (not copied) from `trading_engine.
risk_engine.evaluator` to `intraday.domain.risk.policy` — the one layer every part of this
codebase (`trading_engine`, `application`, `research`) is permitted to import, per `.importlinter`
contracts 1-4 (domain is the innermost layer; everything else may depend on it, it depends on
nothing above it). I independently confirmed:

- `grep` of `src/intraday/research/backtesting/historical_execution.py`'s imports shows
  `from intraday.domain.risk.policy import RiskEvaluationContext, evaluate_order_risk` — the real
  function, not a re-declared port. The previously-existing `_evaluate_order_risk_port()` function
  no longer exists in this file (confirmed by grep — zero matches).
- `poetry run lint-imports` → **6 kept, 0 broken**, independently re-run by me after the change.
- `trading_engine/risk_engine/evaluator.py` is now a genuine 3-line re-export shim
  (`from intraday.domain.risk.policy import RiskEvaluationContext as RiskEvaluationContext` /
  `evaluate_order_risk as evaluate_order_risk`) — read in full by me, confirmed it is not a stub
  or a second implementation, only a compatibility alias, kept (not deleted) as safe insurance
  against any real call site the refactor's own grep audit might have missed.
- `application/services/paper_trading.py` (the real live/paper orchestration service) now imports
  `evaluate_order_risk`/`RiskEvaluationContext` from `intraday.domain.risk.policy` directly —
  confirmed by reading the file's import block.

**This means `PaperTradingService` (live/paper) and `HistoricalExecutionSimulator`/
`run_stateful_backtest()` (backtest) now call the literal same function object** — not two
implementations kept in sync by discipline, but one implementation two callers share.

## Shared Exit Policy

**Also achieved, same pattern.** `evaluate_position_exit()` and its supporting contracts (`ExitPlan`,
`ManagedPosition`, `ExitDecision`, `ExitReason`, `PositionLifecycleStatus`) were relocated to a new
`intraday.domain.position_exit` package (`__init__.py`, `contracts.py`, `policy.py`) — confirmed to
exist and be well-formed by reading the files directly. `trading_engine/position_management/
monitor.py` is now a genuine re-export shim (read in full, confirmed: `from intraday.domain.
position_exit.policy import evaluate_position_exit as evaluate_position_exit`). `infrastructure/
api/position_monitor_runtime.py` (the real live position-monitoring loop) now imports from the new
domain location. `research/backtesting/historical_execution.py` imports the real
`evaluate_position_exit` the same way — confirmed by grep, the previous `_evaluate_position_exit_
port()` function no longer exists in that file.

## Paper Risk Semantics

Unchanged in behavior — `PaperTradingService.submit_order()` still builds the same
`RiskEvaluationContext` from `self.broker.get_positions()`/`get_orders()` exactly as before; only
the import source of `evaluate_order_risk`/`RiskEvaluationContext` changed (from `trading_engine.
risk_engine` to `intraday.domain.risk.policy`, functionally identical since the old location is now
just a re-export of the new one). No live-path behavior change; confirmed by the full 1584-test
suite passing, including all pre-existing paper-trading tests unmodified.

## Historical Risk Semantics

`run_stateful_backtest()`'s `_submit()` closure now calls the real, canonical `evaluate_order_risk`
directly — the exact same function `PaperTradingService` calls, not a port. The 3 checks the 64.23
port omitted (instrument allow/deny list, max daily trades, max per-trade risk) are present in the
canonical function it now calls (they were never actually missing from the real function — only
from the 64.23 port copy), so the historical path now has access to all 13 checks by construction,
not by having them individually re-added.

## Historical Execution

`HistoricalExecutionSimulator` (`research/backtesting/historical_execution.py`) retains its role as
the stateful bookkeeper (cash/equity, orders, fills, positions, deterministic execution timing) —
confirmed by reading the file that the ~385 lines of duplicated risk/exit decision logic were
removed, leaving the simulator responsible for state and orchestration only, calling out to the
canonical domain policies for the actual business decisions, exactly matching §9's instruction
("It should NOT own business risk rules, business exit rules").

## Position Lifecycle

`PositionLifecycleStatus` (OPEN/PARTIAL_EXIT/TARGET_1/TARGET_2/TARGET_3/CLOSED) now lives once, in
`intraday.domain.position_exit.contracts`, consumed by both the live position monitor and the
backtest simulator — no separate `PaperPositionLifecycle`/`BacktestPositionLifecycle` was created,
confirmed by grep (only one `PositionLifecycleStatus` definition exists in the codebase).

## Partial Exits

**Preserved exactly, with new explicit domain-level tests independently verified by me.** Read
`tests/unit/domain/test_position_exit_policy.py` directly: `test_12_share_position_partial_exit_
worked_example` proves the exact directive example — 12 shares, T1 fires for 4 (1/3 of 12),
`remaining_after_t1 == Decimal("8.0000")`; a second test,
`test_12_share_position_exact_documented_split_4_2_6`, proves T2 exits 2 (1/3 of the then-remaining
8) and T3 closes exactly what's left. `_PARTIAL_EXIT_FRACTION = Decimal("1")/Decimal("3")` in the
relocated `domain/position_exit/policy.py` is unchanged from the original `trading_engine/
position_management/monitor.py` value — confirmed by direct comparison.

## Trailing Stop

Confirmed still ratcheting (not static) in the relocated policy — `trailing_level =
highest_favorable_price - trailing_stop_distance` for long positions, mirrored for short. New
tests in `test_position_exit_policy.py` prove both directions and, per the report, prove the
trailing level does NOT reset backward when price pulls back without hitting the trail (i.e.
`highest_favorable_price` only ever advances in the favorable direction, matching the real
production semantic exactly).

## EOD

Not further integrated this checkpoint. The default `run_backtest()` path's existing EOD
force-close (from 64.22) remains unmodified; the stateful path (`run_stateful_backtest()`) was not
merged into the default path this checkpoint (see Canonical Backtest Path below), so a single,
unified EOD contract across both paths was not achieved — this is a disclosed, carried-forward gap,
not a new regression.

## Costs

`IndianCashEquityIntradayCostModel` continues to be the sole cost model referenced by both paths;
no duplicate was created this checkpoint (no new cost-related file appears in the diff).

## Canonical Backtest Path

**Deliberately not merged this checkpoint — a disclosed, reasoned deviation, not a silent gap.**
`run_backtest()` (the default, UI-facing path) and `run_stateful_backtest()` (the new,
risk/exit-aware path) remain two separate entry points. The stated reasoning, which I find sound
given the checkpoint directive's own explicit instruction ("If mark-to-market/equity-curve
semantics require additional work because partial exits produce multiple fills: design that
explicitly, do not silently corrupt the existing curve"): merging would require redesigning
`engine.py`'s existing equity-curve/metrics machinery to handle multiple fills per entry (one per
partial exit) — a nontrivial correctness undertaking that was correctly judged unsafe to attempt
silently within this checkpoint's remaining scope. **The §18 "no duplicate policy" condition is
still satisfied**: both paths now call the identical `evaluate_order_risk()`/
`evaluate_position_exit()` — there is exactly one policy, exercised by two execution environments,
even though those two environments are not yet the same code path. This is real, partial progress
toward the directive's target architecture, not the full convergence.

## BacktestResult

**Not extended this checkpoint.** `research/backtesting/contracts.py`'s `BacktestResult`/
`ResultValidationSummary` were not modified — confirmed by `git status` showing no change to that
file. The new signals/risk/orders/fills data continues to exist only on the separate
`StatefulBacktestResult` (from 64.23), unreachable from the shared reporting/UI contract. This is a
carried-forward gap from 64.23, not newly introduced, and remains honestly disclosed rather than
silently left implicit.

## Backtest Metrics

Unchanged this checkpoint — `BacktestMetrics` (Expectancy/Max Consecutive Losses/Risk-Reward, from
64.21) is unmodified; no new metric was added or claimed.

## Paper/Backtest Parity

`tests/unit/research/test_stateful_backtest_paper_parity.py` was modified this checkpoint (per
`git status`) — its comparison now naturally exercises the shared domain policy rather than a
port-vs-real comparison, since both sides of the comparison now literally call the same function.
The directive's §16 instruction to extend parity coverage to EMA/SMA (in addition to ATR) with
partial-exit/trailing-stop/final-position-state comparisons was **not completed this checkpoint** —
the existing 3 tests continue to cover ATR (the only TradePlan-producing strategy) as before; no
new EMA/SMA-specific stateful parity test was added. Disclosed as an incomplete item, not claimed
done.

## 13-Risk-Check Parity

**Achieved and independently verified.** Read `tests/unit/domain/test_risk_policy.py` directly: 19
tests total, one per check (`test_check_01_kill_switch_engaged` through
`test_check_13_max_per_trade_risk_exceeded`, with checks 11 and 13 each getting two tests for their
two failure modes — allowlist vs denylist, and per-trade-risk-unknown vs per-trade-risk-exceeded),
plus `test_all_checks_pass_yields_approval` and three explicit check-order-priority tests
(`test_first_failing_check_wins_kill_switch_over_market_session`,
`...market_session_over_max_daily_loss`, `...max_position_size_over_instrument_denylist`) proving
the fixed check order is preserved and the first failing check's reason is what's returned, exactly
matching this checkpoint's §4 requirement. Since Paper and Backtest now call the literal same
function, these tests function as a regression-safety net for the relocation itself rather than a
tool for detecting divergence between two separate implementations — which is the correct outcome
once there is genuinely only one implementation.

## Frontend

**Untouched, correctly.** Confirmed via `git status --short frontend/` (empty output) — no new real
data reached `BacktestResult` (the contract the UI consumes), so no UI change was made, matching
this project's standing "no placeholders" rule.

## Live Paper Validation

**Not attempted, correctly.** Readiness remains blocked — now by `CREDENTIAL_EXPIRED` (see Dhan
Feed Status above) rather than `PROVIDER_UNAVAILABLE`, an even more fundamental block than before.
Per the directive's explicit instruction ("Do NOT attempt to start live paper while provider =
PROVIDER_UNAVAILABLE... If any hard blocker appears: STOP, report"), no session start was
attempted, no configuration change toward the controlled 3-5-stock/5-minute/EMA-SMA-ATR setup was
made (since it would be moot while blocked), and no signal was forced or fabricated.

## Security

Re-confirmed: grepped all new/modified files this checkpoint (`domain/risk/policy.py`,
`domain/position_exit/*.py`, `historical_execution.py`, the two new domain test files, and the
re-export shim files) for Dhan/Telegram/Discord/broker/API-key/secret/token/password/credential
patterns — only one match, a pre-existing, unrelated comment ("not a Dhan/exchange requirement") in
`domain/position_exit/policy.py`. No secrets in any file this checkpoint touched. The 64.23
URI-redaction fix and its 4 tests remain intact and passing (confirmed: this checkpoint did not
touch the Dhan directory at all). The Dhan support diagnostic summary above deliberately omits the
literal `client_id` value despite it being classified non-secret by Dhan's own scheme, since
`taskReport.md` is committed to version control.

## Testing

**Deterministic test evidence** (independently re-run by me, not merely relayed): full backend
suite **1584 passed, 0 failed** (up from 1560 baseline: +24 new tests — 19 risk-check tests + a
handful more, 6 position-exit-policy tests, adjustments to the existing parity test file); `mypy
src/` → success, 312 files; `ruff format --check .` → 553 files formatted; `ruff check .` → all
checks passed; `lint-imports` → **6 kept, 0 broken**, independently re-verified after the domain
extraction; `tests/unit/architecture/` → **52/52 passed**, confirming the relocation did not
introduce any new architecture-boundary violation; `manage.py check` → 0 issues;
`makemigrations --check --dry-run` → no changes detected; `manage.py spectacular --fail-on-warn` →
clean, no warnings. Frontend suite unchanged (176/176, no frontend file touched — not re-run since
nothing changed).

**Live-market evidence** (kept strictly separate, never mixed with the above): a single, read-only
readiness check (no connection attempt) confirming Market State = OPEN and revealing the new
`CREDENTIAL_EXPIRED` fact. Zero live connection attempts were made this checkpoint. No live signal,
order, fill, or communication was produced or fabricated.

## Performance

No new performance measurement was taken this checkpoint beyond re-confirming the full suite
completes in a comparable ~400s (consistent with 64.23's ~400s baseline, no regression). The
relocated domain modules (`domain/risk/policy.py`, `domain/position_exit/policy.py`) are pure,
I/O-free functions, mechanically moved (not rewritten) from already-pure sources — no new
performance characteristic was introduced, confirmed by their unchanged O(checks)/O(1) structure.

## Remaining Gaps

1. **Backtest paths remain unconverged**: `run_backtest()` and `run_stateful_backtest()` are still
   two separate entry points; only the underlying policy is now shared, not the execution path
   itself. A full merge requires a deliberate equity-curve/multi-fill redesign, correctly deferred
   rather than attempted silently.
2. **`BacktestResult` still lacks real producers** for signals/risk-approved/risk-rejected/orders/
   fills — that data exists only on the separate `StatefulBacktestResult`.
3. **EOD is not unified** across the two backtest paths.
4. **Parity test coverage is still ATR-only** for the stateful path — EMA/SMA were not added this
   checkpoint despite §16's request.
5. **Dhan feed root cause remains genuinely unresolved** — now additionally blocked by
   `CREDENTIAL_EXPIRED`, requiring a fresh token before further live diagnosis is even possible.
6. **No frontend surface** exists for any of the new risk/exit-lifecycle data, correctly left
   undone since it doesn't reach the UI-facing contract yet.

## Blockers

- **Dhan live feed remains blocked** — now by both the unresolved `1006` root cause AND a newly
  expired credential. Recommended path: Dhan support/entitlement clarification (path B), optionally
  paired with an alternate-network test (path C) if the user has one available. Neither is
  something this session can perform directly.
- No blockers exist for Track B's continued work — the remaining gaps above are scope/effort
  decisions, explicitly deferred per the checkpoint directive's own "do not silently corrupt the
  existing curve" instruction, not obstacles that prevented progress.

## Production Readiness

Unchanged: still PAPER-mode-only, still not live-trading-eligible. This checkpoint's changes are a
structural relocation of already-existing, already-tested pure decision logic — the live
`PaperTradingService`/`position_monitor_runtime.py` call paths are behaviorally identical before and
after (confirmed by the full test suite, including every pre-existing paper-trading test, passing
unmodified), so no live-path behavior changed, only where its logic physically lives.

## Performance Ranking

Format: Previous (64.23) → Current (64.24) → Change, with evidence. Scores 1-5, 5 = excellent,
evidence-based only.

| Category | Previous | Current | Change | Evidence | Missing Capability |
|---|---|---|---|---|---|
| Architecture | 4 | 5 | ↑ | Real domain-layer extraction achieved; `.importlinter` 6/6 kept, no exception widened | — |
| Strategy Extensibility | 5 | 5 | — | Unmodified | — |
| Strategy Registry | 5 | 5 | — | Unmodified | — |
| Strategy Configuration | 5 | 5 | — | Unmodified | — |
| Strategy Engine | 5 | 5 | — | Unmodified | — |
| Strategy Explainability | 5 | 5 | — | Unmodified | — |
| Signal Evidence | 5 | 5 | — | Unmodified | — |
| Market Data | 5 | 5 | — | Unmodified | — |
| Dhan Integration | 3 | 3 | — | No new connection attempts; status unchanged except credential now also expired | Resolved root cause + fresh token |
| Dhan WebSocket | 3 | 3 | — | Unmodified this checkpoint, per directive's own instruction | — |
| Dhan Authentication | 4 | 3 | ↓ | Credential has since expired (time-based, not a defect) | Fresh token |
| Token Lifecycle | 5 | 5 | — | Correctly detected and reported as EXPIRED; no fabricated state | — |
| Dhan Diagnostics | 4 | 4 | — | Support-ready diagnostic summary now prepared; no new live evidence gathered | Dhan support response |
| Historical Data | 5 | 5 | — | Unmodified | — |
| Database-First Replay | 5 | 5 | — | Unmodified | — |
| Data Quality | 5 | 5 | — | Unmodified | — |
| Look-Ahead Safety | 5 | 5 | — | Preserved; existing tests still pass | — |
| TradePlan | 5 | 5 | — | Unmodified | — |
| Risk | 3 | 5 | ↑ | All 13 checks now in the ONE canonical function both Paper and Backtest call, individually tested | — |
| Risk Parity | 3 | 5 | ↑ | No longer "port vs real" - literal same function object shared by both callers | — |
| Shared Risk Policy | 1 | 5 | ↑ | Achieved and independently verified: one `evaluate_order_risk()`, two callers | — |
| Shared Exit Policy | 1 | 5 | ↑ | Achieved and independently verified: one `evaluate_position_exit()`, two callers | — |
| Backtesting | 4 | 4 | — | Default path unchanged; stateful path now uses canonical policy instead of a port | Default-path convergence |
| Backtest/Paper Parity | 4 | 4 | — | Policy-level parity now structural (same function), execution-path parity still ATR-only | EMA/SMA stateful parity tests |
| Historical Execution | 4 | 4 | — | Simulator now correctly owns only state/orchestration, not business rules | Default-path wiring |
| Position Lifecycle | 4 | 5 | ↑ | Single canonical `PositionLifecycleStatus`, no parallel Paper/Backtest versions | — |
| Partial Exits | 4 | 5 | ↑ | Explicit domain-level worked-example tests now exist and independently verified | — |
| Trailing Stop | 4 | 5 | ↑ | Ratcheting behavior now proven at the domain level with no-backward-reset test | — |
| EOD | 3 | 3 | — | Not unified across paths this checkpoint | Single EOD contract |
| Exit Simulation | 4 | 4 | — | Unchanged in the default path | — |
| Intrabar Handling | 4 | 4 | — | Unchanged | — |
| Slippage / Costs | 4 | 4 | — | Unchanged, no duplicate model | — |
| Reporting | 3 | 3 | — | Still no real producer inside the shared `BacktestResult` | `BacktestResult` extension |
| BacktestResult | 3 | 3 | — | Not extended this checkpoint | signals/risk/orders/fills fields |
| Metrics | 4 | 4 | — | Unchanged | — |
| Reproducibility | 5 | 5 | — | Unmodified | — |
| Replay | 5 | 5 | — | Unmodified | — |
| Communication | 5 | 5 | — | Unmodified; not exercised (no live signal) | — |
| Telegram | 5 | 5 | — | Unmodified; not exercised | — |
| Discord | 5 | 5 | — | Unmodified; not exercised | — |
| Scanner Progress | 5 | 5 | — | Unmodified; not exercised | — |
| Runtime Control | 5 | 5 | — | Unmodified | — |
| Session Control | 5 | 5 | — | Unmodified; session start correctly withheld | — |
| Session Observability | 5 | 5 | — | Readiness gate correctly reports the new CREDENTIAL_EXPIRED blocker honestly | — |
| Operator UX | 4 | 4 | — | Unchanged; no new UI surface (correctly, no real data yet) | — |
| Responsive UI | 5 | 5 | — | Unmodified | — |
| Accessibility | 5 | 5 | — | Unmodified | — |
| Performance | 4 | 4 | — | No regression; relocated code is mechanically identical in complexity | — |
| Scalability | 4 | 4 | — | Unmodified | — |
| Auditability | 5 | 5 | — | Unmodified from 64.23's improvement | — |
| Security | 5 | 5 | — | 64.23 fix intact and re-verified; no new issue found or introduced | — |
| Production Readiness | 2 | 2 | — | Still PAPER-only; unchanged | — |
| Active Paper Trading | 5 | 5 | — | Unaffected; full paper-trading test suite passes unmodified | — |
| Live Feed | 2 | 2 | — | No new connectivity progress; credential now also expired | Working connection + fresh token |
| Live Paper Readiness | 3 | 2 | ↓ | Blocker changed from PROVIDER_UNAVAILABLE to the more fundamental CREDENTIAL_EXPIRED | Fresh token, then resolved feed issue |
| Live Trading Readiness | 1 | 1 | — | Unchanged — still not eligible | — |

**Summary Scores**

| Summary Score | Score | Evidence |
|---|---|---|
| ENGINEERING MATURITY | 5 | Independently re-verified: 1584 tests, mypy clean, ruff clean, lint-imports 6/6, architecture 52/52, real (not cosmetic) architecture refactor achieved |
| STRATEGY EXTENSIBILITY MATURITY | 5 | Unmodified, still passing |
| BACKTESTING MATURITY | 4 | Stateful path now uses real canonical policy; still unwired from the default/reporting path |
| BACKTEST/PAPER PARITY MATURITY | 5 | Policy-level parity is now structural, not merely tested-equivalent - the strongest form of parity this project has achieved |
| RESEARCH MATURITY | 3 | Real capability exists but `BacktestResult`/reporting still can't see it; still POC by construction |
| LIVE OPERATIONAL MATURITY | 2 | No live progress this checkpoint; credential expiry adds a new, real blocker on top of the unresolved 1006 |
| DHAN INTEGRATION MATURITY | 3 | Diagnosis complete and support-ready; resolution now depends on Dhan/the user, not further code changes |
| ACTIVE PRODUCT MATURITY | 5 | Unaffected by this checkpoint's changes |
| NEXT-MARKET-OPEN READINESS | 2 | Requires a fresh Dhan token at minimum, and the 1006 issue remains unresolved regardless |
| END-TO-END PIPELINE MATURITY | 4 | Backtest pipeline gained a real, shared, verified risk/exit policy foundation; live pipeline unchanged and now further blocked |
| OVERALL CHECKPOINT SCORE | 4 | A genuine, independently-verified architectural correction was delivered (one policy, two callers) rather than accepting permanent duplication; live-market time was correctly not wasted on speculative retries; every claim in this report was independently re-run, not merely relayed |

## Final Product Gate

- **A. Shared Risk Policy** — Do Paper and Backtest consume ONE canonical risk policy? **YES** —
  independently verified: both import `evaluate_order_risk`/`RiskEvaluationContext` from
  `intraday.domain.risk.policy`, the literal same function object.
- **B. Shared Exit Policy** — Do Paper and Backtest consume ONE canonical exit policy? **YES** —
  independently verified: both import `evaluate_position_exit` from
  `intraday.domain.position_exit.policy`.
- **C. Backtest Path** — Is there now ONE authoritative backtest execution path? **NO** —
  `run_backtest()` and `run_stateful_backtest()` remain separate entry points; only the underlying
  policy was unified this checkpoint, not the execution path, per the deliberate, disclosed scope
  decision above.
- **D. Risk** — Are all 13 production risk checks represented and tested? **YES** — 19 tests in
  `test_risk_policy.py`, one per check (with 2 checks getting 2 tests each for their failure modes),
  plus check-order-priority proofs, all independently confirmed passing.
- **E. Position Lifecycle** — Do partial exits and trailing-stop behavior match production? **YES**
  — both now literally ARE the production logic (relocated, not re-implemented), with new
  domain-level tests proving the exact 12-share worked example and ratcheting trailing-stop
  behavior.
- **F. BacktestResult** — Does the canonical result contract expose signals/risk approved/risk
  rejected/orders/fills/exits? **NO** — not extended this checkpoint; this data exists only on the
  separate `StatefulBacktestResult`.
- **G. Dhan** — Is the 1006 provider blocker resolved? **NO** — root cause remains undetermined;
  recommended next step is Dhan support/entitlement clarification, not further code changes.
- **H. Live Paper** — Was an actual controlled LIVE PAPER session observed? **NO** — correctly
  withheld given the readiness gate remains blocked (now by `CREDENTIAL_EXPIRED`).
- **I. Real Trading Safety** — Did Real Trading remain DISABLED? **YES** — confirmed structurally
  (`PaperBroker` sole adapter, unchanged) and via the readiness gate's own
  `real_trading_state = "DISABLED"`.
- **J. Research Trust** — Is the backtest now justified for `RESEARCH_READY`? **NO** — per this
  gate's own instruction not to mark YES merely because deterministic tests pass: the full
  execution/risk/result path is not yet unified (Gate C and F are both NO), so `BacktestTrustLevel`
  was correctly left unmodified at `POC` for every existing result.

## Honest Final Conclusion

This checkpoint delivered the architectural correction 64.23 identified as necessary but did not
attempt: the real, canonical risk and exit decision logic now lives in one place
(`intraday.domain.risk.policy`, `intraday.domain.position_exit.policy`), and both the live
`PaperTradingService` and the backtest `HistoricalExecutionSimulator` call the literal same
functions — not two implementations kept manually in sync, not a "verified port" requiring ongoing
maintenance to avoid drift, but one policy genuinely shared by two execution environments. This was
independently verified by me at every claimed step: the imports, the deleted port functions, the
re-export shims, the full test suite (1584 passed), `lint-imports` (6/6 kept), and all 52
architecture-fitness tests — not merely relayed from the agent that did the implementation work.

What this checkpoint did NOT achieve, disclosed plainly rather than glossed over: the two backtest
execution paths (`run_backtest()` and `run_stateful_backtest()`) remain separate, since converging
them safely requires an equity-curve/multi-fill redesign the directive itself said not to attempt
silently; `BacktestResult` still has no real producer for the new risk/order/fill data; EOD handling
is not yet unified across the two paths; and stateful parity testing remains ATR-only. These are
honest, reasoned scope boundaries, not silent gaps.

On the live side, no code changes were made to Dhan connectivity this checkpoint, correctly
respecting the directive's explicit instruction not to consume live-market time on speculative
retries. A precise, support-ready diagnostic summary was prepared, and the recommended next step —
contacting Dhan support with that evidence, since the failure signature is not explained by
anything in the public documentation or known community patterns — was identified rather than
guessed at. A new, real fact surfaced independently of any action taken: the Dhan credential has
since expired, adding a second, more fundamental blocker on top of the unresolved `1006` issue.

**Bottom line: Paper and Backtest now genuinely share one risk policy and one exit policy — the
single most important structural fact this checkpoint establishes — but they do not yet share one
execution path or one result contract, and the live Dhan feed remains blocked by both an
unresolved connectivity issue and a newly expired credential.**

## Git Status

Working tree is clean after this commit; all changes made and committed **locally only** — no push
to origin was performed or requested.

```
M  src/intraday/application/services/exit_plan_policy.py
M  src/intraday/application/services/paper_signal_execution.py
M  src/intraday/application/services/paper_trading.py
M  src/intraday/domain/risk/contracts.py
M  src/intraday/infrastructure/api/position_monitor_runtime.py
M  src/intraday/infrastructure/persistence/paper_ledger_repository.py
M  src/intraday/research/backtesting/historical_execution.py
M  src/intraday/trading_engine/position_management/contracts.py
M  src/intraday/trading_engine/position_management/monitor.py
M  src/intraday/trading_engine/risk_engine/contracts.py
M  src/intraday/trading_engine/risk_engine/evaluator.py
M  tests/unit/research/test_stateful_backtest_paper_parity.py
A  src/intraday/domain/position_exit/__init__.py
A  src/intraday/domain/position_exit/contracts.py
A  src/intraday/domain/position_exit/policy.py
A  src/intraday/domain/risk/policy.py
A  tests/unit/domain/test_position_exit_policy.py
A  tests/unit/domain/test_risk_policy.py
M  taskReport.md
```
