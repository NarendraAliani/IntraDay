# CHECKPOINT 87 — Canonicalize TCS/HDFCBANK/INFY's 2026-08-17 (BLOCKED — 0/3)

```
directive: migrate TCS/HDFCBANK/INFY's 2026-08-17 (3 units), using the
           proven CHECKPOINT_83/84 mechanism
result: 0/3 units migrated — ALL THREE correctly refused at the
           fresh-dry-run step (Task item #1), before Gate 1/2/3 were
           even reached, before any real write was attempted
root cause: CHECKPOINT_86's own boundary-bar recovery fetched each
           day's session-END bar directly (already in CLOSE-timestamp
           form, since 5m/NSE_EQ/CAS-era is 67.0-proven) — for these 3
           symbols specifically, that new row's own timestamp
           (09:45) is EXACTLY the timestamp the still-unmigrated
           09:40-raw row would shift to — a genuine collision the
           pre-existing dry-run guard (migration_dry_run.py's own
           ALREADY_CANONICAL_COLLISION classification, unmodified,
           pre-existing) correctly detects and refuses
data state: both rows hold near-identical, real market data for the
           SAME underlying candle (byte-identical high/low/close/
           volume; open differs by <0.1% for 2 of 3 symbols) — not
           corruption, a genuine duplicate representation
gate-verified day count: 24 — UNCHANGED (zero writes occurred)
47-day threshold: still NOT met (24 of 47)
full_suite_result: 7 failed / 3391 passed — identical to CHECKPOINT_86,
           zero new/unexplained failures
commit: (recorded below)
```

## Part 0 — Pre-flight

`[F]` Confirmed via `ls`/`git status`: `CHECKPOINT_87_SUMMARY.md` did
not already exist. Git tree was clean (only the deliberately-
uncommitted `SINGLE_ENV_AUTHORIZATION_PROPOSAL.md`) before this
checkpoint's own writes began.

## What happened

`[F]` Production-boot setup, identical discipline to every prior real-
write checkpoint: a fresh `Fernet.generate_key()` value, session-only,
never committed. `manage.py check` under
`DJANGO_SETTINGS_MODULE=intraday.settings.production` → **`System
check identified no issues (0 silenced)`** — genuine boot, confirmed
directly.

`[F]` **Task item #1 (fresh dry-run per unit) immediately surfaced a
real, unanticipated blocker for all 3 units** — not a ceiling issue,
not a gate-authorization issue, a genuine data-state collision:

```
TCS      2026-08-17  FAILED  70  PROVEN  ('row 7046: ALREADY_CANONICAL_COLLISION at projected new_timestamp=2026-08-17T09:45:00+00:00',)
HDFCBANK 2026-08-17  FAILED  70  PROVEN  ('row 7660: ALREADY_CANONICAL_COLLISION at projected new_timestamp=2026-08-17T09:45:00+00:00',)
INFY     2026-08-17  FAILED  70  PROVEN  ('row 8360: ALREADY_CANONICAL_COLLISION at projected new_timestamp=2026-08-17T09:45:00+00:00',)
```

None of the 3 units reached `DRY_RUN_SAFE`. Per this checkpoint's own
established discipline (diagnose before forcing anything through),
**no real command was ever attempted for any of the 3 units** — a
dry-run `FAILED` state is itself the correct, working outcome of a
pre-existing guard, not something to route around.

## Root cause, diagnosed directly

`[F]` Queried the exact colliding rows for all 3 symbols:

| Symbol | Old row (raw `09:40`) | New row (`09:45`) |
|---|---|---|
| TCS | id `7046`, `UNCANONICALIZED`, `REAL_DHAN` | id `55209`, `CANONICALIZED`, `REAL_DHAN` |
| HDFCBANK | id `7660`, `UNCANONICALIZED`, `REAL_DHAN` | id `55211`, `CANONICALIZED`, `REAL_DHAN` |
| INFY | id `8360`, `UNCANONICALIZED`, `REAL_DHAN` | id `55213`, `CANONICALIZED`, `REAL_DHAN` |

`[F]` **OHLCV comparison, both rows per symbol**:

| Symbol | Field | Old (`09:40`) | New (`09:45`) |
|---|---|---|---|
| TCS | open/high/low/close/vol | `2316.00`/`2317.30`/`2310.60`/`2314.30`/`210394` | `2315.70`/`2317.30`/`2310.60`/`2314.30`/`210394` |
| HDFCBANK | open/high/low/close/vol | `729.95`/`732.10`/`729.95`/`731.35`/`1056015` | `729.95`/`732.10`/`729.95`/`731.35`/`1056015` |
| INFY | open/high/low/close/vol | `1138.70`/`1139.30`/`1129.70`/`1136.10`/`952648` | `1138.80`/`1139.30`/`1129.70`/`1136.10`/`952648` |

**High/low/close/volume are byte-identical across both rows for all 3
symbols; open differs by a sub-0.1% amount for TCS and INFY (likely a
Dhan data-revision nuance between two separate fetch calls), and is
identical for HDFCBANK.** This is real market data, not corruption —
**both rows describe the same underlying 5-minute candle
(`09:40`–`09:45`)**, just labeled under two different timestamp
conventions:
- The OLD row's `bar_timestamp=09:40` is the PRE-canonicalization raw
  (OPEN-of-interval) label — the migration's own job is to shift it
  forward by one interval to `09:45` (the CLOSE-of-interval,
  canonical label).
- The NEW row's `bar_timestamp=09:45` arrived that way directly —
  `CHECKPOINT_86`'s own boundary-bar recovery fetched this exact
  candle fresh via the live `DhanHistoricalBarProvider`, whose
  `_candle_to_bar()` already performs the OPEN→CLOSE canonicalization
  shift BEFORE persisting (confirmed by direct code reading, unchanged
  since `Checkpoint 67.1`) — so it landed at `09:45`, `CANONICALIZED`,
  from the moment it was written.

**Neither `CHECKPOINT_86` nor this checkpoint did anything wrong.**
`CHECKPOINT_86`'s own fetch was correctly scoped to exactly the
missing `09:45` timestamp (confirmed purely additive at the time,
verified again below) — it had no way to know, and no reason to check,
that a not-yet-migrated OLD row would later want to shift INTO that
same slot. This checkpoint's own migration attempt is what surfaced
the interaction, and the **pre-existing** `migration_dry_run.py`
collision classifier (`ALREADY_CANONICAL_COLLISION`,
`migration_dry_run.py:298-301` — unmodified, dating to well before
this session's own checkpoints) caught it correctly, exactly as
designed: refusing to shift a row into an already-occupied,
already-canonical slot rather than silently creating a duplicate or
raising an unhandled integrity error.

`[F]` **RELIANCE's own `2026-08-17` (`CHECKPOINT_83`'s already-
migrated unit) is unaffected** — confirmed directly: its `09:35`/
`09:40`/`09:45` rows are all `CANONICALIZED`, `REAL_DHAN`, no
duplication, because RELIANCE was fully migrated BEFORE
`CHECKPOINT_86` ran; `CHECKPOINT_86`'s own coverage check for
RELIANCE correctly saw `09:45` as already present (from the
migration) and never needed to fetch a day-end bar for RELIANCE at
all — matching `CHECKPOINT_86`'s own recorded finding that RELIANCE's
missing range was day-start only, no day-end gap. This collision is
therefore specific to symbols whose `2026-08-17` was migrated AFTER
(or never, in this case) the day-end boundary bar was independently
recovered.

## Verification — zero writes occurred

`[F]` **P4**: table-wide duplicate-key check
(`(instrument_id, timeframe, bar_timestamp)`, `count > 1`): **0
duplicates** (the two rows per symbol have DIFFERENT `bar_timestamp`
values — `09:40` vs `09:45` — so no database constraint was ever at
risk; this is a semantic, not a structural, duplicate). Total table
row count: **55,213** — identical to `CHECKPOINT_86`'s own final
count, confirming zero rows were inserted, updated, or deleted this
checkpoint. `MigrationUnit` table: still exactly **36** rows total —
identical to `CHECKPOINT_84`'s own final count, confirming zero new
migration executions occurred. RELIANCE's own `08-17` unit re-queried
directly: still `72/72 CANONICALIZED`, untouched.

`[F]` **Research gate re-run**: common gate-verified day count across
all 4 symbols: **24 — UNCHANGED** from `CHECKPOINT_86`'s own final
count (RELIANCE individually `28`, HDFCBANK/INFY `27` each, TCS `24`)
— exactly as expected, since this checkpoint made zero data changes.

`[F]` **Full test suite**: `.venv/Scripts/python.exe -m pytest -q
--reuse-db` — **3391 passed, 7 failed** (690.85s). Exact failure
names, identical to `CHECKPOINT_86`'s own list (same 5 pre-existing +
2 known `--reuse-db` flakes). **Zero new/unexplained failures.**

## New baseline, stated plainly

- **Common gate-verified day count across all 4 symbols: 24** —
  unchanged. This checkpoint recovered ZERO of the 3 targeted units;
  the day count did not move.
- **47-day Gainz/VWAP/ORB tuning-resumption criterion: still NOT
  MET** (24 of 47, 23 short). No strategy tuning was resumed.
- **This checkpoint's own task could not be completed as specified,
  and that is reported honestly rather than worked around.** The dry-
  run's own `FAILED`/`ALREADY_CANONICAL_COLLISION` state is the
  correct behavior of an existing, unmodified safety guard — not a
  bug to route past.

## What resolving this would require (NOT implemented — a future
checkpoint's own explicit decision, same category as `CHECKPOINT_86`'s
own TCS provenance finding)

Two rows now exist per symbol for the same real-world candle. A
correct resolution would need to:
1. Decide which of the two rows is authoritative (the OLD row, once
   migrated/shifted, or the NEW row, already in its final canonical
   form) — they carry near-identical but not always byte-identical
   OHLCV (the small `open` discrepancy for TCS/INFY needs a decision,
   not an assumption).
2. Delete or supersede the other — a genuine `HistoricalBar` mutation/
   deletion, squarely inside P4's own prohibition list, requiring
   separate, explicit operator authorization before any future
   checkpoint attempts it (the same discipline `CHECKPOINT_86`'s own
   Part 2 applied to TCS's broader provenance issue — this is a
   smaller-scoped instance of the same category of decision, not a
   new kind of risk).
3. Only then would the unit's own dry-run reach `DRY_RUN_SAFE` and
   this checkpoint's originally-intended migration become possible.

**No fix was attempted.** This checkpoint's own scope was migration
execution against an assumed-clean state; the state was not clean, the
correct response was to stop and report — not improvise a resolution
unilaterally.

## Governance compliance

- P3/P5: zero real writes attempted after the dry-run's own refusal —
  exactly the "no shortcuts, verify everything directly" discipline
  this session's migration checkpoints have followed throughout.
- P4: zero `HistoricalBar` rows touched by this checkpoint — confirmed
  directly via row-count and `MigrationUnit`-count stability, not
  assumed from the absence of an error.
- P7/P8: no guard weakened or bypassed — the very guard that stopped
  this checkpoint (`ALREADY_CANONICAL_COLLISION`) is pre-existing,
  unmodified, and correctly did its job.
- P9/P10: no strategy logic, registry, or tuning parameter change; no
  tuning resumed (moot — the threshold remains unmet regardless).
- P11: commit to `active-development` only (this commit). No source
  code was modified this checkpoint at all — no data changes, no code
  changes, only this checkpoint's own tracking documents.
- P13: root cause traced via three independent search shapes — exact
  row query (both colliding rows per symbol), adjacent-vocabulary
  scan (RELIANCE's own equivalent slot, confirmed unaffected, to
  bound the issue's scope), and source-level inspection
  (`migration_dry_run.py`'s own collision-classification code,
  confirmed pre-existing and unmodified).
- P15: no speculative directories created.
- P16: single persistent branch, no new branch created.

`CHECKPOINT_87_SUMMARY.md` — this file — committed alongside the
tracking-document updates. `MEMORY.md` and `PROJECT_STRATEGY_STATUS.md`
updated in the same commit (see below).
