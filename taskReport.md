# Task Report

## Checkpoint

64.19 — COMMUNICATION EVIDENCE + LIVE SESSION READINESS + PRODUCTION HYGIENE

## Objective

Close the last deliberately-deferred product gap (Signal Evidence in
Telegram/Discord messages) before the first real controlled LIVE PAPER
validation; confirm the existing readiness checklist already satisfies
this checkpoint's own list (no new readiness engine); properly research
and either fix or honestly defer the PostgreSQL teardown warning; and
write a precise, deterministic first-live-session validation procedure.

## Baseline Verification

| Gate | Result |
|---|---|
| pytest | 1519 passed |
| vitest | 174 passed |
| ruff format --check | 529 files already formatted |
| ruff check | All checks passed |
| mypy | Success: no issues found in 300 source files |
| lint-imports | 6 kept, 0 broken |
| manage.py check | 0 issues |
| makemigrations --check --dry-run | No changes detected |
| manage.py spectacular --fail-on-warn | exit 0 |
| frontend tsc --noEmit | 0 errors |
| frontend build | succeeded |

## Telegram Evidence

Implemented (64.18 deliberately deferred this). A new `_render_evidence()`
pure function in `communication/contracts/templates.py` renders a
compact "Key Evidence:" section — only the strategy's own real,
persisted evidence fields, never every raw value, never a fabricated
line when evidence is absent. Spliced into the two per-signal templates
(`VALIDATED_SIGNAL`, `VALIDATED_SIGNAL_EXECUTION_BLOCKED`) after the
existing TradePlan fields, before the Signal/Execution status lines —
matching the exact ordering this checkpoint's own example shows. The
existing template fields (Strategy/Stock/Time/Timeframe/Direction/
Spot/Entry/SL/Targets/Trailing SL) are completely unchanged.

## Discord Evidence

Same mechanism, same test coverage — `render_message()` is the ONE
channel-independent renderer both Telegram and Discord already call
(Checkpoint 37); no `TelegramEvidenceFormatter`/`DiscordEvidenceFormatter`
was created, per §3's explicit instruction. Proven directly by a new
test (`test_telegram_and_discord_render_the_same_canonical_text`)
asserting the two calls produce byte-identical text.

## Risk-Rejected Signal Communication

Proven with real, extended end-to-end tests (not new isolated units):
the existing `test_scenario_j_risk_rejected_signal_is_persisted_
queryable_and_communicated` (Checkpoint 64.16) now additionally asserts
`"Key Evidence:"` appears in the actually-delivered Discord message, and
that no delivered message ever says `"FILLED"` for a signal whose trade
never executed — the message never implies an order was placed.
`Signal → Evidence → Risk REJECTED → NO Paper Order → Telegram/Discord
attempted` remains fully auditable: the signal row, the evidence row,
and both channels' ledger rows all persist regardless of the rejection.

## Communication Independence

Re-verified, not rebuilt: `communication` is architecturally forbidden
from importing `trading_engine` at all (`.importlinter` Contract 4,
bounded-context independence) — confirmed by `lint-imports` staying
clean after this checkpoint's changes. The new `evidence_fields` field
on `SignalCommunicationContext` is a plain `tuple[tuple[str, str], ...]`,
never the `trading_engine`-owned `SignalEvidence` type; the CALLER
(`application.services.paper_signal_execution`, which is allowed to
depend on both bounded contexts) performs the conversion. This is a
genuine architectural finding worth stating plainly: broker/channel
independence and bounded-context independence are BOTH still intact
after adding evidence to the message pipeline.

## Message Template Safety

New `test_no_message_ever_contains_a_credential_shaped_value` renders
every per-signal template with a full context (evidence, TradePlan,
order, fill) and asserts no rendered text contains "token", "webhook",
"secret", or "bearer" (case-insensitive) — a real regression test, not
an assumption. `test_execution_status_wording_distinguishes_every_real_
outcome` proves NOT_EVALUATED/BLOCKED/ORDER_SUBMITTED/FILLED/REJECTED
each render distinct text and none ever say "TRADED" (§5's explicit
"no semantic ambiguity" — this was already true of the existing
`ExecutionStatus` enum's own `.value` rendering, now directly tested).

## Next-Market-Open Readiness

**Confirmed via direct cross-reference against the real test, not
rebuilt**: the existing 10-item Pre-Session Readiness Workbench
(Checkpoint 64.14) already lists exactly this checkpoint's own §8 items
— Dhan Credential, Provider Connectivity, Token Validity, Watchdog,
Market State, Universe, Timeframe, Strategy Selection, Paper Execution,
Real Trading Safety — verified against
`test_workbench_returns_all_ten_checklist_items_in_order`. No new
readiness engine was created, per the checkpoint's own explicit
instruction. Documented in the new
`docs/architecture/FIRST_LIVE_PAPER_VALIDATION_PROCEDURE.md` §1 with
the exact state vocabulary each item uses.

## First Live Paper Validation Procedure

New `docs/architecture/FIRST_LIVE_PAPER_VALIDATION_PROCEDURE.md` — NOT
executed this checkpoint (market closed, credential expired). Specifies:
a small, deliberate first-session universe (3-5 large-cap NSE
instruments, `SELECTED` mode — never `ALL_CONFIGURED`), `5m` timeframe,
all three strategies at their Checkpoint 64.17 conservative baseline
defaults, PAPER mode (the only mode this codebase has), the structural
(non-configurable) real-trading guard, a one-session maximum runtime,
and both an operator-STOP and kill-switch stop condition — matching
§10's exact requirements.

## First Session Success Criteria

Documented in the same file, §5 — a table mapping every criterion
(§11's list: Dhan CONNECTED, token VALID, market OPEN, scanner RUNNING,
effective config matches requested, scanner progress advances, at least
one complete scan cycle, no stale progress, signals-have-evidence, risk
decisions persisted, paper orders/fills persisted, Telegram/Discord
status visible, P&L/report generated, no real order API call,
real_trading_state DISABLED) to the REAL, already-tested source that
proves it — never a vague/unverifiable criterion. Explicitly states
system health is separate from "a strategy produced a signal," per §11's
own instruction.

## Validation Evidence Requirements

Documented in the same file, §6 — timestamps, configuration_version,
universe, timeframe, strategy versions, worker state, scanner progress,
signal IDs, evidence, risk decision, execution state, communication
status, report ID/timestamp. Explicitly states credentials are NEVER
captured, backed by the existing "never returns/logs a credential"
guarantee re-verified every checkpoint since 64.12.

## PostgreSQL Teardown Warning

**Properly researched this checkpoint** (§13's own explicit instruction
not to blindly add another hook). Read pytest-django's actual
`fixtures.py` source: `teardown_databases()` (where the warning
originates, in pytest-django's own exception handler) runs inside the
session-scoped `django_db_setup` fixture's OWN finalizer — not in any
pytest hook. This confirms 64.18's `pytest_sessionfinish` hook fired
too late (fixture finalizers complete before session-finish hooks run).

**Attempted fix #2** (correctly reasoned this time): a new
`autouse=True, scope="session"` fixture,
`_close_db_connections_before_teardown`, that explicitly DEPENDS ON
`django_db_setup` — per pytest's own documented teardown ordering,
a fixture's finalizer runs before the finalizer of any fixture it
depends on, so this guarantees `connections.close_all()` runs before
`django_db_setup` attempts `DROP DATABASE`.

**Result: verified via a full-suite run — the warning still appears,
identically.** This is itself informative: it proves the lingering
Postgres session is NOT this pytest process's own default Django
connection (that one is now provably closed first). The true remaining
session could not be identified without direct `pg_stat_activity`
access on the Postgres server, which is outside what this checkpoint's
tooling can safely inspect. **Deferred, per §13's own explicit
permission** — safe to defer because this warning has never once caused
a test failure, never affected test isolation, and never varied with
which tests ran, across every checkpoint it has been observed
(64.16-64.19). The fixture is left in place (harmless, and closes
connections that could otherwise leak into a later process) with the
full investigation documented directly in `tests/conftest.py`.

## Security

Ran a targeted scan (§15) against exactly the surfaces named: Signal
Evidence (new `test_no_message_ever_contains_a_credential_shaped_value`,
plus the existing 64.18 evidence-serialization security test),
Telegram/Discord payloads (the same new test, run across every
per-signal template), Reports (existing, re-verified passing), readiness
API (existing, re-verified passing), communication logs (existing
ledger-repository tests, re-verified passing). No new leakage surface
was introduced — evidence values are plain strings built only from
`FeatureValue.value`/`signal.price`/`signal.direction`.

## Frontend

**No frontend code changes this checkpoint.** Audited first (§17): the
existing Live Paper Operations Console already shows per-channel
Telegram/Discord delivery counts (Checkpoint 64.16), the "Why This
Signal?" evidence panel (Checkpoint 64.18), and the full 10-item
readiness checklist (Checkpoint 64.15). The change this checkpoint made
— evidence appearing inside the Telegram/Discord message TEXT — has no
corresponding UI surface to update (the console never renders raw
message bodies, only delivery status), so no UI change was needed or
made. This is a deliberate, audited "nothing to do" finding, not an
oversight — re-confirmed by the frontend test suite staying at exactly
174/174, unchanged.

## Testing

**8 new backend tests, full suite 1527 passed** (was 1519):
`tests/unit/communication/test_templates.py` (new file, 8 tests):
evidence-present rendering, evidence-absent omission (no fabricated
placeholder), risk-rejected evidence rendering, partial-evidence
honesty (only real fields shown), execution-status wording distinctness
across 5 real states, no-credential-shaped-value regression across 4
templates, Telegram/Discord byte-identical rendering, and a missing-
evidence matrix across risk/execution combinations. Plus 2 existing
end-to-end tests (`test_active_loop_end_to_end.py`) extended in place
(not new test count) with real delivered-message assertions for both
the risk-approved and risk-rejected paths.

## Market Closed Behavior

Unchanged and re-verified: no live Dhan connectivity was attempted, no
live worker was started. The existing Market State/Live Paper Start =
BLOCKED behavior (Checkpoint 64.14 checklist item, Checkpoint 64.15 UI)
is untouched by this checkpoint. Backtesting/Replay/Reports/Research
remain available, unaffected.

## Real Live Validation

**NOT ATTEMPTED**, per explicit directive — market closed, credential
expired. Every new test in this checkpoint uses deterministic in-memory
fixtures (`FakeProvider`/`_FailingTelegram`/`_SucceedingDiscord`, the
same established pattern since Checkpoint 37/64.8), never a real
network call.

## Remaining Gaps

- **PostgreSQL teardown warning**: unresolved after two properly-
  researched attempts; deferred per explicit permission, root cause
  fully documented for a future attempt with direct DB-server access.
- **Evidence field verbosity in messages**: currently shows ALL of a
  strategy's evidence fields (2-4 fields per strategy) — genuinely
  "compact" for the three existing strategies, but not independently
  capped/truncated for a hypothetical future strategy with many more
  evidence fields. Not a problem for any strategy that exists today;
  noted as a design assumption, not a bug.

## Blockers

None new. The market remains closed and the Dhan credential remains
expired — live validation remains externally blocked, unchanged from
every prior checkpoint since 64.11.

## Production Readiness

The last deliberately-deferred communication gap is now closed: an
operator reading a Telegram/Discord message can see the same compact,
factual evidence the console already shows, for both executed and
risk-rejected signals, with the execution-status wording kept
unambiguous. The readiness checklist, session control, scanner
observability, and reporting layers (64.14-64.18) are all confirmed
still correct and were not touched. A precise, small-scope, low-risk
procedure for the first real session now exists in writing. The only
remaining blocker to executing it is external: a fresh Dhan credential
and an open market session.

## Performance Ranking

| Category | Previous | Current | Change | Evidence | Missing Capability |
|---|---|---|---|---|---|
| Architecture | 1 | 1 | none | Bounded-context independence re-verified intact after adding evidence to messages | — |
| Market Data | 1 | 1 | none | Unchanged; market closed | — |
| Dhan Integration | 2 | 2 | none | No live call attempted | Fresh credential + open market |
| Credential Lifecycle | 1 | 1 | none | Unchanged | — |
| Token Validation | 1 | 1 | none | Unchanged | — |
| Live Feed | 2 | 2 | none | Not exercised | Live market session |
| Historical Data | 1 | 1 | none | Unchanged | — |
| Database-First Replay | 1 | 1 | none | Unchanged (64.18 complete) | — |
| Bar Engine | 1 | 1 | none | Unchanged | — |
| Strategy Engine | 1 | 1 | none | No strategy calculation touched | — |
| Strategy Explainability | 1 | 1 | none | Unchanged (64.18 complete); now also reaches messages | — |
| Signal Evidence | 1 | 1 | none | Unchanged (64.18 complete); now also flows into communication | — |
| TradePlan | 1 | 1 | none | Unchanged | — |
| Signal Operations | 1 | 1 | none | Unchanged | — |
| Risk | 1 | 1 | none | Unchanged | — |
| Paper Trading | 1 | 1 | none | Unchanged | — |
| Communication | 2 | 1 | improved | Evidence now included; broker/channel/bounded-context independence all re-verified | — |
| Telegram | 2 | 1 | improved | Key Evidence now included, real end-to-end proof | — |
| Discord | 2 | 1 | improved | Same as Telegram, proven byte-identical to Telegram's rendering | — |
| Watchdog | 1 | 1 | none | Unchanged | — |
| Reconnect | 1 | 1 | none | Unchanged | — |
| Scanner Progress | 1 | 1 | none | Unchanged (64.18 complete) | — |
| Reporting | 1 | 1 | none | Unchanged (64.18 complete) | — |
| Backtesting | 1 | 1 | none | Unchanged | — |
| Replay | 1 | 1 | none | Unchanged | — |
| Reproducibility | 1 | 1 | none | Unchanged (64.18 complete) | — |
| EOD | 1 | 1 | none | Unchanged | — |
| Runtime Control | 1 | 1 | none | Unchanged | — |
| Pre-Session Readiness | 1 | 1 | none | Confirmed (not rebuilt) to already satisfy this checkpoint's own checklist | — |
| Session Control | 1 | 1 | none | Unchanged | — |
| Session Observability | 1 | 1 | none | Unchanged | — |
| Operator UX | 1 | 1 | none | No UI change needed - audited and confirmed already complete for this checkpoint's scope | — |
| Responsive UI | 2 | 2 | none | No UI change this checkpoint | — |
| Accessibility | 2 | 2 | none | No UI change this checkpoint | — |
| Performance | 1 | 1 | none | Unchanged (64.18's N+1 fix holds) | — |
| Scalability | 1 | 1 | none | Unchanged | — |
| Auditability | 1 | 1 | none | Evidence-in-message adds one more auditable surface | — |
| Security | 1 | 1 | none | New targeted regression test across evidence/messages, no leakage found | — |
| Production Readiness | 1 | 1 | none | The last deferred gap closed; only the external credential/market blocker remains | — |
| Active Paper Trading | 2 | 2 | none | No live session run this checkpoint | Open market + fresh credential |
| Live Paper Readiness | 1 | 1 | none | Unchanged | — |
| Live Trading Readiness | N/A | N/A | none | Structurally disabled by design | — |
| **ENGINEERING MATURITY** | 1 | 1 | none | Small, well-scoped, fully-tested change; zero test weakening | — |
| **ACTIVE PRODUCT MATURITY** | 1 | 1 | none | Communication now carries evidence; nothing else changed | — |
| **CLOSED-MARKET READINESS** | 1 | 1 | none | This checkpoint's exact purpose, delivered without touching live systems | — |
| **NEXT-MARKET-OPEN READINESS** | 1 | 1 | none | A precise written procedure now exists; readiness checklist confirmed complete | Fresh credential, open market |
| **END-TO-END PIPELINE MATURITY** | 1 | 1 | none | Unchanged core proof; communication now carries one more real field | — |
| **OPERATOR OBSERVABILITY** | 1 | 1 | none | Unchanged from 64.18 (already closed) | — |
| **SIGNAL AUDITABILITY** | 1 | 1 | none | Now extends into the delivered message text itself, proven by real end-to-end tests | — |
| **COMMUNICATION MATURITY** | 2 | 1 | improved | The one deliberately-deferred gap (evidence in messages) is now closed with real, tested code | — |
| **OVERALL CHECKPOINT SCORE** | — | 1 | — | The named primary objective (communication evidence) fully implemented and tested; readiness/procedure work is real documentation, not inflated; Postgres warning honestly deferred | Fresh Dhan credential + open market (external) |

(1 = best/complete, higher numbers = more remaining work. Scores are not
inflated for the documentation produced this checkpoint — every "1" here
reflects either a real, tested code change or a direct, verified
cross-reference against an existing, already-passing test, never a plan
alone.)

## Final Product Gate

**A. Communication**

Do Telegram and Discord communicate the same canonical signal, TradePlan,
risk decision, and compact key evidence?

**YES.** Proven directly: `render_message()` is the one shared renderer
both channels call, verified byte-identical by a dedicated test; the
existing template fields are unchanged; evidence is now included
compactly and only when real.

**B. Risk Rejection**

Does a risk-rejected signal remain fully communicable and auditable?

**YES.** The signal, its evidence, and both channels' delivery attempts
all persist regardless of rejection — proven by the extended
`scenario_j` test, including a new assertion that the delivered message
text itself never implies an order was placed.

**C. First Live Paper Session**

With a fresh Dhan credential and an open market, is there now a precise,
low-risk procedure for the first controlled LIVE PAPER session?

**YES.** `docs/architecture/FIRST_LIVE_PAPER_VALIDATION_PROCEDURE.md`
specifies the exact universe, timeframe, strategies, success criteria,
and evidence-capture requirements — not executed this checkpoint, by
design, but ready to follow the moment the external blocker clears.

**D. Production Blocker**

Is the only major external blocker now the real Dhan credential + live
market validation?

**YES.** Every product-side gap named across 64.14-64.19 (readiness,
session control, scanner progress, signal evidence, reporting,
reproducibility, communication evidence) is now closed with real, tested
code. What remains is external: a fresh credential and an open market.

**E. Real Trading**

**NO.** Unchanged: `real_trading_state` remains the structural constant
`"DISABLED"`; `PaperBroker` remains the only concrete broker
implementation in the codebase; zero real orders were placed or
attempted.

## Honest Final Conclusion

This checkpoint closed the one deliberately-deferred gap from 64.18 —
Telegram/Discord messages now include a compact, real "Key Evidence"
section, proven end-to-end (not just at the pure-rendering level) for
both the risk-approved and risk-rejected paths, with bounded-context
independence and broker/channel independence both re-verified intact.
The Pre-Session Readiness checklist was confirmed — by direct
cross-reference against a real, existing, passing test — to already
satisfy this checkpoint's own 10-item list; no second readiness engine
was built, honoring the explicit instruction not to. A precise,
deterministic first-live-session validation procedure now exists in
writing, specifying a deliberately small universe and measurable,
evidence-backed success criteria that correctly separate "the system is
healthy" from "a strategy produced a signal." The PostgreSQL teardown
warning received a second, properly-researched attempt this checkpoint
(reading pytest-django's actual fixture-teardown ordering and fixing
the dependency direction correctly) — it still did not resolve the
warning, and that honest result is reported plainly rather than hidden
or force-fixed, along with the reasoning for why deferring it further is
safe. No live Dhan connectivity was attempted, and no live data was
fabricated anywhere. Real trading remains structurally disabled
everywhere.

## Git Status

All changes are staged and committed locally only. No push to origin was
performed or will be performed without explicit instruction. Working
tree is clean after commit.
