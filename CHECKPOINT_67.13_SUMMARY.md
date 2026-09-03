# Checkpoint 67.13 — First Real One-Unit Canonicalization Execution: HALTED at Part 0

```
checkpoint: 67.13
verdict: HALTED_PREFLIGHT_FAILED
preflight_result: 153/153 migration-related tests pass (99 + 54, two batches, listed below); no test drift found
unit_executed: NOT_APPLICABLE
rows_canonicalized: 0
evidence_trail_complete: NOT_APPLICABLE
other_rows_unaffected: YES (nothing was touched)
research_eligible_count_now: 0 (unchanged from RECON-BACKTEST)
commit: (this file only)
blockers: [the write-capable migration executor structurally refuses to write to the real database holding real captured data, by design, and this cannot be resolved without either weakening an existing safety guard (forbidden) or new, separately-authorized architecture work]
```

## A. Pre-flight re-verification results

`[F]` **Test suite**: re-ran every migration-related test file found,
in two batches (paths differ slightly from what the directive assumed
— confirmed via `Glob`, not guessed):

- Batch 1 (`test_migration_67_7_dry_run.py`,
  `test_migration_67_10_execute.py`,
  `test_migration_67_11_5_canary_selection.py`,
  `test_migration_67_11_5_connection_drop.py`,
  `test_migration_67_11_5_rollback_rehearsal.py`,
  `test_migration_67_11_6_backup_restore_rehearsal.py`,
  `test_migration_67_11_research_gate.py`,
  `test_migration_67_11_stress.py`,
  `test_migration_67_12_2_export_snapshot_and_authorization.py`,
  `test_migration_67_12_pre_integrity_hardening.py`): **99 passed**.
- Batch 2 (`test_migration_67_11_locks.py`,
  `test_checkpoint_67_9_scope_fingerprint.py`,
  `test_checkpoint_67_9_audit_schema_constraints.py`,
  `test_checkpoint_67_9_bulk_upsert_lock_ordering.py`,
  `test_checkpoint_67_8_audit_and_research_gate.py`,
  `test_checkpoint_67_8_migration_state_machines.py`,
  `test_checkpoint_67_8_migration_concurrency_and_trial.py`,
  `test_checkpoint_67_9_research_gate_migration_wiring.py`):
  **54 passed**.

**Total: 153/153 passing, no drift found.** The dry-run/authorization
machinery itself is exactly as sound as when it was built.

`[F]` **`verify_environment_identity()`**, run for real, right now,
against current `active-development`:

```
verdict = EnvironmentIdentityVerdict.CANNOT_VERIFY
settings_module = intraday.settings.development
database_alias = default
database_name = intraday
database_host = localhost
production_marker_present = False
reasons = (
  "DJANGO_SETTINGS_MODULE='intraday.settings.development' does not
   end with '.production' — this process was not booted with the
   production settings module.",
  "no positive production-identity marker found: environment variable
   'INTRADAY_VERIFIED_PRODUCTION_IDENTITY' is not set to the live
   connected database name ('intraday'). A database being reachable
   and plausibly named is NOT treated as evidence of production
   identity by this function."
)
```

Behaves exactly as documented when built (67.12.1) — correctly,
honestly fails closed to `CANNOT_VERIFY` in this workspace. **No
drift.**

`[F]` **`authorize_one_unit_execution()`**, read in full
(`migration_execution_authorization.py:78-108+`): its very first check
requires `environment_identity.verdict is
EnvironmentIdentityVerdict.VERIFIED_PRODUCTION` — given the confirmed
`CANNOT_VERIFY` above, this function would **deny** (not error — deny,
its documented, correct behavior) with reason "environment identity is
not VERIFIED_PRODUCTION." Not run against a live request object (no
unit was selected — see Section B for why), but its logic was traced
and its precondition confirmed unmet.

`[F]` **The write-capable guard, re-read directly**
(`migration_execute.py:71-79`, `assert_write_capable_connection_is_test_database()`):
requires the **actual live connection's** database name
(`connection.settings_dict["NAME"]`) to start with `"test_"`. The
current real connection — the same one holding today's real captured
`REAL_DHAN` `5m` data from checkpoints 67.12.2-F/Q and `LIVE-1` — is
named **`"intraday"`**, confirmed directly via
`verify_environment_identity()`'s own `database_name` field above. No
drift here either — this guard has never been modified, exactly as
intended (P7).

## B. The blocker — structural, by design, previously documented, now practically consequential

**Two independent checks, both traced and confirmed, both point at the
same underlying fact**: the write-capable migration executor, exactly
as safely built, **cannot ever write to the `"intraday"` database** —
the one and only database this entire project's real captured
`HistoricalBar` data actually lives in — because:

1. `assert_write_capable_connection_is_test_database()` refuses any
   connection whose name doesn't start with `"test_"`. `"intraday"`
   doesn't.
2. `authorize_one_unit_execution()` independently requires
   `VERIFIED_PRODUCTION` environment identity, which this workspace
   can never produce (`intraday.settings.production` cannot boot here
   — missing `SETTINGS_ENCRYPTION_KEY`, a fact re-confirmed, not new,
   across multiple prior checkpoints this session).

**This is not new information — 67.12.2's own report already named
this exact fact**: *"VERIFIED_PRODUCTION and the test-database guard
are currently structurally mutually exclusive... deliberately NOT
wired into `migration_execute.py`."* What's different today is that
`67.13` is the first checkpoint to actually attempt Part 4's real
execution, which makes the **practical consequence** of that
previously-abstract fact concrete: **there is currently no way, using
the real, unmodified, already-built machinery, to canonicalize even
one real row in the actual database holding real data** — not because
anything broke, but because the safety architecture was built with an
assumption (a genuine production environment, distinct from any
test-prefixed database) that this project's actual deployment
topology doesn't currently satisfy. The real database this whole arc
needs to write to is not, and structurally cannot become, a
`test_`-prefixed database without either:

- **Weakening the write guard** — explicitly forbidden by this
  checkpoint's own Part 0 instruction ("NO weakening of any existing
  safety check... If a gate fails, HALT and report — do not work
  around it") and by standing prohibition P7.
- **New, separately-authorized architecture work** — e.g. defining
  what "verified production" actually means for this project's real
  single-environment deployment (it may never have a separate
  `.production` settings module in practice), or building an
  explicitly-reviewed, narrower execution path for this specific
  single-environment case. This is real design work this checkpoint
  was not authorized to invent on the spot, and inventing it now would
  be exactly the kind of ad hoc, pressure-driven architecture change
  this project's entire discipline exists to prevent.

Per Part 0's own explicit instruction, this checkpoint **HALTs here**.
Parts 1-5 (selecting a unit, running the dry-run, asking for approval,
executing, verifying) were never reached — there is no path to a real
execution today without violating a standing prohibition or inventing
unauthorized new architecture, and this checkpoint does neither.

## C. What was NOT done, and why that's correct

- No unit was selected (Part 1) — selecting one would have implied a
  real execution was reachable, which it is not.
- No dry-run was run against a real unit (Part 2) — the existing
  153-test suite already re-confirms the dry-run machinery itself
  works; running it again against a hand-picked unit would not have
  changed today's actual blocker, which sits one layer above the
  dry-run, at the authorization/write-guard boundary.
- No `AskUserQuestion` approval was sought (Part 3) — there was
  nothing to approve; execution was never reachable regardless of the
  answer.
- **No workaround was attempted** — no temporary database rename, no
  ad hoc "verified production" environment variable set outside its
  documented, deliberate meaning, no direct-SQL bypass of
  `migration_execute.py`. All of these would constitute exactly the
  kind of guard-weakening or unauthorized architecture change this
  checkpoint's own prohibitions rule out.

## D. Honest assessment

**Did this work as designed?** The dry-run/authorization/evidence
machinery (153 tests) did — it is exactly as sound today as when
built, with zero drift across everything checked since. **What did not
work is the assumption that this machinery, once proven safe, would
have somewhere real to actually execute against.** That gap was
already documented in 67.12.2 as an abstract fact; this checkpoint is
the first to confirm it is also a **concrete, current, blocking
fact** — not a "someday" caveat.

**How many more units would this same treatment need to reach
meaningful research-eligible coverage?** Unanswerable meaningfully
right now — the question is moot until the structural blocker above is
resolved. Once resolved, scaling up is very likely a **mechanical
repeat** of the same process 67.7-67.12.2-V already built and
hardened (dry-run → scope/payload fingerprint → canary backup →
authorization → execute → verify), applied unit-by-unit or in
small batches — nothing about today's attempt suggests the
*mechanism itself* needs rework, only that it currently has no
legitimate environment to run in.

**Recommendation for a genuinely different next checkpoint**: a
dedicated, explicitly-scoped design checkpoint that resolves what
"VERIFIED_PRODUCTION" should concretely mean for this project's real,
single-environment deployment — not a code fix, a decision — before
any future `67.13`-style attempt has anywhere legitimate to execute.
This is a decision for the operator, not something to infer or
improvise.
