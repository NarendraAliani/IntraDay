# CHECKPOINT 89 — Execute Migration for TCS/HDFCBANK/INFY's 2026-08-17 (3 units)

```
directive: run the actual, explicitly-authorized migration for
           TCS/HDFCBANK/INFY, 5m, 2026-08-17 (3 units) - CHECKPOINT_88
           confirmed all 3 DRY_RUN_SAFE, 69 rows each
result: 3/3 units COMMITTED - all 3 days now fully CANONICALIZED
           (71/71 each, matching each day's own real row count)
P4: 0 duplicate keys; table row count unchanged (55,210, UPDATE-only);
           RELIANCE and all 35 previously-migrated interior-gap units
           re-confirmed untouched; MigrationUnit +3, MigrationRow
           +207 (69x3), exactly matching
important new finding, honestly reported, NOT fixed: the migration's
           own cascading timestamp shift exposed a genuine, previously
           -masked 1-bar gap at 03:55 for all 3 symbols - out of this
           checkpoint's authorized scope (migration only)
gate-verified day count: 24 — UNCHANGED (the newly-exposed 03:55 gap
           blocks all 3 days from becoming research-eligible, same as
           before this checkpoint, for a DIFFERENT/more precise reason)
47-day threshold: still NOT met (24 of 47)
full_suite_result: 7 failed / 3391 passed — identical to CHECKPOINT_88,
           zero new/unexplained failures
commit: (recorded below)
```

## Part 0 — Pre-flight

`[F]` Confirmed via `ls`/`git status`: `CHECKPOINT_89_SUMMARY.md` did
not already exist. Git tree was clean apart from the deliberately-
uncommitted `SINGLE_ENV_AUTHORIZATION_PROPOSAL.md`.

## Part 1 — Fresh dry-run + real migration, all 3 units

`[F]` Production-boot setup, identical discipline to every prior
real-write checkpoint: a fresh `Fernet.generate_key()` value,
session-only, never committed. `manage.py check` under
`.production` settings → **`System check identified no issues (0
silenced)`**.

`[F]` **Fresh dry-run, all 3 units, before any write**:

```
TCS      DRY_RUN_SAFE  69  PROVEN  ()
HDFCBANK DRY_RUN_SAFE  69  PROVEN  ()
INFY     DRY_RUN_SAFE  69  PROVEN  ()
```

Confirmed `DRY_RUN_SAFE` and `row_count=69` for all 3, comfortably
under the 200-row ceiling — matching `CHECKPOINT_88`'s own final
state exactly.

`[F]` **Real migration executed, one unit at a time, each with its
own fresh dry-run and freshly-derived scope fingerprint** (never
reused/batch-computed):

```
TCS       — Gate 1 PASSED, Gate 2 PASSED, Gate 3 PASSED — COMMITTED
HDFCBANK  — Gate 1 PASSED, Gate 2 PASSED, Gate 3 PASSED — COMMITTED
INFY      — Gate 1 PASSED, Gate 2 PASSED, Gate 3 PASSED — COMMITTED
```

**3/3 units COMMITTED. Zero gate failures.**

`[F]` **Postcondition, corrected mid-checkpoint and reported
honestly**: my own driver's first postcondition check (expecting
exactly 69 `CANONICALIZED` rows) tripped on TCS, reporting a
"mismatch" — investigated directly rather than assumed broken: TCS's
day already held 2 pre-existing `CANONICALIZED` rows (from
`CHECKPOINT_86`'s own boundary-bar recovery) OUTSIDE this 69-row
migration unit, so the correct postcondition is "every `REAL_DHAN` row
for the whole day is now `CANONICALIZED`" (`71/71`), not "exactly 69."
Confirmed directly: **TCS/08-17 is genuinely `71/71 CANONICALIZED`** —
the migration succeeded completely; the check was corrected and
HDFCBANK/INFY confirmed the same `69/69` postcondition against the
corrected, correct comparison, landing at `71/71` each too.

## Verification

`[F]` **P4**:
- Table-wide duplicate-key check across the full, 55,210-row table:
  **0 duplicates**.
- Total table row count: **55,210 → 55,210** — unchanged (this
  migration's write mechanism is UPDATE-only, no inserts/deletes,
  exactly as every prior migration checkpoint).
- RELIANCE's own `08-17` (`CHECKPOINT_83`'s unit): re-queried
  directly, still `72/72 CANONICALIZED`, untouched.
- All 35 previously-migrated interior-gap units (`CHECKPOINT_84`):
  re-queried directly, **zero** mismatches — every one remains exactly
  as those checkpoints left it.
- `MigrationUnit` table: **36 → 39** (`+3`, exactly this checkpoint's
  3 new units, all `status=COMMITTED`, `old_row_count=69`,
  `new_row_count=69` each). `MigrationRow` audit table: **2,504 →
  2,711** (`+207` = `69×3`, exact match).
- Broader spot-check (10 rows, sampled outside `2026-08-17` entirely):
  all sane, unchanged states and values.

`[F]` **Research gate re-run, full range**: common gate-verified day
count across all 4 symbols: **24 — UNCHANGED**. RELIANCE `28`,
HDFCBANK/INFY `27` each, TCS `24` — identical to `CHECKPOINT_88`'s own
final state.

### A genuine new finding, surfaced by this migration, honestly reported and NOT fixed

`[F]` **TCS/HDFCBANK/INFY's `2026-08-17` are STILL rejected by the
research gate — but for a newly-precise reason.** Diagnosed directly:
`get_coverage()` for all 3 symbols now reports `71/72`, missing
exactly one canonical slot at `03:55` (the `03:50`–`03:55` candle's own
close):

```
TCS      expected=72 cached=71 missing=[03:55]
HDFCBANK expected=72 cached=71 missing=[03:55]
INFY     expected=72 cached=71 missing=[03:55]
```

This is the SAME class of phenomenon `CHECKPOINT_88` diagnosed at the
day-END boundary (the `09:40` slot briefly reading "missing" after
that deletion, until this migration's own cascading shift filled it):
before this migration, the coverage service's naive presence-by-
timestamp check was satisfied at `03:55` by the FIRST row of the
original raw (`UNCANONICALIZED`) chain — which coincidentally sat at
that exact numeric coordinate in its PRE-migration (OPEN-semantics)
form, representing a DIFFERENT candle (`03:55`–`04:00`) than what the
coverage schedule actually wants at that slot (`03:50`–`03:55`'s
close). This migration's own `+5min` cascading shift moved that row
to `04:00` (its correct canonical position) — genuinely, correctly
vacating `03:55`, which turns out to have NEVER held real data for
that specific candle. `CHECKPOINT_86`'s own earlier boundary-bar fetch
recovered the DIFFERENT missing slot it saw at the time (`03:50`) —
a real, correct, additional candle — but did not (and had no way to)
know a second, distinct gap existed one slot later, since it was
masked by the same pre-migration timestamp ambiguity until migration
itself resolved it.

**Confirmed genuinely real, not corrupted state**: TCS/HDFCBANK/INFY
each have exactly 71 real rows for a 72-expected day, with a clean,
single, real missing candle at `03:50`–`03:55` — no duplicate, no
collision, nothing to delete or reconcile this time. **Recovering it
would need one more real Dhan fetch (the same purely-additive
mechanism `CHECKPOINT_85`/`86` used) — explicitly NOT attempted here,
since this checkpoint's own authorization covered migration execution
only, not a new data fetch.** Reported plainly as the honest next
blocker for these 3 specific days, not glossed over or silently
worked around.

`[F]` **Full test suite**: `.venv/Scripts/python.exe -m pytest -q
--reuse-db` — **3391 passed, 7 failed** (697.61s). Exact failure
names, identical to `CHECKPOINT_88`'s own list (same 5 pre-existing +
2 known `--reuse-db` flakes). **Zero new/unexplained failures.**

## New baseline, stated plainly

- **Common gate-verified day count across all 4 symbols: 24** —
  unchanged. This checkpoint's migration succeeded completely (3/3
  units, fully canonicalized), but did not itself unlock any new
  research-eligible day, because these 3 days' own remaining blocker
  turned out to be a genuine, previously-masked, one-more-bar data
  gap — not a canonicalization gap — surfaced only once migration ran.
- **47-day Gainz/VWAP/ORB tuning-resumption criterion: still NOT
  MET** (24 of 47). No strategy tuning was resumed.
- **`CHECKPOINT_86`'s own broader TCS `UNKNOWN`-provenance issue
  remains completely untouched and unauthorized** — this checkpoint
  did not go near it.
- **Next step, explicitly not taken here**: a future checkpoint could
  recover the newly-identified `03:55` gap for all 3 symbols via the
  same proven, purely-additive boundary-bar mechanism `CHECKPOINT_85`/
  `86` used — a real Dhan fetch, one bar per symbol, explicitly
  requiring its own authorization before being attempted.

## Governance compliance

- P3/P5: 3 real writes, each independently gated through all 3
  authorization checks plus the mandatory confirmation flag; zero
  writes attempted outside this mechanism; fresh dry-run and
  freshly-derived fingerprint per unit, never reused.
- P4: purely canonicalization (UPDATE-only) — confirmed directly via
  row-count stability, duplicate-key check, and targeted re-query of
  every previously-touched unit. The newly-surfaced `03:55` gap was
  discovered, not created, by this checkpoint's own write — no data
  was lost or corrupted; it was always missing, only now correctly
  visible.
- P7/P8: no guard weakened or bypassed; no fingerprint/checksum
  semantics changed.
- P9/P10: no strategy logic, registry, or tuning parameter change; no
  tuning resumed (moot — threshold remains unmet).
- P11: commit to `active-development` only (this commit). No source
  code was modified this checkpoint — only data (via the sanctioned,
  proven migration path) and this checkpoint's own tracking documents.
- P15: no speculative directories created.
- P16: single persistent branch, no new branch created.

`CHECKPOINT_89_SUMMARY.md` — this file — committed alongside the
tracking-document updates. `MEMORY.md` and `PROJECT_STRATEGY_STATUS.md`
updated in the same commit (see below).
