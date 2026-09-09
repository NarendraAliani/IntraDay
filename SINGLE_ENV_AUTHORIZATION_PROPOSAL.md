# Single-Environment Migration Authorization — Design Proposal

**Status: PROPOSAL ONLY. Not implemented, not authorized, not
committed.** This document exists for operator review before any
implementation checkpoint is written. See "Closing note" at the end.

No code was changed to produce this document. No migration was
executed. This is read/analysis only, same rigor as every prior
safety-related recon this session.

## 0. Why this document exists

`CHECKPOINT_82` confirmed, live, for the first time this session, that
`authorize_one_unit_execution()` can **never** return `AUTHORIZED`
against this project's real database, because two of its checks are
structurally unsatisfiable together:

- Check (1): `verify_environment_identity()` must report
  `VERIFIED_PRODUCTION`, which requires the connected database to be
  the REAL one (`intraday`).
- Check (5): `assert_write_capable_connection_is_test_database()` must
  pass, which requires the connected database name to **start with
  `test_`**.

A database can never simultaneously be the real `intraday` database
and be named `test_intraday`. This is not a bug — it is two guards,
each individually correct for what they were originally built to
protect, that were composed together in a way that makes one of the
two protected paths permanently unreachable.

## Part 1 — What the guard actually protects against

### 1.1 The guard's own stated purpose, read directly from its origin

`assert_write_capable_connection_is_test_database()` was written at
**Checkpoint 67.10**, for `HistoricalBarMigrationExecutor` — the class
that issues the real `UPDATE` against `HistoricalBar`. Its own module
header, quoted verbatim:

> *"This module is the sibling of `migration_dry_run.py` that is
> actually capable of issuing a real `UPDATE`... It is invoked ONLY by
> the new `migration_67_10 --execute` management command, and ONLY
> against Django's disposable pytest test database inside this
> checkpoint's own test suite."*

And the guard's own docstring:

> *"Raised (never silently swallowed) if `--execute` is ever pointed
> at a database connection whose name does not look like a Django
> disposable test database."*

**The precise, original risk this guard exists to prevent**: a
**test-only command** (`migration_67_10 --execute`, built and invoked
specifically from inside `pytest` to prove the executor logic itself
works) being run **outside** that context — by a developer at a
terminal, by a misconfigured CI job, by anything — and accidentally
issuing a real write against whatever database happened to be
configured at the time. This is a real, general risk in **any**
topology, single- or multi-environment: a command whose only tested,
intended purpose is "run inside pytest against a disposable database"
should never be able to reach real data, full stop.

**This is not "don't run against the wrong database" in the
multi-environment sense** (dev vs. staging vs. production, a mistaken
`--host` flag, a stale `.env`). It is narrower and more specific:
"don't let the TEST-ONLY entry point escape its test-only context."

### 1.2 Where the design actually broke: reuse, not the original guard

The guard itself is not the problem. The problem is that
`authorize_one_unit_execution()` (Checkpoint 67.12.2) — a
**general-purpose** authorization function later built to sit in
front of **any** real execution, including a genuine production entry
point — reused this exact same test-only guard as its own check (5),
and `migration_production_execute.py` (Checkpoint 67.13-C) — the
**actual production entry point**, built specifically to write to real
data — calls `authorize_one_unit_execution()` and therefore inherits
the identical check.

The result: the one function whose entire job is "verify this is safe
to write to REAL data" internally requires the connection to look like
a TEST database. `migration_execution_authorization.py`'s own header
comment already names this outcome explicitly, written at the time:

> *"in production that guard by design REFUSES — it only ever allows
> `test_`-prefixed databases, so it can never itself authorize a real
> production write; a genuine production execution path, if one is
> ever built, would need to replace/parameterize that guard, which is
> explicitly out of scope here and NOT done."*

This proposal is that explicitly-anticipated next step, not a novel
idea reached for on the spot.

### 1.3 Does this project have more than one real database?

`[F]` Confirmed directly: `.env`'s `POSTGRES_DB=intraday` is the
**only** database name configured anywhere. Every settings module
(`development.py`, `paper.py`, `production.py`) derives
`DATABASES["default"]["NAME"]` from the identical `POSTGRES_DB`
environment variable (`base.py:147`) — there is no staging database,
no second developer's own database, no environment-specific override
anywhere in this codebase. The only *other* database name that exists
at all is `test_intraday` — Django's own automatic `test_` + `NAME`
prefixing for the disposable pytest database, not a second real
environment.

**Stated plainly**: today, this project has exactly one real database.
The "wrong database" risk the `test_` prefix check protects against in
a genuine multi-environment deployment (accidentally running a
migration meant for staging against production, or vice versa) **does
not currently exist here** — there is nothing else to accidentally
target.

**One honest caveat, not glossed over**: `docs/architecture/
ARCHITECTURE_DECISIONS.md` decision #27 records this project's
*intended* long-term deployment shape as "single Linux VM per
environment (dev/testing/staging-paper/production)" — i.e., the
architecture anticipates a genuine multi-environment future, even
though it does not exist today. Any replacement guard should be
honest that it is scoped to **today's actual topology**, not a
permanent architectural stance — see §4's recommendation and §3's risk
assessment for how this proposal accounts for that.

## Part 2 — Proposed replacement boundary

### 2.1 What stays unchanged

Every other check `authorize_one_unit_execution()` already performs
stays exactly as built — none of it depends on the test-database
naming convention, and all of it targets real, still-relevant risks:

| Check | What it protects against | Keep as-is? |
|---|---|---|
| (1) `verify_environment_identity()` = `VERIFIED_PRODUCTION` | Running against a process that isn't genuinely, deliberately booted with real intent (production settings module + an explicit, out-of-band operator marker) | **Yes, unchanged** |
| (2) Intended target unit matches the backup artifact's own recorded identity | Executing against a *different* unit than the one the presented evidence describes (a mismatched-argument mistake) | **Yes, unchanged** |
| (3) Scope fingerprint matches the operator's independently-supplied expectation | Stale or silently-drifted scope between when the operator decided to authorize and when the write actually happens | **Yes, unchanged** |
| (4) Backup artifact internal consistency (`source_before == source_after == payload`) | The underlying rows changing mid-export, or a hand-built/tampered artifact being passed instead of a real one | **Yes, unchanged** |
| (5) `assert_write_capable_connection_is_test_database()` | Originally: the test-only command escaping its test-only context. **This is the one check being replaced** — not because it did anything wrong, but because it is being asked, via reuse, to also gate a path it was never designed for | **Replace, for the production path only** |

**Also unchanged, and this matters**: `migration_67_10 --execute`
(the actual test-only command) and `HistoricalBarMigrationExecutor`'s
own **direct** internal call to
`assert_write_capable_connection_is_test_database()` at the top of
`run()` — confirmed by direct reading
(`migration_execute.py:129-142`, the executor's own docstring: *"MUST
only ever be constructed against a connection that
`assert_write_capable_connection_is_test_database` accepts — the
executor calls that guard itself, first thing, inside `run()`, so
even a caller that forgets to check is still protected."*). This
proposal does **not** touch that call, and does **not** touch
`migration_67_10.py` or its own test suite in any way. The test-only
path keeps its own, fully appropriate, unmodified protection.

### 2.2 The actual risk in a single-environment deployment

With "wrong database" removed from the risk model (§1.3), what remains
is real and worth naming precisely:

1. **Wrong unit** — the operator fat-fingers a symbol, timeframe, or
   date and authorizes a write against data they didn't mean to touch.
   *(Already substantially mitigated by checks (2)/(3) above — a
   mismatched or stale unit is already caught.)*
2. **Unintended/accidental invocation** — a command gets run by
   habit, muscle memory, a copied-and-pasted shell history entry, or a
   script, without the operator genuinely deciding "yes, write to real
   data, right now."
3. **Unbounded blast radius** — if something DOES go wrong, how much
   real data could a single mistaken invocation touch?
4. **Replay** — the exact same command being run twice, intentionally
   or by accident (e.g. a flaky terminal, a retried CI step).

### 2.3 Recommended replacement, single approach

**Replace check (5) — for the production entry point only — with a
new, purpose-built guard**, `assert_write_capable_connection_is_
verified_production()`, alongside a small number of additional,
narrowly-scoped safeguards that target the FOUR real risks in §2.2
directly, rather than the "wrong database" risk that doesn't apply
today:

**a) The new guard itself**: requires the connected database name to
be the value already asserted by `verify_environment_identity()`'s own
`VERIFIED_PRODUCTION` verdict — i.e., re-derive "is this connection
legitimate" from the SAME positive-evidence chain check (1) already
established (real settings module + the operator's own out-of-band
`INTRADAY_VERIFIED_PRODUCTION_IDENTITY` marker), rather than from a
database-naming convention. Concretely: if `verify_environment_
identity()` already reports `VERIFIED_PRODUCTION`, this new guard adds
**no further condition of its own** — it exists only so that a
reviewer can see, in `migration_production_execute.py`'s own gate 2 (as
today), an explicit, dedicated, separately-named function call, not a
silent inheritance. This directly answers risk #1/#2 in the same way
check (1) already does — no new mechanism, just correctly re-scoped.

**b) `HistoricalBarMigrationExecutor` gains an explicit
`allow_non_test_database: bool` constructor parameter, defaulting to
`False`.** `migration_67_10.py` (the test-only command) continues
constructing it with the default (`False`) — its own call to
`assert_write_capable_connection_is_test_database()` stays completely
unmodified and mandatory. `migration_production_execute.py` (the
production entry point) is the **only** caller anywhere in this
codebase that would ever pass `allow_non_test_database=True` — and
only after all of gates 1-3 (identity, the new guard, and
`authorize_one_unit_execution()`) have already passed. This is the
"parameterize the guard" step `migration_execution_authorization.py`'s
own comment already named as necessary future work — done narrowly, a
boolean flag with a safe default, not a new framework.

**c) A mandatory, explicit, single-use operator confirmation per
invocation** — a new required `--i-have-reviewed-this-real-write`
flag (or equivalent) on `migration_production_execute` that must be
passed with no default, matching the same "explicit operator action
per checkpoint" discipline already established for live paper
sessions (an operator must consciously choose to press START; nothing
in this project auto-starts a real action). This directly targets risk
#2 (unintended invocation) — a copy-pasted command from shell history
would be missing this flag (or an operator would have to consciously
retype it), and its own presence in the command line is a visible,
reviewable signal in any logged history of what ran.

**d) A hard per-invocation scope ceiling, already implicit but worth
making explicit and enforced in code, not just by convention**: the
`--unit` argument already restricts every invocation to exactly ONE
`(symbol, timeframe, date)` — roughly 70-72 rows for a 5-minute CAS-era
trading day, confirmed directly this session
(`CHECKPOINT_82`'s own dry-run: 70 rows for RELIANCE/`5m`/
`2026-08-17`). This is already a very tight, real bound on risk #3
(blast radius) — a mistake can affect at most one symbol's one
trading day, never a range, never multiple symbols. **Recommendation:
make this an explicit, enforced assertion** (e.g., refuse to proceed
if a resolved unit's row count exceeds some generous ceiling like 200
— comfortably above one real trading day's own maximum bar count,
`ELIGIBILITY_PREDICATE_VERSION`'s own `5m` scope — rather than relying
solely on the CLI only ever accepting one unit as an informal
convention). This is a cheap, narrow, high-value addition.

**e) Replay protection — already sufficient, confirmed directly, no
new mechanism needed.** `[F]` The dry-run's own eligibility scan
(`migration_dry_run.py`) only includes rows whose
`canonicalization_state == UNCANONICALIZED`. Once a unit is
successfully canonicalized, a fresh dry-run run immediately before the
next authorization attempt would find **zero** eligible rows for that
unit — `migration_production_execute.py`'s own code already refuses
with `CommandError` when the requested unit isn't found in a fresh
plan (*"unit {unit} was not found in a fresh dry-run plan — refusing
to proceed"*). Re-running the exact same command a second time against
an already-executed unit is **already a safe, hard refusal**, not a
silent double-write. Risk #4 is already covered by existing machinery
— explicitly confirmed here, not assumed.

### 2.4 Alternatives considered, and why they were not the primary recommendation

- **A time-limited, freshly-generated one-time token** (e.g., the
  dry-run prints a random code the operator must copy into the execute
  call). Rejected as the primary mechanism: it adds real complexity
  (state to generate, store, and expire) to solve a risk (#4, replay)
  that §2.3(e) already shows is structurally handled by the existing
  eligibility-scan idempotency. Worth keeping in mind only if a future
  review finds a gap in that idempotency argument.
- **Requiring a second operator's approval (two-person rule)**.
  Rejected as disproportionate for this project's current scale (a
  single-operator research/paper-trading platform, not a team
  production deployment) — this is exactly the kind of "new generic
  framework complexity for smallest-correct-fix reasons" this
  project's own Part 7 discipline warns against. Worth revisiting only
  if/when this project genuinely reaches a multi-person operational
  posture.
- **Fully removing check (5) rather than replacing it**. Rejected —
  this would leave the production entry point with no database-
  identity-adjacent guard of its own at all beyond check (1), which
  is real but is a settings/env-var check, not a live database
  round-trip. §2.3(a)'s dedicated re-derivation keeps an explicit,
  reviewable, separately-named check in place, at negligible cost.
- **Reintroducing a "staging" database today, purely to keep the
  existing `test_`-prefix-style logic satisfiable**. Rejected as
  solving the wrong problem: it would require standing up and
  maintaining real infrastructure this project does not otherwise
  need, purely to satisfy a check's own naming convention — inverted
  effort/risk relative to just correctly re-scoping the check itself.

### 2.5 Recommendation, stated plainly

**Implement §2.3(a)-(d) together, as one coherent change, once
authorized.** Each piece is small and independently reviewable; none
of them touches the test-only path; all four directly target a real
risk identified in §2.2 rather than a risk (multi-environment
confusion) this deployment does not currently have. §2.3(e) requires
no new code — only explicit documentation that the existing
idempotency already covers replay, so a future reviewer doesn't
reinvent it.

## Part 3 — Honest risk assessment of this proposal

### 3.1 New risk introduced, compared to today's guard

**The core trade-off, stated without hedging**: today's guard is
*safer* in the narrow sense that it can **never** fire — a database
that can never be written to has zero risk of an unwanted write. Any
replacement that makes real execution *possible again* necessarily
reopens the possibility of a **genuine mistake reaching real data**,
which literally cannot happen under the current, permanently-denying
configuration. This is not a flaw in the proposal — it is the explicit
purpose of writing one: this project's own captured real data
(currently un-canonicalized rows in the interior gap) legitimately
needs a real, working execution path eventually, and "permanently
impossible" is not the same as "safe by design" once real work depends
on it. But it must be named as the actual, quantifiable trade-off, not
minimized.

The specific new risk: an operator who supplies
`--i-have-reviewed-this-real-write` **without actually having
reviewed the command carefully** (habit, haste, copying a working
invocation and only changing the date) could authorize a write against
the wrong day. This is mitigated by check (2)/(3) (mismatched or stale
scope is caught) and by the row-count ceiling (§2.3d, bounds the
damage even so) — but it is not eliminated, because a *correctly*
re-derived scope fingerprint for the *wrong but real* unit the
operator meant to type will still pass every automated check. No
purely mechanical guard can fully substitute for the operator reading
what they are about to run.

### 3.2 What would need to be true before implementing this

- **New tests, at the same rigor as 67.13-C's own 5 tests**: at
  minimum, one test proving `HistoricalBarMigrationExecutor` still
  refuses a non-test database when `allow_non_test_database=False`
  (the default — proving the test-only path's own protection is
  unchanged), one proving it accepts a non-test database only when
  explicitly passed `True` AND all upstream gates already passed, and
  one proving the new row-count ceiling actually refuses an
  oversized unit.
- **A specific review step this proposal itself cannot substitute
  for**: the operator (not this session) should decide the exact
  wording/mechanics of §2.3(c)'s confirmation flag, and the exact
  numeric value of §2.3(d)'s row-count ceiling — both are judgment
  calls about acceptable friction/risk this document deliberately
  leaves to the operator rather than picking unilaterally.
- **Re-confirmation that `migration_67_10.py`'s own test suite (the
  153-158 tests already covering the dry-run/authorization machinery)
  still passes unmodified** after `allow_non_test_database` is added
  as a new, defaulted parameter — expected to be a non-event (the
  default preserves today's exact behavior for every existing caller),
  but should be verified directly, not assumed, per this session's own
  standing discipline.
- **A live rehearsal against the real `intraday` database, on a
  single, small, already-well-understood unit** (the same RELIANCE/
  `5m`/`2026-08-17` unit `CHECKPOINT_82` already dry-run-proved SAFE),
  before scaling to the rest of the interior gap — exactly the same
  "one unit only, hard stop, review before continuing" discipline
  `CHECKPOINT_82` itself already used.

### 3.3 Reservation, stated plainly, not resolved toward "proceed"

**I have one genuine reservation, and I am not resolving it toward
"yes, proceed" on my own authority.** This is safety-critical code
whose entire prior design intentionally, permanently refuses to
execute — every checkpoint that built it (`67.10` through `67.13-C`)
did so cautiously, in small steps, explicitly declining to remove or
weaken it without direct authorization at each stage. Making it
executable again is a genuinely consequential decision, not a purely
mechanical one: once implemented, a real write to real data becomes
possible in a way it categorically is not today. I believe the design
in §2.3 is well-motivated and no less careful than what it replaces —
but "well-motivated" is my own assessment, not a substitute for the
operator's own explicit sign-off that reopening this capability is
worth the trade-off in §3.1, on the operator's own terms, not inferred
from this session's general authorization pattern.

## Closing note

**This document is a proposal for operator review. It is deliberately
left uncommitted** (matching `GAINZ_ROADMAP.md`/
`VWAP_STRATEGY_ROADMAP.md`/`ORB_STRATEGY_ROADMAP.md`'s own established
convention for exactly this kind of living, pre-decision document) —
no future checkpoint should treat its existence alone as
authorization to implement anything in it. A future implementation
checkpoint should not proceed until the operator has explicitly
reviewed this document and separately authorized specific parts of it
(§2.3's four safeguards, §2.5's recommendation, and — per §3.3 — the
underlying decision to reopen real-write capability at all).
