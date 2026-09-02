# Checkpoint 67.12.2 — True Export Snapshot + Production Execution Authorization Boundary

Critical audit of checkpoint 67.12.1's claimed fix, followed by the smallest correct
implementation of a genuine transaction-snapshot guarantee and a narrow, testable
pre-execution authorization boundary. The real migration was NOT executed. No Dhan
calls were made. No production `MigrationRun`/`MigrationUnit`/`MigrationRow` rows
were created.

---

## A. 67.12.1 audit findings

**FACT** — `_fetch_payload_rows()` (pre-67.12.2) issued exactly ONE SQL statement:
one `.values()` queryset over `HistoricalBar.objects.filter(id__in=row_ids)`, which
Django compiles to one `SELECT ... WHERE id IN (...)`.

**FACT** — Under PostgreSQL's default READ COMMITTED isolation, each *statement*
(not each transaction) gets its own snapshot at that statement's start. A single
statement covering N rows is therefore guaranteed internally consistent across all
N rows. This is a documented, unconditional PostgreSQL guarantee that requires no
application code to invoke — it holds for a bare, unwrapped queryset exactly as
much as for one wrapped in `transaction.atomic()`.

**FACT** — Wrapping ONE read-only SELECT in `transaction.atomic()` does not change
what that single statement sees. `transaction.atomic()` changes the transaction
boundary (autocommit vs explicit BEGIN/COMMIT) and error-handling behaviour; it does
not, by itself, change a session's isolation level (Django's default remains READ
COMMITTED unless explicitly changed), and READ COMMITTED still gives a fresh
per-statement snapshot even inside an explicit transaction, for each additional
statement issued in that same transaction. For a transaction containing exactly one
SELECT, "per-statement snapshot" and "per-transaction snapshot" are indistinguishable
outcomes — there was never a second statement to observe a different snapshot.

**CONCLUSION, stated plainly, not softened**: 67.12.1's `transaction.atomic()`
wrapper around `_fetch_payload_rows()` was **cosmetic** with respect to snapshot
consistency. It added no new isolation guarantee. 67.12.1's own docstring (still
present, unmodified, in the current file) says this correctly and explicitly in
its own words ("the transaction wrapper does not change the single-statement
consistency guarantee... that guarantee holds with or without an explicit
transaction") — so 67.12.1 did not misrepresent what it did in its code comments,
but the checkpoint's summary framing of this as "a stronger snapshot-consistency
guarantee" (per the audit prompt) overstated it. What the wrapper legitimately
added were three narrower, real things: (a) explicit intent at the call site,
(b) a guarantee this function never silently piggybacks on a caller's already-open
transaction, and (c) stylistic consistency with `migration_execute.py`'s pattern.
None of those three is "snapshot consistency."

**Test K, scrutinized**: Test K's `_delayed_fetch` helper does not call
`_fetch_payload_rows()` or exercise its `transaction.atomic()` wrapper at all — it
builds its own raw-SQL cursor `SELECT ... WHERE id IN (...) AND pg_sleep(0.05) IS
NOT NULL`, executed with no `transaction.atomic()` wrapper of its own (default
autocommit mode, one implicit transaction per statement). It proves that ONE
multi-row SELECT statement, under PostgreSQL's READ COMMITTED default, is never
torn by a concurrent multi-row UPDATE that commits mid-statement. **This is a
pre-existing PostgreSQL property, true identically before and after 67.12.1's
change** — Test K would have passed against the pre-67.12.1 code unmodified, since
it never touches the code 67.12.1 changed. Test K is valid and a useful proof, but
it proves an existing PostgreSQL guarantee, not new behavioural change introduced
by 67.12.1. Filing it as "new proof of new behavior" would have been incorrect;
filing it as "new proof of pre-existing behavior" (its accurate characterization)
is what this checkpoint now records.

**Remaining gap 67.12.1 left unaddressed** — the ACTUAL question worth asking
(does the *whole* export — row fetch + fingerprint computation — derive from one
consistent point-in-time view?) was never answered by 67.12.1, because
`compute_payload_fingerprint()` is a pure function over rows already fetched
in-process; the risk was never "does the fingerprint computation itself re-query
the database" (it doesn't — it's pure) but rather whether two *separate* reads
(the row fetch, and any other export-cataloguing read) could straddle different
snapshots. In the pre-67.12.2 code there is in fact only one relevant read per
"before"/"after" side (`_fetch_payload_rows` + a pure fingerprint over its result),
so there was no live multi-statement snapshot-inconsistency bug — but the
*guarantee that this remains true* was undocumented and unproven at the
transaction level, and nothing prevented a future edit from adding a second read
inside `build_canary_backup` without anyone re-examining snapshot boundaries. This
checkpoint closes that architecturally, not because a bug was found, but because
the guarantee should be structural, not incidental.

**Transient-revert gap — concrete walkthrough (Part 1, item 5)**: yes, this is a
real, structural gap in the source_before/export/source_after design, and it
remains real even after this checkpoint's Part 2 change (by design — see Section D
below). Walkthrough:
1. `source_before` is read (t0). Row X currently has volume=1000.
2. Between t0 and the "after" read, an UPDATE sets row X's volume to 9999 (t1),
   then a second UPDATE reverts it back to 1000 (t2) — both committed, both
   genuinely durable writes, entirely between the two reads.
3. `source_after` is read (t3). Row X now shows volume=1000 again.
4. `fp_before == fp_after` (both computed from volume=1000) — the drift check
   reports "no drift," and the backup is accepted.
5. If, hypothetically, the actual EXPORTED payload (the one embedded in the JSON
   artifact) had been captured from a DIFFERENT read that happened to land inside
   the t1–t2 window (volume=9999), the artifact would contain a value the source
   table never durably held at any point that matters, while the before/after
   check — comparing only its own two independent reads — would still report
   equality and never notice, because it does not inspect what the *exported*
   payload actually was, only whether its own two bracket reads agree with each
   other.

In the actual pre-67.12.2 code this specific failure mode (exported rows read
from a *third*, different point in time than either bracket read) could not
happen, because `serialized_rows` was built directly from `source_before` itself
— but that was true by accident of the code's current shape, not by any
structural guarantee that source_before/source_after enforces. Test D (Section L)
demonstrates the concrete transient-revert scenario and confirms the before/after
mechanism reports "no drift" through it, exactly as this walkthrough predicts —
proving the equality check's blind spot is real, while confirming the current
code's actual export narrowly avoids being fooled by it only because of how
`serialized_rows` happens to be derived, not because before/after equality itself
is sufficient.

---

## B. Exact remaining architectural gaps (as of pre-67.12.2 code)

1. No transaction-level guarantee bound the payload-row fetch and the payload
   fingerprint together to one snapshot — true by incidental code shape, not
   structural design.
2. `source_before`/`source_after` is the ONLY defence against drift, and it is
   provably blind to a transient change-and-revert entirely inside its own
   bracket window (Section A, item 5).
3. `verify_environment_identity()` exists but is not composed with scope
   fingerprint, target identity, or the write-capability guard into one
   authorization decision — each check is independently correct but nothing
   forces a caller to check all of them together before treating a unit as
   "safe to execute."
4. No function exists anywhere in the repository that composes ALL of:
   environment identity + database identity + intended-target identity + scope
   fingerprint + evidence/snapshot requirements + the write-capability guard into
   one fail-closed decision. This is exactly what Part 3 below adds.

---

## C. Exact PostgreSQL snapshot semantics (documented, not assumed)

- **READ COMMITTED** (PostgreSQL's default, and Django's default absent explicit
  configuration): each *statement* within a transaction gets a fresh snapshot at
  that statement's start. Two statements in the same READ-COMMITTED transaction
  can see two different states of the table if a concurrent transaction commits
  in between them.
- **REPEATABLE READ**: the *entire transaction* gets one snapshot, taken at the
  first statement of the transaction (not at `BEGIN`, but at first actual query).
  Every subsequent statement in that transaction sees that same snapshot,
  regardless of concurrent commits by other sessions. It does not block or delay
  concurrent writers — it makes their commits invisible to this transaction's
  remaining reads, not disallowed.
- **SERIALIZABLE**: strictly stronger than REPEATABLE READ — additionally detects
  and aborts (with a serialization-failure error requiring application-level
  retry) transactions whose combined read/write behaviour could not have occurred
  in any serial ordering. Not used here — explicitly forbidden by the directive,
  and irrelevant to a pure read-only transaction with no writes to conflict on.

---

## D. Why the old before/after mechanism is insufficient (and remains
insufficient even after this checkpoint)

The before/after fingerprint bracket compares only two independent endpoint
reads. It can prove "the state at t0 equals the state at t3" but it structurally
cannot see, and never claimed to see, anything about states between t0 and t3 —
including a full change-and-revert cycle that happened entirely inside that
window (Section A walkthrough; Test D, Section L, demonstrates this concretely
with a real write-then-revert and confirms the check reports "no drift"). This
remains true after Part 2's REPEATABLE READ change, and is explicitly NOT fixed
by it — REPEATABLE READ only guarantees the payload rows and payload fingerprint
correspond to ONE snapshot taken at the START of the export transaction; it says
nothing about states before that transaction opened or after it closed. The
before/after check therefore remains a genuinely separate, non-redundant,
complementary check — catching drift RELATIVE TO the export transaction's
snapshot, from OUTSIDE that transaction, which the in-transaction guarantee alone
cannot see into.

---

## E. New snapshot mechanism (Part 2, implemented)

Added to `src/intraday/application/services/migration_canary_backup.py`:

- `_repeatable_read_atomic()` — a context manager that opens one
  `transaction.atomic()` block and issues `SET TRANSACTION ISOLATION LEVEL
  REPEATABLE READ` as the first statement inside it (PostgreSQL requires this
  statement to be first in the transaction).
- `_fetch_payload_rows_in_snapshot()` — the same single `.values()` query as
  `_fetch_payload_rows`, but designed to be called from WITHIN an
  already-open `_repeatable_read_atomic()` block rather than opening its own
  transaction, so it shares the caller's snapshot.
- `build_canary_backup()` now performs its "before" export (the payload-row
  fetch AND the payload-fingerprint computation derived from those rows) inside
  ONE call to `_repeatable_read_atomic()`. `serialized_rows` (what actually gets
  written into the artifact) is built from the SAME `source_before` rows read
  inside that transaction.
- `source_after` (the separate drift check) is UNCHANGED — it still calls the
  original `_fetch_payload_rows()` (its own independent READ COMMITTED
  transaction, its own separate snapshot), by design, per Section D.

**What is now proven that was not proven before**: the rows in the exported
artifact and the `payload_fingerprint` value the artifact records are
GUARANTEED, by REPEATABLE READ's transaction-duration snapshot, to correspond to
the exact same point-in-time database state — not merely "each was individually
internally consistent" (the old, weaker guarantee), but "the two together
describe one snapshot." Test C (Section L) demonstrates this directly.

**What is explicitly NOT claimed**: this does not make the export atomic with
respect to anything outside the transaction; does not prevent concurrent writes
to the real table (only makes them invisible to this transaction going forward);
does not close the transient-revert gap (Section D); is unrelated to
SERIALIZABLE's write-write conflict detection (irrelevant here — nothing in this
transaction writes).

---

## F. Isolation level and justification

**REPEATABLE READ**, set via a literal `SET TRANSACTION ISOLATION LEVEL
REPEATABLE READ` executed as the first statement inside a `transaction.atomic()`
block (the mechanism Django's ORM supports for this — there is no higher-level
`atomic(isolation_level=...)` parameter in this codebase's Django version, so the
explicit `SET TRANSACTION` statement is the correct, minimal mechanism).

- **Sufficient** because the ONLY property needed is "multiple reads inside one
  transaction observe one snapshot" — exactly REPEATABLE READ's definition, no
  more.
- **SERIALIZABLE not used** — it adds write-write conflict detection and retry
  complexity that is meaningless for a transaction that never writes; using it
  would be needless overhead the directive explicitly forbids ("Do NOT blindly
  use SERIALIZABLE").
- **No new locks added** — REPEATABLE READ in PostgreSQL uses MVCC snapshot
  isolation, not locking, for read-only transactions; no `SELECT ... FOR UPDATE`
  or advisory lock was introduced by this change.

---

## G. Environment identity architecture (Part 3 review)

`verify_environment_identity()` (67.12.1, unmodified) checks three signals:
(1) `DJANGO_SETTINGS_MODULE` ends with `.production`, (2) a live
`SELECT current_database()` round-trip matches the configured `NAME`, (3) an
out-of-band environment variable (`INTRADAY_VERIFIED_PRODUCTION_IDENTITY`) is
set and equals the live database name.

**Critical review — is this sufficient evidence of "production"?** No single
signal is (Tests F/G/H, Section L, prove each one alone is insufficient), and the
directive's own framing is correct that all three together are still spoofable
by a sufficiently motivated or careless operator: an operator could deliberately
set `DJANGO_SETTINGS_MODULE=intraday.settings.production`, connect to a
NON-production database that happens to be named identically to production, and
manually export the marker env var set to that same (wrong) database's name —
all three checks would pass while the connected database is not actually
production. This function is a **plausibility/negligence filter**, not
cryptographic proof of identity — it reliably catches accidental misconfiguration
(the overwhelmingly common real-world failure mode: running from a dev laptop
with the wrong `.env` loaded) but does not defeat a deliberately falsified
environment. This is stated explicitly rather than glossed over, and it is why
Part 3's authorization boundary treats `VERIFIED_PRODUCTION` as one necessary
input among several, never as sufficient by itself.

---

## H. Execution authorization architecture (Part 3, implemented)

New file: `src/intraday/application/services/migration_execution_authorization.py`.

- `ExecutionAuthorizationRequest` — composes `environment_identity`
  (an `EnvironmentIdentityReport`), `intended_target_unit` (a `MigrationUnitKey`),
  `backup_artifact` (a `CanaryBackupArtifact`), and `expected_scope_fingerprint`.
- `authorize_one_unit_execution()` — checks, additively (all reasons
  accumulated, never short-circuited):
  1. environment identity is `VERIFIED_PRODUCTION` (both the enum and the
     report's own `fail_closed_ok_to_proceed()`),
  2. the intended target unit's identity matches the backup artifact's recorded
     `unit_identity`,
  3. the artifact's `scope_fingerprint` matches the caller's independently
     supplied `expected_scope_fingerprint`,
  4. the artifact's own before/after and payload/before fingerprints are
     internally consistent (defense-in-depth against a hand-built/tampered
     artifact object),
  5. the EXISTING, untouched `assert_write_capable_connection_is_test_database()`
     guard does not raise.
- Fails closed: any missing/failing prerequisite → `DENIED`, never `AUTHORIZED`
  by omission. `ExecutionAuthorizationDecision.fail_closed_ok_to_proceed()`
  mirrors the same safe-default pattern as `EnvironmentIdentityReport`.

**NOT wired into `migration_execute.py`'s write path.** Reasoning (also recorded
in the module itself as `NOT_WIRED_RATIONALE`):
1. Check (1) requires `VERIFIED_PRODUCTION`, while check (5)
   (`assert_write_capable_connection_is_test_database`) by design only ever
   ACCEPTS a `test_`-prefixed database — a genuine production database is never
   `test_`-prefixed. These two checks are therefore structurally unsatisfiable
   together as this codebase is currently configured: `authorize_one_unit_
   execution` can never return `AUTHORIZED` today. Wiring an always-`DENIED` gate
   into `migration_execute.py`'s only real caller (the `--execute` management
   command, gated to the disposable pytest test database) would either silently
   break that already-proven-safe test path, or require inventing a bypass for
   tests — exactly the generic-framework complexity Part 7 forbids.
2. No real production execution path exists in this repository yet to gate in
   the first place — wiring an authorization boundary in front of a path that
   has no legitimate production caller would be authorization theater with no
   real scenario exercising it.
3. Instead, this checkpoint proves the boundary is real and load-bearing the
   honest way available now: Test J (Section L) calls `authorize_one_unit_
   execution` directly with real evidence objects (a real `CanaryBackupArtifact`
   from `build_canary_backup()`, a real `EnvironmentIdentityReport` from
   `verify_environment_identity()`) and proves DENIAL for each of four
   independently-missing prerequisites, one at a time. When a genuine production
   execution path is designed in a future checkpoint, wiring this function in
   front of it becomes the pre-tested, trivial step.

---

## I. Exact files changed

- `src/intraday/application/services/migration_canary_backup.py` — added
  `_repeatable_read_atomic()` and `_fetch_payload_rows_in_snapshot()`; changed
  `build_canary_backup()`'s "before" read to use them; `source_after` and
  `_fetch_payload_rows()` (original) left unchanged and still used for the
  after-read. No change to `CanaryBackupArtifact`'s shape or any public
  function signature.
- `src/intraday/application/services/migration_execution_authorization.py`
  (NEW) — `ExecutionAuthorizationRequest`, `ExecutionAuthorizationDecision`,
  `ExecutionAuthorizationVerdict`, `authorize_one_unit_execution()`.
- `tests/unit/application/services/test_migration_67_12_2_export_snapshot_and_authorization.py`
  (NEW) — 12 tests, A-L.
- `tests/unit/application/services/test_migration_67_12_pre_integrity_hardening.py`
  — Tests G and J updated (monkeypatch target changed from `_fetch_payload_rows`
  to `_fetch_payload_rows_in_snapshot` for the "before" read, since Part 2 moved
  which function performs that read). Test behaviour/intent unchanged; still
  proves the same before/after drift-detection property.
- `d:\IntraDay\taskReport.md` — overwritten (this file).

No changes to `migration_execute.py`, `migration_environment_identity.py`,
`migration_payload_fingerprint.py`, `migration_scope_fingerprint.py`, or any
migration file. `assert_write_capable_connection_is_test_database()` untouched.

---

## J. Exact tests added/modified

Added (`test_migration_67_12_2_export_snapshot_and_authorization.py`):
A, B, C, D, E, F, G, H, I, J, K, L — see Section L for results and per-test intent.

Modified (`test_migration_67_12_pre_integrity_hardening.py`):
- `test_g_live_before_after_mismatch_blocks_backup_acceptance` — now patches
  `_fetch_payload_rows_in_snapshot` (the new "before" read function) to mutate
  the first row, since patching the old `_fetch_payload_rows` no longer affects
  the "before" read after Part 2's change.
- `test_j_concurrent_source_mutation_during_export_stops` — now injects the
  concurrent DB mutation immediately after `_fetch_payload_rows_in_snapshot`
  (the "before" read/transaction) completes, so the real, unpatched
  `_fetch_payload_rows` "after" read genuinely observes the change.

Test K and Test L in that same file (single-statement snapshot proof;
environment-identity fail-closed proof) were left completely unmodified — both
still pass unchanged, confirming no regression to 67.12.1's prior proofs.

---

## K. Full test results

```
tests/unit/application/services/test_migration_67_12_2_export_snapshot_and_authorization.py .... (12 passed)
tests/unit/application/services/test_migration_67_12_pre_integrity_hardening.py ............ (12 passed)
24 passed, 1 warning in 16.58s
```

Broader regression sweep — all migration-related tests in
`tests/unit/application/services/`:
```
103 passed, 247 deselected, 2 warnings in 54.46s
```
(the two warnings are a pre-existing, unrelated pytest-django teardown notice
about a differently-named database, not a failure, and a schemathesis
deprecation warning — neither introduced by this checkpoint.)

---

## L. Adversarial test results (A-L)

| Test | What it proves | Result |
|---|---|---|
| A | Single-statement snapshot consistency is real but PRE-EXISTING PostgreSQL behavior, not new | PASSED |
| B | Complete export is either fully consistent or correctly refused under a concurrent update | PASSED |
| C | Payload rows and payload fingerprint correspond to the SAME transaction snapshot (the genuinely NEW guarantee) | PASSED |
| D | A real write-then-revert, entirely between two independent reads, is invisible to before/after equality — concrete proof the old mechanism's blind spot is real | PASSED |
| E | REPEATABLE READ transaction's SECOND read still reflects the FIRST read's snapshot even though a concurrent writer committed in between — genuinely distinct from Test K (which tests one statement, not two reads sharing one transaction) | PASSED |
| F | Environment identity fails closed with no marker | PASSED |
| G | A production-looking/live database name alone (no marker) is insufficient | PASSED |
| H | A marker alone, without production settings, is insufficient | PASSED |
| I | All required signals together is the only path toward `VERIFIED_PRODUCTION`; this workspace can supply the marker but not production settings, and correctly still gets `CANNOT_VERIFY` | PASSED |
| J | Authorization is DENIED if any single one of four independent prerequisites (environment identity, target-identity match, scope-fingerprint match, write-capability guard) is missing, one at a time | PASSED |
| K | The pre-existing `assert_write_capable_connection_is_test_database()` guard is untouched and still correctly accepts this workspace's real disposable test database | PASSED |
| L | No write-shaped call (`.save`/`.update`/`.bulk_create`/`.delete`/`.bulk_update`) exists in either new/changed module's actual code; `HistoricalBar.objects.count()` is identical before and after building a backup and running authorization | PASSED |

---

## M. HistoricalBar before/after invariants

| Metric | Before | After | Match |
|---|---|---|---|
| TOTAL | 16,542 | 16,542 | YES |
| REAL_DHAN | 11,442 | 11,442 | YES |
| UNKNOWN | 5,100 | 5,100 | YES |
| SYNTHETIC_TEST | 0 | 0 | YES |

Both counts independently re-queried via read-only Django ORM
(`HistoricalBar.objects.count()` and `.values('provenance').annotate(Count('id'))`)
against the live `intraday` database, once before any work in this checkpoint and
once after all work (code changes + full test suite run) completed.

**Checksum honesty note (unchanged from prior checkpoints)**: the literal hash
`efad4a2121da7db912f1867b62ffd27ae8d54d8e98efe3b5bd7cf0e0c2edfd8e` could NOT be
independently recomputed in this checkpoint either. No checksum-computation
script or management command producing that exact hash was found anywhere in
this repository (searched via `grep` for the literal hash and for any
`checksum`/`sha256` computation touching `HistoricalBar`/`REAL_DHAN`). This is
reported plainly, not assumed unchanged on faith. What WAS independently
re-verified, twice, is every count that hash is claimed to summarize (table
above), identical both times.

---

## N. Migration audit-table before/after invariants

`MigrationRun=0`, `MigrationUnit=0`, `MigrationRow=0` — independently re-queried
via `Model.objects.count()` before and after all work in this checkpoint, both
times identical, both times 0/0/0. No test in this checkpoint's own or the
modified pre-existing test file writes to these tables under the `intraday`
production alias — all `@pytest.mark.django_db` tests run against Django's own
disposable per-test-run PostgreSQL database (`test_` prefixed), which is
destroyed after the suite completes and never overlaps with the `intraday`
database queried in Section M.

---

## O. Evidence-chain status

- **SCOPE INTEGRITY** (`compute_scope_fingerprint`) — untouched this checkpoint,
  still a separate concept from payload identity, never conflated.
- **PAYLOAD INTEGRITY** (`compute_payload_fingerprint`) — untouched function
  itself; now provably bound to the SAME transaction snapshot as the rows it
  hashes (Section E), a genuinely stronger evidentiary claim than before.
- **ARTIFACT INTEGRITY** (`backup_checksum`, whole-artifact SHA-256) —
  untouched, still a separate mechanical mutation-detector over the final JSON
  body, unrelated to database snapshot semantics.
- No "byte-identical" claim is made anywhere in this report beyond what was
  actually established: payload-row equality is CANONICAL PAYLOAD EQUALITY
  (via `compute_payload_fingerprint`'s deterministic rendering), not literal
  byte-for-byte file identity, which was never tested here.
- The obsolete 67.11.6 `unit_fingerprint` was not touched, referenced, or
  reverse-engineered anywhere in this checkpoint.

---

## P. Production-readiness status

**NOT_READY**

Full honest reasoning against the directive's 8 required conditions for
`READY_FOR_ONE_UNIT_EXECUTION`:

1. True export snapshot consistency (payload rows + fingerprint, one snapshot) —
   **technically proven** (Section E, Test C). ✔
2. Environment identity positively established — **NOT met**. This workspace
   cannot boot production Django settings at all (`SETTINGS_ENCRYPTION_KEY`
   missing, per 67.12.1's finding, re-confirmed by Test I here) — `verify_
   environment_identity()` returns `CANNOT_VERIFY` and always will in this
   workspace. ✘
3. Authorization enforced at the actual execution boundary — **NOT met**, by
   deliberate design (Section H): the new authorization function exists and is
   tested, but is not wired into `migration_execute.py`'s write path, and no
   real production execution path exists to wire it into yet. ✘
4. Existing safety guards remain intact — **met**
   (`assert_write_capable_connection_is_test_database` unmodified, Test K). ✔
5. No target ambiguity — **met** for the mechanisms tested (Test J proves target
   identity is checked), but this is moot without conditions 2-3. Partial. 
6. All relevant adversarial tests pass — **met**, 24/24 (Section K/L). ✔
7. No HistoricalBar mutation during this checkpoint — **met** (Section M, and
   Test L's code-level + row-count-level proof). ✔
8. No production migration executed during this checkpoint — **met** — no
   `--execute` command was ever run; only disposable-test-database pytest runs
   occurred. ✔

Because conditions 2 and 3 are unmet — and condition 2 in particular is
structurally unmeetable in this workspace as currently configured (no
production settings can boot here) — `READY_FOR_ONE_UNIT_EXECUTION` is
**forbidden** per the directive's own rule, and this checkpoint does not
manufacture a way around that. `CONDITIONALLY_READY_FOR_PRODUCTION_PREFLIGHT`
is also too strong a claim: preflight readiness would imply the authorization
boundary is at least wired somewhere reachable from a real execution attempt,
which it deliberately is not yet (Section H's rationale). The strictest honest
value is **NOT_READY**.

---

## Q. Remaining blockers

1. No genuine production Django settings can be booted in this workspace
   (`SETTINGS_ENCRYPTION_KEY` and presumably other production secrets are
   absent by design — this workspace is not meant to reach production).
2. No real production execution entry point exists yet for
   `authorize_one_unit_execution` to guard — one would need to be designed
   (likely a new, separate, explicitly production-only command/script, NOT a
   parameterization of the existing test-only `--execute` command) before
   wiring is meaningful rather than theatrical.
3. `verify_environment_identity()`'s three signals, even when all satisfied,
   remain a plausibility filter rather than cryptographic proof (Section G) —
   a future checkpoint designing the real production path should decide
   whether a stronger identity mechanism (e.g., a signed/attested deployment
   credential) is warranted before any real one-unit write is ever attempted,
   though this is explicitly a decision for that future checkpoint, not
   something to build speculatively now.

---

## R. ONE recommended next checkpoint

Design (but do NOT execute) the actual production entry point that would call
`authorize_one_unit_execution` — a new, narrowly-scoped, non-test script/command
that: (a) is structurally incapable of running against a `test_`-prefixed
database (inverse of the existing guard, for symmetry), (b) calls `verify_
environment_identity()` and `authorize_one_unit_execution()` in sequence and
refuses to proceed past either non-affirmative result, (c) is proven, via tests
run against the disposable test database, to correctly refuse to run there (its
own guard rejecting a non-production-shaped connection) — closing the "wiring
is currently theatrical" gap named in Section H without ever touching real
production data in this checkpoint's successor either.
