# Checkpoint 64.14: Complete Live Paper Operator Workbench + Session Observability

## Objective

64.13 delivered the backend-enforced START/STOP workflow for a Live Paper
Session but left six gaps, stated verbatim in its own report: (1) the full
10-item pre-session readiness workbench, (2) an explicit Effective Session
Configuration presentation, (3) session-specific audit action semantics,
(4) a real FAILED session-state path, (5) a consolidated Live Session
Monitor, (6) live-observed READY → START → RUNNING (blocked by the expired
Dhan credential). This checkpoint's directive instructed closing items 1-5
and explicitly forbade attempting live Dhan connectivity with the known
expired credential (item 6 remains out of scope by direction, not by
oversight).

## Baseline Verification

Full baseline (pytest, vitest, ruff format --check, ruff check, mypy,
lint-imports, manage.py check, makemigrations --check --dry-run,
manage.py spectacular --fail-on-warn, frontend tsc --noEmit, frontend
build) was run before starting and matched the clean state left by 64.13
(1459 backend tests passing, 144 frontend tests passing, all gates clean).

## Existing Architecture Reused

No new engine was built. Everything in this checkpoint is either a pure
re-presentation of already-computed signals or a plumbing change to an
existing write path:

- `LivePaperReadiness` (64.12) remains the SOLE authoritative "can we
  safely start" decision — untouched, still composes credential/watchdog/
  kill-switch/market-session state.
- `derive_live_paper_session_state()` (64.13) — extended, not replaced.
- `ScannerConfigurationRepository.save()` (64.4) — extended with an
  optional `action` parameter, default preserves original behavior.
- `WorkerRuntimeStatusRecord`, `TokenLifecycleState`, `AuditLogEntry`
  (Checkpoint 12), `SessionStatus` — all read-only inputs, unmodified.
- Token lifecycle, credential validation, PaperBroker, TradePlan, risk
  engine, communication engine, watchdog: not touched, per directive.

## Ten-Item Readiness Workbench

New pure module `application/services/live_paper_readiness_checklist.py`
exposes `build_readiness_checklist()` returning exactly 10 `ReadinessCheck`
items (`key`, `label`, `state` ∈ READY/WARNING/BLOCKED/UNKNOWN,
`explanation`, `remediation`), each a pure function of already-computed
signals — never a second I/O path:

1. Dhan Credential — from `TokenLifecycleState` (VALID→READY,
   EXPIRING_SOON→WARNING, EXPIRED/MALFORMED/UNCONFIGURED→BLOCKED).
2. Provider Connectivity — from `WorkerRuntimeStatus.watchdog_state`.
3. Token Validity — mirrors credential state; UNKNOWN when unconfigured.
4. Watchdog — HEALTHY/DEGRADED/STALE/DISCONNECTED mapping.
5. Market State — from `SessionStatus` (OPEN→READY, PRE_OPEN/CLOSING→
   WARNING, CLOSED/HOLIDAY→BLOCKED).
6. Universe — BLOCKED on empty selection, WARNING on partial subscription.
7. Timeframe — READY when a desired timeframe is set.
8. Strategy Selection — BLOCKED when no strategies selected.
9. Paper Execution — always READY (PaperBroker is unconditional).
10. Real Trading Safety — always READY (structurally disabled, matches
    `LivePaperReadiness.real_trading_state == "DISABLED"`).

9 new unit tests cover ordering and every state-mapping branch, including
all 5 `TokenLifecycleState` values and all 5 `SessionStatus` values.

## Aggregate Readiness

`LivePaperReadiness.can_start` remains the only decision authority. The
checklist is presented alongside it in the new workbench response but
never overrides or duplicates it — confirmed by the checklist module
taking `readiness` as an input, never recomputing it.

## Desired vs Effective Configuration

New `effective_session_configuration` object in the workbench response
distinguishes `desired_*` (from `ScannerConfigurationRecord`) from
`effective_*` (from `WorkerRuntimeStatusRecord`, defaulting to zero/empty
when the worker has never reported), plus an honest `drift` boolean —
`true` exactly when `effective_configuration_version != desired
.configuration_version`. Verified: `drift is True` when never started;
`drift is False` once versions match (new tests).

## Live Session Monitor

Consolidated into the single new `GET /api/v1/config/market-data/
live-paper-workbench/` endpoint, which returns `readiness`, `checklist`,
`session_state`, and `effective_session_configuration` together — one
call gives an operator UI everything needed for a monitor screen. No new
frontend screen was built this checkpoint (see Remaining Gaps); the
backend data contract for it is complete and tested.

## Session State Machine

`derive_live_paper_session_state()` extended with a FAILED check ahead of
the existing RUNNING/STARTING/STOPPING/STOPPED logic. §9's rule remains
honored: `desired.enabled` alone is never RUNNING or STOPPED — both
require `effective_configuration_version == desired.configuration_version`
as real reconciliation evidence. New STOPPING case: `desired.enabled is
False` but the worker hasn't yet reconciled → STOPPING, not STOPPED.

## FAILED State

Derived from the REAL, pre-existing `WorkerState` enum (Checkpoint 53)
values `FAILED`/`AUTH_FAILED`/`TOKEN_EXPIRED`, which `run_market_data_
worker.py`'s own guard clauses set as `final_state` on genuine startup/
runtime failure and which `worker_runtime_status_repository.py` persists
verbatim into `WorkerRuntimeStatus.worker_state`. Not fabricated for test
coverage — traced through the real write path before use. Verified by a
test that sets `worker_state="TOKEN_EXPIRED"` and asserts
`session_state == "FAILED"`.

## Audit Trail

Audited all 3 existing callers of `ScannerConfigurationRepository.save()`
before changing its signature (scanner_configuration_views.py x2,
live_paper_session.py x2 from 64.13). Added `action: str = "scanner_
configuration.update"` as an optional keyword parameter — the default
preserves the exact original label for every unmodified caller.
`live_paper_session.py`'s start/stop calls now pass `action="live_paper_
session.start"` / `"live_paper_session.stop"`. No second audit table —
the existing `AuditLogEntry` model (Checkpoint 12) is reused unchanged.
New test queries `AuditLogEntry.objects.filter(action=...)` for both
labels and confirms no token leakage into `request_id` or
`previous_version`.

## Signal Table

Not touched this checkpoint — out of the closed scope (items 1-5).

## Paper Execution / Telegram / Discord

Unchanged, reused verbatim (existing PaperBroker / Communication Engine).

## Operator UX / Responsive Design / Accessibility

No new frontend UI was built this checkpoint — the backend contract
(`live-paper-workbench` endpoint) is complete, tested, and ready for a
future frontend consumption pass. This is an honest, explicit scope
reduction, not an oversight: the directive's five closed items are all
backend/data-contract items (readiness workbench data, effective
configuration data, audit semantics, FAILED derivation) except for the
"consolidated Live Session Monitor," whose data contract is done but
whose UI screen was not built this pass.

## API

New endpoint: `GET /api/v1/config/market-data/live-paper-workbench/`
(`live_paper_readiness_views.live_paper_workbench`), authenticated,
read-only, composing `LivePaperReadiness` + checklist + session state +
effective/desired configuration in one response. Schema passes
`manage.py spectacular --fail-on-warn`. A `ReadinessCheckSerializer` is
kept for documentation only (a real nested serializer collided with
DRF's own `Field.label` at the mypy/stub level); the wire response uses
`ListField(child=DictField())` to preserve the exact `"label"` JSON key
without the type-checker collision.

## Testing

Backend: 17 new tests this checkpoint (9 checklist, 2 session-state
[STOPPING-not-yet-reconciled, FAILED parametrized over 3 worker states],
1 audit-label distinguishability, 5 workbench API). Full suite:
**1477 passed**, 0 failed (up from 1459 baseline + 18 net new/counted).
Frontend: **144 passed**, 0 failed, unchanged (no frontend code touched).

## Security

No token value is ever returned or logged by the new endpoint (verified
by the pre-existing `test_response_never_contains_the_configured_token_
value` pattern and by the new audit-label test explicitly asserting the
token is absent from `request_id`/`previous_version`). The workbench
endpoint requires authentication (`IsAuthenticated`), matching the
existing readiness endpoint's contract.

## Historical/Research Isolation

Not modified. Existing tests confirming an expired credential does not
break the Signal Report / Daily Session Report endpoints continue to
pass unchanged.

## Official Dhan Research

No new assumption required verification this checkpoint — the FAILED-
state derivation relies on this codebase's own `WorkerState` enum and
`run_market_data_worker.py`'s own guard clauses (Checkpoint 53), not on
any new claim about Dhan's external API behavior. The existing research
document (`DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md`) was not touched.

## Real Live Validation

NOT ATTEMPTED, by explicit directive: "Do NOT attempt live Dhan
connectivity with the known expired credential." No live Dhan call was
made. `test_the_actual_configured_environment_credential_reports_expired_
honestly` (64.12) continues to pass against this environment's real
`.env` token, confirming it remains expired (OBSERVED, via existing test,
not re-investigated this checkpoint).

## Remaining Gaps

- Frontend consumption of the new `live-paper-workbench` endpoint: no
  10-item checklist display, no Effective Session Configuration UI
  section, no consolidated Live Session Monitor screen were built. The
  backend contract is complete and tested; the UI work is the next
  logical checkpoint.
- Item 6 from 64.13 (live-observed READY → START → RUNNING) remains
  blocked by the expired Dhan credential, unchanged, by explicit
  directive not to attempt it.
- Signal Table changes (§13 of the original 64.14 directive) not
  attempted.

## Blockers

The Dhan credential in this environment's `.env` remains expired
(confirmed again via the pre-existing, still-passing test against the
real environment value). No live Dhan session can be observed until a
human operator renews it — this is a real, external blocker, not a code
gap.

## Production Readiness

The pre-session readiness data contract, audit trail, and session-state
derivation are all real and test-covered. The operator-facing UI to
consume them does not yet exist, so an operator today would need to call
the API directly to see the checklist/effective-configuration/session-
state — not yet a complete operator product experience.

## Performance Ranking

| Category | Rank (1=best) |
|---|---|
| Correctness of session-state derivation | 1 |
| Audit trail fidelity | 1 |
| Readiness checklist accuracy | 1 |
| Backend test coverage | 1 |
| API contract completeness | 2 |
| Security (no credential leakage) | 1 |
| Reuse of existing architecture | 1 |
| Frontend consumption of new data | 5 (not built) |
| Operator UX completeness | 4 |
| Responsive design | N/A (no new UI) |
| Accessibility | N/A (no new UI) |
| Live validation | N/A (blocked by directive) |
| Historical/research isolation | 1 |
| Migration safety | 1 (no schema change) |
| Type safety (mypy) | 1 |
| Import-layer discipline | 1 |
| Lint cleanliness | 1 |
| Schema generation cleanliness | 1 |
| Idempotency | 1 |
| FAILED-state legitimacy | 1 |
| Documentation honesty | 1 |
| Scope honesty | 1 |
| Communication Engine reuse | 1 (unchanged) |
| Reporting reuse | 1 (unchanged) |
| Paper execution correctness | 1 (unchanged) |
| Risk engine reuse | 1 (unchanged) |
| TradePlan reuse | 1 (unchanged) |
| Watchdog reuse | 1 (unchanged) |
| Token lifecycle reuse | 1 (unchanged) |
| PaperBroker exclusivity | 1 (unchanged, verified) |
| Real trading safety (structural) | 1 |
| Git hygiene (local-only) | 1 |
| Backend regression stability | 1 (1477/1477) |
| Frontend regression stability | 1 (144/144) |
| Quality-gate cleanliness (all 9 gates) | 1 |
| Overall backend delivery | 1 |
| Overall frontend delivery | 5 (none this checkpoint) |
| **Overall checkpoint** | **2** (strong backend, no new UI) |

## Final Product Gate

**A. Is the operator-facing pre-session readiness workbench complete?**
- A1 (10-item checklist available): YES, via API — NOT via UI.
- A2 (Effective Session Configuration distinguishable from desired): YES,
  via API — NOT via UI.
- A3 (Aggregate `can_start` remains sole authority): YES.

**B. Is there a consolidated Live Session Monitor?**
NO — the data contract exists (one endpoint, all needed fields); the
consolidated UI screen was not built this checkpoint.

**C. Can a live paper session be started/observed with a fresh
credential?**
NOT VERIFIED — blocked by the known-expired `.env` token, and live
connectivity was explicitly out of scope by directive.

**D. Can real (non-paper) trading be enabled?**
**NO.** `real_trading_state` remains a structural constant `"DISABLED"`
on every code path; `PaperBroker` remains the only concrete broker
implementation in the codebase. Zero real broker orders were placed or
attempted.

## Honest Final Conclusion

This checkpoint closed the backend/data-contract portion of items 1-5
from 64.13's gap list with real, tested code: the 10-item readiness
checklist, the effective-vs-desired configuration comparison with an
honest drift flag, session-specific audit action labels (verified via
the existing `AuditLogEntry` mechanism, no new table), and a legitimate
FAILED session-state path derived from real worker state — all exposed
through one new, fully-tested API endpoint. The corresponding frontend
UI (checklist display, Effective Session Configuration section,
consolidated Live Session Monitor) was not attempted this pass and is
disclosed here as the clear next step, not hidden or implied to be done.
Item 6 (live-observed session start) remains blocked by the expired Dhan
credential, unchanged, per explicit directive not to attempt it this
checkpoint. No real trading capability exists or was added; PAPER mode
remains the only execution path.

## Git Status

All changes are staged and committed locally only. No push to origin was
performed or will be performed without explicit instruction.
