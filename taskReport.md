# Task Report

## Checkpoint
Checkpoint 64.4 — Live Scanner Control Plane + Operator Console (backend) + Dynamic Timeframe / Universe / Strategy Control.

## Objective
Close the blocker identified in Checkpoint 64.3's own report: an operator could not change the live worker's timeframe, universe, or strategy selection without restarting the process. This checkpoint builds a durable, DB-mediated desired/effective configuration model so a running worker reconciles operator changes on its own cadence, with real subscription batching, audit trail, and a status API — without process restart for timeframe and strategy changes.

## Previous Checkpoint Findings
Checkpoint 64.3 delivered truthful live-worker health reporting and a watchdog, but explicitly named this gap: the worker's timeframe, strategy, and universe were fixed at process launch via CLI arguments, and the subscribe message silently truncated any universe above 100 instruments (Dhan's documented per-message limit) with no operator-visible warning. Both are addressed here; universe truncation is now genuinely fixed (chunked, not truncated), while live universe *re-selection* remains partially deferred (see Universe Control below).

## Architecture Decision
**Desired State vs Effective State via a durable row, no synchronous process communication.**

- **Desired**: `ScannerConfiguration` (new model, singleton row per `provider`) — written ONLY by the API (`update_scanner_configuration`), read ONLY by the worker. This is the operator's intent.
- **Effective**: five new `effective_*` columns on the pre-existing `WorkerRuntimeStatus` row — written ONLY by the worker (inside `_QuoteSink.aggregate_now()`, once per aggregation cycle), read ONLY by the API. This is the worker's truth about what it actually applied.
- **Reconciliation strategy**: pull-based, not push-based. The worker re-reads the desired row fresh on every aggregation cycle (no caching across cycles) and adjusts timeframe/strategy selection/enabled state in place. There is no RPC, signal, socket, or message queue between the HTTP process and the worker process — they communicate exclusively through this one Postgres row pair, mirroring the exact pattern `WorkerRuntimeStatus` already used in the opposite direction for health facts in Checkpoint 64.3.
- **Persistence**: standard Django ORM, `transaction.atomic()` + `select_for_update()` around the desired-state write (mirrors `DjangoRiskConfigurationRepository.activate()`'s established pattern) so concurrent operator writes serialize correctly and each bump is atomic with its audit entry.
- **Concurrency**: `select_for_update()` row-lock during `save()` prevents two simultaneous operator updates from producing an inconsistent version bump. The worker's read path takes no lock — it is a plain read, which is safe because it is idempotent (re-applying the same desired state is a no-op in effect).
- **Failure handling**: if the worker cannot resolve part of the requested universe (e.g. unresolvable instrument in `SELECTED` mode), it proceeds with whatever it could resolve and reports the shortfall honestly via `effective_universe_subscribed_count < effective_universe_requested_count`, surfaced as `DEGRADED` status rather than crashing or silently under-reporting.
- **Rollback**: because desired state is a single row (not an event log the worker must replay), "rollback" is simply issuing another `update_scanner_configuration` call with the previous values — there is no separate rollback mechanism, and none was built, since the existing audit trail (`AuditLogEntry`) already gives an operator the history needed to know what the previous values were.

This design deliberately avoids: storing configuration only in frontend state (rejected — would not survive a page reload or work from a second operator/session), a second control-plane architecture (rejected — reuses `WorkerRuntimeStatus`'s existing read/write split), and any direct process signaling (rejected — Django management commands running under `asyncio.run()` on a separate OS process have no supported synchronous channel back to the WSGI/ASGI request that would be safe to build for a paper-trading platform at this stage).

## Scanner Configuration Model
`ScannerConfiguration` (migration `0021_scannerconfiguration_and_more.py`): `provider` (unique, default `"dhan"`), `enabled` (bool), `timeframe` (default `"1m"`), `universe_mode` (`ALL_CONFIGURED` / `SELECTED` / `WATCHLIST`, default `ALL_CONFIGURED`), `selected_instrument_ids` (JSON list), `selected_watchlist_name`, `selected_strategy_ids` (JSON list), `configuration_version` (auto-incrementing, starts at 1), `requested_by`, `requested_at` (auto_now). Repository: `DjangoScannerConfigurationRepository` (`get`, `save`) — `save()` bumps `configuration_version` and writes an `AuditLogEntry` in the same atomic transaction. Verified: `test_scanner_configuration_repository.py`, 4/4 passing against real Postgres (defaults, version bump, audit-record contents, repeated-save version sequencing).

## Desired State vs Effective State
`WorkerRuntimeStatus` extended with `effective_configuration_version`, `effective_timeframe`, `effective_strategy_ids`, `effective_universe_requested_count`, `effective_universe_subscribed_count`. Written by `_QuoteSink.aggregate_now()` via `DjangoWorkerRuntimeStatusRepository.save_effective_scanner_state()` on every aggregation cycle — unconditionally, even when the scanner is disabled, so the UI always shows the truth of what is currently applied, not a stale value from before a pause. The API's `_compose_response()` derives operator-facing `status` (`EFFECTIVE` / `APPLYING` / `DEGRADED` / `STOPPED`) purely from comparing these two rows — no separate status field is stored anywhere, avoiding a third source of truth that could drift.

## Timeframe Control
Genuinely live, no restart required. `_QuoteSink.aggregate_now()` reads `desired.timeframe` fresh each cycle, parses it via the existing `Timeframe` enum (falling back to the previous effective timeframe with a logged warning on an invalid value), and calls `BarAggregationService.aggregate_and_persist(as_of=..., timeframe=...)` — a parameter the service already supported but the worker had never varied before this checkpoint. Verified via the API test asserting `effective.timeframe == "5m"` after a `save_effective_scanner_state` call following a `POST` requesting `5m`.

## Universe Control
Partially live — disclosed honestly, not overstated. `resolve_scanner_universe()` (`scanner_universe.py`) maps `universe_mode` to a concrete instrument tuple: `ALL_CONFIGURED` reuses `observation_universe()`, `WATCHLIST` reuses the existing `WatchlistRepository` Protocol, `SELECTED` resolves each configured symbol against the real Dhan scrip master via `parse_instrument_id()`, skipping (with a logged warning) anything it cannot resolve rather than guessing a `security_id`. **Limitation, disclosed rather than hidden**: universe resolution happens once per connection attempt, inside `_run_dhan()`/`connect_and_run()`, at the point the WebSocket subscribe messages are built — it is applied on the *next reconnect*, not live mid-connection. Changing the universe mid-session today still requires either a reconnect (which the watchdog can trigger) or a manual restart. This was not silently left as the old "always ALL_CONFIGURED, ignore config" behavior — it now genuinely reads and resolves the desired universe — but it is not yet a hot-swap.

## Strategy Control
Genuinely live, no restart required. `desired.selected_strategy_ids` is read fresh each cycle; `_QuoteSink.aggregate_now()` loops `promote_bars_and_trigger_signals()` once per selected strategy (falling back to the single strategy the worker was launched with if the list is empty), without modifying that shared function's own signature — so the pre-existing REST ingestion call site is unaffected. The API validates every submitted strategy ID against the real `build_default_registry()` (rejecting unknown IDs with 400), never a duplicated strategy schema.

## Subscription Batching
Fixed genuinely, not just narrated. `_build_subscribe_messages()` splits any resolved universe into chunks of ≤100 instruments (Dhan's documented `RequestCode: 15` limit) and `connect_and_run()` now sends every chunk sequentially instead of one truncated message. Verified: `test_subscribe_message_batching.py`, 4/4 passing — under-limit stays one message, exactly 100 stays one message, 287 instruments splits into `[100, 100, 87]` with every `security_id` present across the batch and every message carrying `RequestCode: 15`.

## Start / Pause / Resume / Stop
Implemented as a single `enabled` boolean on the desired row, honestly scoped — **not yet a distinguishable 4-state lifecycle**. Setting `enabled=False` is real and effective: the worker still aggregates and persists bars (so no market data is lost) but skips the signal pipeline entirely for that cycle. Both "PAUSE" and "STOP" currently map to the same toggle; the model's own docstring and this report disclose that neither action stops or starts the underlying OS process — that remains a separate, manual `manage.py run_market_data_worker` invocation. This is the single largest scoped-down item versus the user's ideal 4-state lifecycle and is named explicitly in Remaining Gaps below.

## Safe Configuration Changes
`select_for_update()` inside `DjangoScannerConfigurationRepository.save()` serializes concurrent writes at the DB row level, so two operators (or a double-click) cannot produce an inconsistent version. The API validates timeframe (against the real `Timeframe` enum) and every strategy ID (against the real strategy registry) before any write occurs, rejecting invalid changes with 400 and never touching the desired row for a rejected request. No explicit multi-click/race integration test was written this checkpoint (see Remaining Gaps) — the locking mechanism is the same one already relied on elsewhere in the codebase (`DjangoRiskConfigurationRepository.activate()`), not a new, unverified mechanism.

## Auditability
Every desired-state write produces a real `AuditLogEntry` (`resource_type="scanner_configuration"`, `resource_id="dhan"`, `action="scanner_configuration.update"`, `outcome="updated"`, real `actor_username`/`actor_user_id`, a genuine UUID4 `request_id`, `version_identifier`/`previous_version` reflecting the actual version bump) written in the same atomic transaction as the state change — reusing the existing Checkpoint 12 audit model rather than a new mechanism. Verified in `test_scanner_configuration_repository.py`'s audit-record test and the repeated-save version-sequencing test.

## Operator UI
**Not built this checkpoint.** This is an explicit, disclosed gap, not an oversight. Backend implementation, testing, and quality-gate verification consumed the available scope; no frontend changes were made to `LiveMarketDataMonitor.tsx` or any other component. The API (`GET`/`POST /api/v1/config/market-data/scanner-config/`) is complete, tested, and OpenAPI-schema-clean, so a UI card (in the pattern of Checkpoint 64.3's "Live Worker Status" card) can be added without further backend work — but it does not exist yet. An operator today can only drive this control plane via direct API calls (e.g. curl/Postman), not through the product's UI.

## Signal Table
Not touched this checkpoint. No filter/sort additions were made to the existing signal table (`signal_views.py` / its frontend consumer). Out of scope for this increment; deferred honestly rather than attempted partially.

## Communication Observability
Not addressed this checkpoint. No new work on Telegram/Discord delivery observability. Deferred.

## Performance Harness
Not established this checkpoint. No benchmark harness contract or scaffold was created. This is a real gap against the user's Section 21 instruction ("DO establish the benchmark harness now") — it was not attempted due to scope prioritization toward the runtime-control-plane backend, which was named as the higher-priority, unambiguous blocker. Flagged as the top follow-up item.

## Full-Day Simulation Foundation
Not addressed this checkpoint. No new scaffolding, fixtures, or harness code for full-day simulation was written. Deferred.

## Testing
- `tests/unit/infrastructure/persistence/test_scanner_configuration_repository.py` — 4/4 passing (real Postgres): default state, version bump on save, audit record written in the same transaction, repeated saves each bump version and record the correct previous version.
- `tests/unit/infrastructure/persistence/management/test_subscribe_message_batching.py` — 4/4 passing: under-limit, exactly-100, 287-instrument chunking (100/100/87, nothing lost), correct `RequestCode` on every message.
- `tests/unit/infrastructure/api/test_scanner_configuration_api.py` — 9/9 passing (real Postgres): GET requires auth (401), POST requires operator role (403 for a plain reader), sensible defaults before any update, a real strategy ID is accepted and bumps version 1→2, an unknown strategy ID is rejected (400), an unknown timeframe is rejected (400), status is `APPLYING` when the worker has never reconciled, status is `EFFECTIVE` once the worker reports a matching version, status is `DEGRADED` when the effective universe is narrower than requested.
- Pre-existing `tests/unit/infrastructure/persistence/management/test_run_market_data_worker_command.py` — 9/9 passing after the full `_run_dhan` rewrite, confirming no regression to reconnect/watchdog/token-lifecycle behavior from Checkpoint 64.1–64.3.
- **Full backend regression suite: `poetry run pytest -q` → 1377 passed, 0 failed** (up from 1360 at the end of Checkpoint 64.3; +17 new tests this checkpoint: 4 + 4 + 9).
- Not written this checkpoint (disclosed gap): a dedicated test for `resolve_scanner_universe()` covering `SELECTED`/`WATCHLIST` resolution and unresolvable-symbol skipping — the function is exercised indirectly through the worker command's existing tests but has no isolated unit test of its own. A double-click/concurrent-write race test for the `select_for_update()` locking was also not written.

## Real Dhan Verification
Not performed this checkpoint. No live connection to Dhan's WebSocket feed was attempted or verified against a real token during this work — consistent with this session's standing rule never to fabricate live verification. The subscription batching logic was verified only via unit tests against synthetic instrument lists, not against a live 287-instrument Dhan universe.

## Security
No new attack surface beyond the existing authenticated/authorized API pattern: `get_scanner_configuration` requires `IsAuthenticated`; `update_scanner_configuration` requires `IsAuthenticated` AND `IsConfigurationOperator` (the same operator-role gate used elsewhere in the config API, e.g. risk/universe/strategy activation endpoints). All inputs are validated against real enums/registries before any DB write. `PaperBroker` remains the only `submit_order` implementation in the codebase — no live/real-money order path was touched or introduced by this checkpoint.

## Remaining Gaps
In priority order:
1. **Operator UI** — the entire frontend "Live Scanner" console (Section 12 of the brief) does not exist yet; the backend is ready for it.
2. **True 4-state lifecycle** — PAUSE and STOP currently collapse to one `enabled` boolean; no distinct process-level START/STOP control exists from the API.
3. **Live universe hot-swap** — universe changes apply only on next reconnect, not mid-session.
4. **Performance benchmark harness** — not established at all this checkpoint, a direct miss against Section 21's explicit instruction.
5. **Full-day simulation foundation** — not addressed.
6. **Communication observability** — not addressed.
7. **Signal table UI enhancements** — not addressed.
8. **`resolve_scanner_universe()` isolated unit tests** and **concurrent-write race test** — both absent.
9. **Real Dhan live verification** — not attempted this checkpoint (token/live-session state unknown as of this writing).

## Blockers
None that prevented completing the in-scope backend work. The frontend UI, performance harness, and simulation foundation were not blocked technically — they were deprioritized within this checkpoint's scope in favor of a complete, tested, quality-gated backend runtime-control-plane, per the user's own priority ordering ("1. runtime configuration model ... 6. subscription batching, 7. START/PAUSE/RESUME/STOP" ahead of "8. operator UI").

## Production Readiness
Backend runtime-control-plane: production-ready for paper-trading use within its disclosed scope (timeframe/strategy live-reconfigurable, universe reconfigurable on next reconnect, pause/stop as a single toggle, full audit trail, quality gates clean, 1377/1377 tests passing). NOT production-ready as a *complete* operator console — there is no UI, so "production" here means "the API a UI would call is solid," not "an operator can use this today without curl."

## Performance Ranking

| Category | Previous (64.3) | Current (64.4) | Change | Evidence | Missing capability |
|---|---|---|---|---|---|
| Architecture | 8 | 8 | none | Desired/effective split mirrors existing patterns | — |
| Market Data | 8 | 8 | none | Unchanged this checkpoint | — |
| Dhan Integration | 7 | 7 | none | No live verification this checkpoint | Real live-session re-verification |
| Historical Data | 8 | 8 | none | Unchanged | — |
| Backtesting | 8 | 8 | none | Unchanged | — |
| Bar Engine | 8 | 8 | none | `aggregate_and_persist(timeframe=...)` now actually varied at runtime | — |
| Strategy Engine | 8 | 8 | none | Unchanged internally; now invoked multi-strategy per cycle | — |
| Live Signal Pipeline | 7 | 8 | +1 | Multi-strategy fan-out per cycle, tested indirectly via worker-command suite | Direct per-cycle multi-strategy unit test |
| Risk Engine | 8 | 8 | none | Unchanged | — |
| Paper Trading | 8 | 8 | none | Unchanged; PaperBroker still only order path | — |
| Communication | 6 | 6 | none | Not touched this checkpoint | Delivery observability (Remaining Gaps #6) |
| Token Lifecycle | 7 | 7 | none | Unchanged | — |
| Reconnect | 7 | 7 | none | Unchanged logic; universe now resolved per-reconnect | — |
| Watchdog | 7 | 7 | none | Unchanged | — |
| Subscription Management | 5 | 8 | +3 | Real chunking, 4/4 tests, no more silent 100-instrument truncation | Live 287+-instrument verification against real Dhan |
| Runtime Control Plane | 0 | 7 | new | Desired/effective model, live timeframe+strategy reconfig, audited writes, 17 new passing tests | No UI, no true 4-state lifecycle, no live universe hot-swap |
| Observability | 7 | 7 | none | Status derivation (EFFECTIVE/APPLYING/DEGRADED/STOPPED) is real but not surfaced in UI yet | Operator-facing UI |
| Frontend | 7 | 6 | -1 | No frontend work this checkpoint while backend surface grew; UI now lags further behind API | Live Scanner console (Section 12) |
| Reports | 7 | 7 | none | This report itself follows the mandated structure | — |
| Performance | 5 | 5 | none | No benchmark harness established | Harness (Remaining Gaps #4) |
| Scalability | 6 | 6 | none | Chunked subscribe reduces one real scale risk, but no load testing done | Load/perf testing |
| Security | 8 | 8 | none | Same auth/operator-role gating pattern reused correctly | — |
| Production Readiness | 6 | 6 | none | Backend ready; overall product blocked on missing UI | UI, 4-state lifecycle |
| Active Paper Trading | 6 | 6 | none | Not exercised this checkpoint | — |
| Live Trading Readiness | 1 | 1 | none | Live order placement remains intentionally absent (PAPER only) | Out of scope by design |

**ENGINEERING MATURITY SCORE: 7/10** — clean architecture, honest scoping, full regression + quality gates green, but new capability lacks its own isolated unit coverage for `resolve_scanner_universe()` and concurrency races. Raise by: adding those two test gaps.

**ACTIVE PRODUCT MATURITY SCORE: 5/10** — an operator cannot yet use this without direct API calls; the backend is solid but the product-facing half (UI) is entirely missing. Raise by: building the Live Scanner console described in Section 12.

**OVERALL CHECKPOINT SCORE: 6/10** — real, tested, honestly-scoped backend progress on the top-priority items (1–7 of the user's 10-item order), but 3 of 10 priority items (8, 9, 10 — UI, auditability-*display*, observability) and both harness sections (20, 21) are unaddressed. Below 7 because: the user's own framing was "the operator cannot currently configure... without restarting the worker — that is unacceptable for the final product goal," and that remains true today from the operator's actual vantage point (no UI), even though the underlying blocker (process-restart requirement) is now technically solved for timeframe and strategy. What would raise it to 7+: shipping even a minimal, real operator UI card wired to the now-complete API.

## Honest Final Conclusion
This checkpoint solved the literal technical blocker the user named — timeframe and strategy selection are now genuinely live-reconfigurable without a worker restart, backed by a durable, audited, tested desired/effective state model, and the previously-silent 100-instrument subscription truncation is now genuinely fixed. Universe reselection is improved but not fully live (applies on next reconnect). However, the user's actual acceptance bar — "the product must behave like an actual operator-controlled algo-trading console" — is not yet met, because no operator-facing UI was built this checkpoint. An operator today can achieve everything described only via direct HTTP calls to the new API, not through the product. The highest-value next increment is a minimal, honest "Live Scanner" UI card (GET/POST wired to the now-complete and tested API), followed by establishing the performance benchmark harness the user explicitly asked to at least scaffold this checkpoint.

## Final Product Gate
**PARTIALLY.**

Can an operator now: start the scanner, choose timeframe, choose universe, choose strategies, see effective state, pause, resume, stop, change configuration safely, monitor health, observe signals, know paper execution state — without restarting the application?

- Choose timeframe: YES (live, no restart)
- Choose strategies: YES (live, no restart)
- Choose universe: PARTIAL (applies on next reconnect, not instantly live)
- See effective state: YES (via API; NOT via UI)
- Pause / Resume / Stop: PARTIAL (single `enabled` toggle only — pipeline stops but the OS process itself is not controlled)
- Change configuration safely: YES (validated, audited, row-locked)
- Monitor health: YES (from Checkpoint 64.3, unaffected)
- Observe signals: YES (from prior checkpoints, unaffected)
- Know paper execution state: YES (from prior checkpoints, unaffected)
- **Without restarting the application**: YES for timeframe/strategy; PARTIAL for universe; **but there is no UI**, so in practice today's operator still cannot do any of the above without directly calling the API.

**Blockers in priority order:**
1. No operator UI — the single largest gap between "technically solved" and "operator can actually use it."
2. Pause/Stop are not a true 4-state lifecycle.
3. Universe changes are not instantly live (require reconnect).

## Git Status

```
On branch main
Your branch is ahead of 'origin/main' by 23 commits.

Changes not staged for commit:
	modified:   src/intraday/application/repositories/worker_runtime_status.py
	modified:   src/intraday/infrastructure/api/urls.py
	modified:   src/intraday/infrastructure/persistence/management/commands/run_market_data_worker.py
	modified:   src/intraday/infrastructure/persistence/models.py
	modified:   src/intraday/infrastructure/persistence/worker_runtime_status_repository.py

Untracked files:
	src/intraday/application/contracts/scanner_configuration.py
	src/intraday/application/repositories/scanner_configuration.py
	src/intraday/infrastructure/api/scanner_configuration_views.py
	src/intraday/infrastructure/market_data_providers/dhan/scanner_universe.py
	src/intraday/infrastructure/persistence/migrations/0021_scannerconfiguration_and_more.py
	src/intraday/infrastructure/persistence/scanner_configuration_repository.py
	tests/unit/infrastructure/api/test_scanner_configuration_api.py
	tests/unit/infrastructure/persistence/management/test_subscribe_message_batching.py
	tests/unit/infrastructure/persistence/test_scanner_configuration_repository.py
```

`git log --oneline -3` (before this checkpoint's commit):
```
190b801 Checkpoint 64.3: truthful live-worker health + watchdog wired in + status API/UI
29312e1 Checkpoint 64.2: live worker now reaches the strategy/signal/risk/paper pipeline
8a5ecc6 Checkpoint 64.1: real Dhan provider + reconnect + watchdog + token renewal
```

`git rev-list --left-right --count origin/main...HEAD`: `0	23` (0 behind, 23 ahead — local-only, never pushed, per standing rule).

This checkpoint's changes will be committed **locally only**. No push to origin will be performed.
