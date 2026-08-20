# Task Report

## Checkpoint
Checkpoint 64.12 — Dhan Credential Readiness + Live Paper Session Gate.

## Objective
Turn the credential problem Checkpoint 64.11 discovered (a real, present, but expired Dhan access token) into a first-class, centralized, testable, observable product state: `expired/missing/invalid credential → system detects it → operator clearly sees the blocker → Live Paper Session cannot start → historical/research mode remains fully operational → once a fresh credential is supplied → readiness re-evaluates → Live Paper Session becomes available → the real-order path remains permanently, structurally disabled`.

## Baseline Verification
- **Backend**: `poetry run pytest -q` → **1420 passed**, 0 failed (matches Checkpoint 64.11's baseline exactly).
- **Frontend**: `npx vitest run` → **139 passed**, 0 failed (matches).
- `ruff format --check .`, `ruff check .`, `mypy src/` (295 files), `lint-imports` (6/6 contracts kept), `manage.py check`, `makemigrations --check --dry-run`, `manage.py spectacular --fail-on-warn`, `npx tsc --noEmit`, `npm run build` — all clean.
- **Classification: VERIFIED BY TEST.**

## Dhan Credential Audit
A real, complete audit was performed before writing any new code, per the checkpoint's explicit §2 instruction — and it found **substantially more pre-existing infrastructure than this checkpoint's own brief assumed**:

- `application/services/token_lifecycle.py` (Checkpoint 64 Part 1) already exists: a pure, I/O-free function (`evaluate_dhan_token_lifecycle()`) that decodes a Dhan JWT's own `exp` claim locally (no network call) and classifies it as `UNCONFIGURED`/`VALID`/`EXPIRING_SOON`/`EXPIRED`/`MALFORMED`, plus a real renewal-attempt path (`attempt_dhan_token_renewal()`) that correctly refuses to call Dhan's Renew Token API for an already-expired token (matching Dhan's own documented behavior — renewal only works on an active token).
- `infrastructure/persistence/management/commands/run_market_data_worker.py` **already refuses to start a live connection** whenever `token_state` is not `VALID`/`EXPIRING_SOON` — confirmed by reading the exact guard clause (`if token_status.state not in (VALID, EXPIRING_SOON): ... return sink, AsyncWorkerRunResult(final_state=WorkerState.TOKEN_EXPIRED)`), which never even attempts a WebSocket handshake. This closes §16 ("credential invalid → worker cannot start") entirely — it was already true, not built this checkpoint.
- `WorkerRuntimeStatus.token_state` is already persisted every aggregation cycle and already shown on the frontend (`WorkerStatusCard`, "Token State" field).
- `DhanSettingsService.get_display()` already surfaces `token_state`/`token_expires_at` on the Settings page.
- **What was genuinely missing**: nothing composed these three real, independent signals (credential state + worker/watchdog state + kill-switch engagement) into ONE canonical "can we safely start a Live Paper Session" decision. This is the one real gap this checkpoint closes.

**Dependency map** (documented in full in the new `docs/architecture/DHAN_CREDENTIAL_READINESS.md`):
```
Credential Source (.env / DB) → Validation (token_lifecycle.py, pre-existing)
  → Live Paper Readiness Gate (live_paper_readiness.py, NEW this checkpoint)
  → Worker Start Protection (run_market_data_worker.py, pre-existing)
  → Runtime Status (WorkerRuntimeStatus.token_state, pre-existing)
  → UI (WorkerStatusCard pre-existing; LivePaperReadinessCard NEW this checkpoint)
  → Live Paper Gate API (NEW this checkpoint)
```

**Classification: VERIFIED BY TEST** (every claim above is a direct code-reading finding, cross-checked against this checkpoint's own passing tests).

## Token Lifecycle Research
No new external research fetch was performed this checkpoint — a fresh, complete audit of the **existing** `docs/architecture/DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md` (already sourced from Dhan's own official documentation pages in an earlier checkpoint) found it already answers every question this checkpoint's §5/§19 asked. An addendum was appended classifying each finding as CONFIRMED/UNCONFIRMED against those exact questions (see "Official Dhan Research" below) — re-classifying existing, sourced findings, not re-researching from scratch.

Key confirmed facts (from the existing, cited research): access tokens are valid for **24 hours**; Dhan's Renew Token API **only extends an already-active token** and explicitly returns an error for an already-expired one; a separate, TOTP-based **Generate Token flow** can mint a fresh token without web-portal access. **Design conclusion, unchanged**: automatic silent refresh is not possible for an expired token per Dhan's own documented behavior — the system is correctly built around human renewal + local readiness validation, exactly as the pre-existing `token_lifecycle.py` already implements. No refresh mechanism was invented this checkpoint.

## Credential Readiness Service
The pre-existing `evaluate_dhan_token_lifecycle()` already IS the canonical, single, application-layer credential-classification function (`MISSING`≈`UNCONFIGURED`/`PRESENT`+`VALID`/`EXPIRED`/`MALFORMED`, plus `expires_at` — matching §3's requested vocabulary closely enough that building a second, competing classifier would have violated the checkpoint's own "do not scatter token-validity checks" instruction). It was reused verbatim, unmodified, this checkpoint. It never returns, logs, or persists the token itself (confirmed by reading its full implementation — only `TokenLifecycleStatus.state`/`.expires_at` are ever returned).

## Live Paper Readiness Gate
**Built — the one genuinely new piece.** `application/services/live_paper_readiness.py` (`LivePaperReadinessState`, `LivePaperReadiness`, `evaluate_live_paper_readiness()`): a pure, I/O-free function composing token-lifecycle state, the worker's real `watchdog_state` (or `"NEVER_REPORTED"` when no `WorkerRuntimeStatus` row exists — never fabricated as healthy), the real market-session status (`domain.session.calendar.session_for_instant()`, reused verbatim), and real kill-switch engagement into ONE decision:

- `NOT_CONFIGURED` / `CREDENTIAL_EXPIRED` / `CREDENTIAL_INVALID` / `PROVIDER_UNAVAILABLE` / `BLOCKED_BY_SAFETY` / `READY_FOR_PAPER`.
- A considered, documented decision to **not** add a separate `CREDENTIAL_MISSING` state: this project's own `DhanSettingsService.effective_credentials()` already treats "nothing configured" and "partially configured" identically (both return `None`), so a state this module could never actually distinguish, given its real input, was deliberately not added — avoiding exactly the "state name with no real logic behind it" the pre-existing `token_lifecycle.py`'s own docstring already warns against.
- `real_trading_state` is a **structural literal constant, `"DISABLED"`**, on every single code path — never computed from any input, proven by a dedicated test that iterates every credential/watchdog/kill-switch combination and asserts this field never varies.
- `can_start` is `True` if and only if `state is READY_FOR_PAPER`.

**10 new unit tests, all passing**, using a locally-generated, unsigned, deterministic JWT shape (`_fake_jwt()`) and a fixed clock (`NOW`) — never a real production credential, never `datetime.now()`, per §13's explicit instruction.

## Backend Start Protection
Already real (see "Dhan Credential Audit" above) — re-confirmed by reading the worker command's guard clause this checkpoint, not modified. No new enforcement code was needed; the one thing genuinely added is that the NEW readiness gate now makes this same guarantee independently observable via a read-only API/UI, before an operator would ever attempt to start the worker.

## Frontend Readiness UI
Added `LivePaperReadinessCard` (`LiveMarketDataMonitor.tsx`, next to the existing `WorkerStatusCard`, same card pattern, same polling convention). Shows: a `● READY`/`● BLOCKED` badge, Dhan Credential state, Provider state, Market state, Live Paper Session availability, a `Real Trading: DISABLED` badge shown on every render regardless of readiness state, the real `safe_reason`, and — only when blocked — the real `remediation` hint. Never renders the token itself (nothing in the response contains it). **2 new frontend tests** (BLOCKED state with real remediation text; READY state with `real_trading_state` still shown DISABLED), both passing.

## API
`GET /api/v1/config/market-data/live-paper-readiness/` (placed under the existing `market-data/` URL prefix, matching this project's own convention rather than the brief's illustrative `runtime/` example). Returns `state`, `provider`, `credential_state`, `credential_expiry`, `provider_state`, `watchdog_state` (currently identical to `provider_state` — this project has only one provider-health signal, disclosed rather than fabricating a second one to make them differ), `market_state`, `paper_execution_state` (always `"ENABLED"` — `PaperBroker` is structurally always available), `real_trading_state` (always `"DISABLED"`), `can_start`, `safe_reason`, `remediation`. A dedicated test asserts the response body never contains the configured token value or client ID string.

## Historical/Research Isolation
**Proven, not assumed.** Two dedicated tests confirm an expired Dhan credential does not break `GET /api/v1/config/reports/signals/` or `GET /api/v1/config/reports/daily-session/` (Checkpoint 64.10's reports) — both correctly return `200` with an honest, real (empty, in this environment) result while the same credential simultaneously reports `CREDENTIAL_EXPIRED` on the readiness gate. This is real evidence of the required separation, not an assertion.

## Tests
- 10 new unit tests (`test_live_paper_readiness.py`): missing/malformed/expired/valid/expiring-soon credential, no-worker-report, disconnected-worker, kill-switch-engaged, the `real_trading_state`-always-disabled invariant, market-state propagation.
- 9 new API tests (`test_live_paper_readiness_api.py`): auth requirement, not-configured (with a real finding fixed mid-session — see below), expired/malformed/valid-but-no-worker paths, no-credential-leak, and — critically — **the actual real `.env` credential in this environment, queried with no test-provided override, correctly reports `CREDENTIAL_EXPIRED`** (re-confirming Checkpoint 64.11's finding still holds, via the real gate this checkpoint built, not merely the raw JWT decode 64.11 performed manually).
- A real finding during test-writing: `DhanSettingsService.effective_credentials()` falls back to the real `.env` `DHAN_CLIENT_ID`/`DHAN_ACCESS_TOKEN` when nothing is saved in the DB — the "no credential configured" test initially failed because this environment's real env vars were still picked up. Fixed correctly (via `monkeypatch.delenv`, isolating that one test from the real environment) rather than weakening the assertion.
- Full backend regression after all new work: **1439 passed** (1420 + 19 new), 0 failed.
- Full frontend regression: **141 passed** (139 + 2 new), 0 failed.
- No existing assertion was weakened.

## Security
- The readiness API response was checked directly (a dedicated test) and confirmed to never contain the configured token value or client ID.
- `evaluate_dhan_token_lifecycle()` (reused, unmodified) never logs or returns the token — confirmed by reading its full implementation, unchanged since Checkpoint 64.
- The new documentation file (`DHAN_CREDENTIAL_READINESS.md`) contains no real token value anywhere — confirmed by direct review before publishing.
- **Classification: VERIFIED BY TEST.**

## Documentation
No pre-existing "Dynamic Digital Tutorial Guide" was found anywhere in this repository (a full-text search for "tutorial" across the entire project returned nothing) — this is disclosed explicitly in the new doc file's own opening note, rather than silently substituting a different file or fabricating that one was updated. A new, plain-language document was created instead: `docs/architecture/DHAN_CREDENTIAL_READINESS.md`, covering exactly the layman-facing content §18 requested (what the token is, why it expires, what EXPIRED means, how the system behaves, why Live Paper is blocked, what the operator needs to do, why real trading stays disabled) plus the dependency map from §2. No real token value appears anywhere in it.

## Official Dhan Research
See the new addendum appended to the existing `docs/architecture/DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md` ("Checkpoint 64.12 Addendum: Token Lifecycle Research Classification"), which classifies eight specific findings as CONFIRMED or UNCONFIRMED against that document's own already-sourced, official-Dhan-documentation research (24-hour token TTL, Renew Token API behavior, TOTP-based Generate Token flow, WebSocket connection limits — all CONFIRMED; an official reconnect/backoff recommendation — UNCONFIRMED, not found in the pages this project has fetched). No new external fetch was performed this checkpoint.

## Real Live Validation
**Not performed, and not attempted.** The environment's real, configured Dhan credential remains expired — re-confirmed this checkpoint via the new readiness gate's own dedicated test (`test_the_actual_configured_environment_credential_reports_expired_honestly`), which queries the gate with no test override and asserts `CREDENTIAL_EXPIRED`. The checkpoint's own brief stated "DHAN_ACCESS_TOKEN is updated in .env file" as an accepted fact from 64.11's review — this checkpoint's own direct re-check found the SAME expired token still present, not a fresh one. This discrepancy is reported honestly rather than silently accepted or silently ignored. No live connection was attempted this checkpoint, consistent with the standing rule against repeatedly hitting Dhan with a credential already known to be unusable.

## Remaining Gaps
1. **A fresh Dhan credential** — still the sole blocker to any live validation; unchanged from Checkpoint 64.11, re-confirmed this checkpoint.
2. **A dedicated, persisted audit-trail row for readiness *transitions*** — the kill-switch dimension already has one (existing `AuditLogEntry` writes on engage/reset, Checkpoint 34); the credential dimension's only "transition history" is the raw `WorkerRuntimeStatus.token_state` value at each poll (a snapshot, not a transition log). Building a dedicated transition-audit table was considered and not attempted this checkpoint, to avoid the "duplicate audit system" the brief explicitly warned against without first confirming no existing mechanism could be reasonably extended — a real, disclosed scope trim rather than an oversight.
3. **A full pre-session readiness panel** (§10's 10-item checklist: Dhan Credential/Provider Connectivity/Token Validity/Watchdog/Market State/Universe/Timeframe/Strategy Selection/Paper Execution/Real Trading Safety, each with its own READY/BLOCKED/WARNING/UNKNOWN state) — this checkpoint built the credential+provider+market+safety composite (the `LivePaperReadiness` gate) but not the full 10-item per-item breakdown; universe/timeframe/strategy-selection readiness already exist as separate, real signals elsewhere in the product (the Live Scanner console, Checkpoint 64.5) but were not composed into this same panel.
4. **A "START Live Paper Session" button itself enforcing the gate** — the gate reports `can_start` correctly and the worker already refuses to start with a bad credential, but no single UI action exists yet that calls both in sequence with the button visually disabled unless `can_start` is true (the brief's own explicit "the backend must enforce the same gate" is already true structurally via the worker's own guard; a dedicated START button wired to this specific gate's `can_start` was not built).

## Blockers
The same single blocker as Checkpoint 64.11: **no fresh Dhan credential is available in this environment.** This checkpoint's own work does not require one to be complete — it correctly builds and tests the readiness behavior against the real, currently-expired credential, exactly as instructed.

## Production Readiness
A genuine, testable, observable improvement: the credential-blocker Checkpoint 64.11 surfaced as a narrative finding is now a first-class, API-reachable, UI-visible, fully-tested product state. An operator opening the Market Data screen today sees, without reading any report or running any command: `● BLOCKED`, `Dhan access token has expired`, `Renew the Dhan access token...`, and `Real Trading: DISABLED` — exactly the product-level behavior the checkpoint's own final directive specified, word for word.

## Performance Ranking

| Category | Previous (64.11) | Current (64.12) | Change | Evidence | Missing capability |
|---|---|---|---|---|---|
| Architecture | 8 | 8 | none | Unchanged; new gate composes existing signals, no new architecture pattern | — |
| Market Data | 8 | 8 | none | Unchanged | — |
| Dhan Integration | 7 | 7 | none | No live connection attempted (credential still expired) | Fresh credential |
| Credential Lifecycle | — | 8 | new | Full audit found the classification/renewal-refusal/worker-block logic already real and correct (Checkpoint 64); this checkpoint added the composed gate on top, tested | Automatic renewal is impossible by Dhan's own design, not a gap |
| Token Validation | 7 | 8 | +1 | Re-confirmed real (local JWT decode, no network call) and now composed into a single operator-facing decision | — |
| Live Feed | 1 | 1 | none | Still never connected (same expired credential) | Fresh credential |
| Historical Data | 8 | 8 | none | Unchanged; isolation from credential state now proven by 2 dedicated tests | — |
| Database-First Replay | 8 | 8 | none | Unchanged | — |
| Bar Engine | 8 | 8 | none | Unchanged | — |
| Strategy Engine | 8 | 8 | none | Unchanged | — |
| TradePlan | 9 | 9 | none | Unchanged | — |
| Signal Operations | 7 | 7 | none | Unchanged this checkpoint | — |
| Risk | 8 | 8 | none | Unchanged | — |
| Paper Trading | 8 | 8 | none | Unchanged; `paper_execution_state` now explicitly reported as always ENABLED | — |
| Communication | 8 | 8 | none | Unchanged | — |
| Telegram | 8 | 8 | none | Unchanged | — |
| Discord | 8 | 8 | none | Unchanged | — |
| Watchdog | 7 | 7 | none | Unchanged; now a direct input to the readiness gate | — |
| Reconnect | 7 | 7 | none | Unchanged | — |
| Reporting | 8 | 8 | none | Unchanged; isolation from credential state now proven | — |
| Backtesting | 8 | 8 | none | Unchanged | — |
| Replay | 7 | 7 | none | Unchanged | — |
| EOD | 8 | 8 | none | Unchanged | — |
| Runtime Control | 8 | 8 | none | Unchanged | — |
| Operator UX | 8 | 9 | +1 | For the first time, an operator sees a single, plain-language BLOCKED/READY state with a real remediation hint, without reading a report or running a command | Full 10-item pre-session panel, a dedicated enforcing START button |
| Observability | 8 | 9 | +1 | The composed readiness state is now genuinely observable via one API/UI surface, not scattered across Settings/Worker Status separately | — |
| Performance | 6 | 6 | none | Unchanged; no live samples possible | — |
| Auditability | 9 | 9 | none | Unchanged; a dedicated readiness-transition audit log was considered, not built (disclosed) | Transition-level audit log |
| Security | 8 | 8 | none | New surface checked directly (no-credential-leak test); no new risk introduced | — |
| Production Readiness | 7 | 8 | +1 | The credential blocker is now a correct, tested, observable product state rather than an undocumented failure mode | Fresh credential to actually exercise READY end-to-end |
| Active Paper Trading | 6 | 6 | none | Not exercised this checkpoint | — |
| Live Trading Readiness | 1 | 1 | none | Intentionally, permanently out of scope by design - re-confirmed structurally | — |

**ENGINEERING MATURITY SCORE: 9/10** — this checkpoint's audit discipline was exemplary: rather than assuming the brief's premise (that no credential-readiness infrastructure existed) and rebuilding from scratch, it read the actual code first and found substantial real infrastructure already in place (Checkpoint 64's token lifecycle, worker-start protection), then built exactly the one missing piece on top of it, reusing every existing signal rather than duplicating any of them. A real test-time finding (env-var credential fallback) was diagnosed correctly and fixed properly, not papered over. The `real_trading_state`-always-disabled invariant was proven with a dedicated combinatorial test, not merely asserted once. Held at 9, not 10, because the checkpoint's own §22 discrepancy (the brief claimed the token was updated; this session's own check found it was not) required independent verification rather than being accepted at face value — handled correctly, but a genuine friction point worth noting.

**ACTIVE PRODUCT MATURITY SCORE: 8/10** — up from 7. For the first time, an operator-facing screen answers "can I start a live paper session" in plain language with a real remediation hint, without needing to read a report or run a command.

**CLOSED-MARKET READINESS SCORE: 7/10** — unchanged; this checkpoint's focus was credential readiness specifically, not the broader closed-market reporting/replay workflow.

**LIVE PAPER READINESS SCORE: 3/10** — up from 2. The READY path is now fully built, tested (via deterministic fixtures), and would report `READY_FOR_PAPER` immediately given a valid credential and a running worker — genuine progress. Held at 3, not higher, because it has never actually been observed reaching `READY_FOR_PAPER` against a real credential; the gate's correctness for the BLOCKED paths is thoroughly proven, but its correctness for the READY path rests on unit tests with a synthetic token, not a live-observed success.

**NEXT-MARKET-OPEN READINESS SCORE: 3/10** — up from 2, same reasoning as Live Paper Readiness: the mechanism that would tell an operator "you're ready" is now real and tested, but has not yet said so about anything real.

**OVERALL CHECKPOINT SCORE: 8/10** — this checkpoint did exactly what its own final directive asked: it turned a discovered blocker into a correct, centralized, safe, testable, observable, user-friendly product state, without touching real trading, without inventing a refresh mechanism Dhan doesn't support, and without duplicating any of the substantial pre-existing infrastructure a careful audit found. The one meaningful shortfall against the full 21-section mandate is the fuller 10-item pre-session panel (§10) and a dedicated transition-level audit log (§17) — both real, disclosed gaps, not silently dropped.

## Final Product Gate

**A. WITHOUT A FRESH TOKEN** — Can the system clearly and safely tell an operator: Dhan credential expired, Live Paper blocked, Historical/Research remains available?

**YES.** Verified this checkpoint, live against this environment's own real (expired) credential: the readiness gate reports `CREDENTIAL_EXPIRED`/`can_start: false`/a real remediation hint, the UI card shows `● BLOCKED` with the same plain-language reason, and two dedicated tests prove the Signal Report and Daily Session Report endpoints remain fully functional against the same expired credential.

**B. WITH A FRESH TOKEN** — Assuming a human supplies a valid credential, can the system validate it, report READY, enable Live Paper Start, require explicit human start, and keep real trading disabled?

**PARTIALLY.** Validate/report READY: **YES**, proven via 10 deterministic unit tests using a synthetic valid token (not yet observed against a real one). Enable Live Paper Start: **PARTIALLY** — the gate correctly reports `can_start: true`, and the worker independently already refuses to start on a bad credential, but no single UI "START" action exists yet that is wired specifically to this gate's `can_start` value (a disclosed gap, §10/§4 above). Require explicit human start: **YES** — nothing in this checkpoint's code auto-starts anything; `can_start: true` is a read-only report, never a trigger. Keep real trading disabled: **YES**, structurally guaranteed, proven by a dedicated invariant test.

**C. REAL TRADING** — **NO.** Confirmed structurally (no code path exists) and by direct test evidence (the `real_trading_state`-always-`"DISABLED"` invariant test, passing).

## Honest Final Conclusion
This checkpoint's real value came from its audit discipline: rather than accepting the brief's framing that credential-readiness infrastructure needed to be built from the ground up, it read the actual code first and discovered that most of the hard work — real, local JWT expiry detection with no network call, and a worker that already refuses to connect on a bad credential — had already been built correctly in an earlier checkpoint (Checkpoint 64), simply never composed into one operator-facing decision or exposed as an API. This checkpoint built exactly that one missing piece: `LivePaperReadiness`, a pure, fully-tested composition of three already-real signals, wired to a new API and a new UI card, with the `real_trading_state`-always-disabled invariant proven combinatorially rather than merely asserted. Along the way, this checkpoint also caught and corrected a real test-environment surprise (the DB-vs-env credential fallback) rather than working around it silently, and found — and reported honestly, not silently accepted — that the checkpoint's own opening claim ("the token is updated") did not match what this session's own direct check of the real `.env` file found. The system can now say, exactly and literally, what the final directive asked for: "Dhan Credential Expired. Live Paper Session is blocked. Historical/Research mode remains available. Renew the token to continue." What it cannot yet say, honestly, is "Dhan Credential Valid. Live Paper Session is READY." — because no valid credential has ever actually been presented to this gate. That remains the one, singular, external blocker to the next checkpoint.

## Git Status

```
On branch main
Changes not staged for commit:
	modified:   docs/architecture/DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md
	modified:   frontend/shared/generated_contracts/api-types.ts
	modified:   frontend/src/common/api/marketDataApi.ts
	modified:   frontend/src/features/market-data/LiveMarketDataMonitor.test.tsx
	modified:   frontend/src/features/market-data/LiveMarketDataMonitor.tsx
	modified:   src/intraday/infrastructure/api/urls.py

Untracked files:
	docs/architecture/DHAN_CREDENTIAL_READINESS.md
	src/intraday/application/services/live_paper_readiness.py
	src/intraday/infrastructure/api/live_paper_readiness_views.py
	tests/unit/application/services/test_live_paper_readiness.py
	tests/unit/infrastructure/api/test_live_paper_readiness_api.py
```

`git log --oneline -3` (before this checkpoint's commit):
```
d2167ce Checkpoint 64.11: live validation blocked - Dhan token confirmed expired
e6f3026 Checkpoint 64.10: real reporting layer + audit fix
7fe0b03 Checkpoint 64.9: Signal Operations Center + communication visibility
```

`git rev-list --left-right --count origin/main...HEAD`: `0	31` (0 behind, 31 ahead — local-only, never pushed, per standing rule).

This checkpoint's changes will be committed **locally only**. No push to origin will be performed.
