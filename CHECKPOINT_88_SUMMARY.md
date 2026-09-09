# CHECKPOINT 88 — Resolve the 3-Row Duplicate (delete old, keep new canonical)

```
directive: operator-authorized deletion of exactly 3 old
           (UNCANONICALIZED) rows (TCS 7046, HDFCBANK 7660, INFY 8360)
           superseded by an independently-fetched, already-
           CANONICALIZED row for the same real candle
backup: docs/baselines/checkpoint_88_pre_delete_backup.json (full
           field values of all 3 rows, captured inside this project's
           own proven repeatable-read snapshot mechanism, before any
           deletion)
result: exactly 3 rows deleted, by primary key, confirmed directly -
           table row count decreased by exactly 3 (55,213 -> 55,210),
           0 duplicate keys, 0 other rows affected
dry-run result: all 3 units now reach DRY_RUN_SAFE - the collision is
           gone
important correction to the checkpoint's own suggested reasoning:
           re-migration is STILL NEEDED for these 3 days - the
           surviving 09:45 row resolves only ONE bar; 69 rows per
           symbol remain UNCANONICALIZED - checked directly, not
           assumed
gate-verified day count: 24 — UNCHANGED (this checkpoint did not
           canonicalize any new data, only removed a blocker)
47-day threshold: still NOT met (24 of 47)
full_suite_result: 7 failed / 3391 passed — identical to CHECKPOINT_87,
           zero new/unexplained failures
commit: (recorded below)
```

## Part 0 — Re-verify before touching anything

`[F]` Confirmed via `ls`/`git status`: `CHECKPOINT_88_SUMMARY.md` did
not already exist. Git tree was clean apart from the deliberately-
uncommitted `SINGLE_ENV_AUTHORIZATION_PROPOSAL.md` before this
checkpoint's own writes began.

`[F]` Re-queried all 6 rows (3 pairs) directly by primary key —
**everything matched `CHECKPOINT_87`'s own description exactly, no
change since**:

| Symbol | Old (`09:40`) | New (`09:45`) |
|---|---|---|
| TCS | `7046`, `UNCANONICALIZED`, `REAL_DHAN` | `55209`, `CANONICALIZED`, `REAL_DHAN` |
| HDFCBANK | `7660`, `UNCANONICALIZED`, `REAL_DHAN` | `55211`, `CANONICALIZED`, `REAL_DHAN` |
| INFY | `8360`, `UNCANONICALIZED`, `REAL_DHAN` | `55213`, `CANONICALIZED`, `REAL_DHAN` |

`[F]` Confirmed the 3 NEW (`09:45`) rows are structurally complete —
iterated every model field on each row, **zero null fields**
(`exchange`, `symbol`, `ingested_at` all present, plus every OHLCV/
provenance/state field already known from `CHECKPOINT_87`). This is
the row that remains as the sole record for each candle — confirmed
fit for that role before deleting anything.

Nothing had changed since `CHECKPOINT_87`. Proceeded to Part 1.

## Part 1 — Backup before deleting

`[F]` Captured a real, auditable snapshot of the exact 3 rows'
full field values BEFORE any deletion, reusing this project's own
proven `_repeatable_read_atomic()` helper
(`migration_canary_backup.py`) so the read is a true point-in-time
snapshot, not assembled from separate queries. `build_canary_backup()`
itself was not reused directly — it is built for one full migration
unit's own row set (all rows of one `(instrument, timeframe, date)`),
not 3 individually-selected rows spanning 3 different units/symbols;
reusing its underlying snapshot primitive while writing a
purpose-built, self-contained export was the honest fit, not forcing
an ill-matched abstraction.

Written to `docs/baselines/checkpoint_88_pre_delete_backup.json`
(committed alongside this summary) — full field values (id, instrument,
timeframe, bar_timestamp, OHLCV, provenance, canonicalization_state,
source, source_timestamp_semantics, exchange, symbol, ingested_at) for
all 3 rows, plus the checkpoint name, purpose, and generation
timestamp. `[F]` Confirmed exactly 3 rows were captured
(`row_count: 3`), matching the target ids `[7046, 7660, 8360]`.

## Part 2 — Delete the 3 old rows only

`[F]` Deleted via `HistoricalBar.objects.filter(id__in=[7046, 7660,
8360]).delete()` — a primary-key filter, never a broader
symbol/date/state filter that could accidentally match more rows.
Pre-delete existence check confirmed exactly these 3 ids existed
before issuing the delete (defense in depth — would have refused
without deleting anything if the set had drifted).

`[F]` **Result: `deleted_count=3`**, `{'persistence.HistoricalBar':
3}` — exactly 3 rows, no more, no less. `before_total=55213`,
`after_total=55210`, delta exactly `3`. Re-queried all 3 target ids
immediately after: **0 remaining**.

## Part 3 — Verify thoroughly

`[F]` **The 3 target rows are gone**: direct `.exists()` check on
`7046`/`7660`/`8360` — all `False`.

`[F]` **The 3 new (`09:45`) rows are completely untouched**:
re-queried `55209`/`55211`/`55213` directly — every field (state,
provenance, OHLCV, volume) byte-identical to Part 0's own
re-verification, before the delete ran.

`[F]` **No other row anywhere in the table was affected**:
- Table-wide duplicate-key check
  (`(instrument_id, timeframe, bar_timestamp)`, `count > 1`) across
  the full, now-55,210-row table: **0 duplicates**.
- Total table row count: `55,213 → 55,210` — exactly `-3`, matching
  the delete result precisely.
- TCS/HDFCBANK/INFY's own `2026-08-17` row counts: `72 → 71` each,
  exactly matching the 1-row-per-symbol deletion.
- RELIANCE's own `2026-08-17` (`CHECKPOINT_83`'s migrated unit),
  untouched by this checkpoint at all: still `72/72 CANONICALIZED`.
- Broader spot-check (10 rows, sampled outside `2026-08-17` entirely,
  across all 4 target symbols and other instruments): all sane,
  unchanged.

`[F]` **Re-ran the migration dry-run for all 3 units — the collision
is gone**:

```
TCS      2026-08-17  DRY_RUN_SAFE  69  PROVEN  ()
HDFCBANK 2026-08-17  DRY_RUN_SAFE  69  PROVEN  ()
INFY     2026-08-17  DRY_RUN_SAFE  69  PROVEN  ()
```

All 3 units now reach `DRY_RUN_SAFE` — confirmed directly, `Checkpoint
87`'s blocking `ALREADY_CANONICAL_COLLISION` is resolved. **Per this
checkpoint's own rule, the migration itself was NOT run** (dry-run
only).

## An important correction to this checkpoint's own suggested reasoning

`[F]` **The directive's own tentative assumption — "these 3 units are
already effectively in their final canonical state via the surviving
`09:45` row; re-migrating is likely unnecessary" — was checked
directly and found INCORRECT, not assumed to be true.**

Queried each symbol's own `2026-08-17` canonicalization-state
breakdown directly:

| Symbol | Total rows | `UNCANONICALIZED` | `CANONICALIZED` |
|---|---|---|---|
| TCS | 71 | **69** | 2 |
| HDFCBANK | 71 | **69** | 2 |
| INFY | 71 | **69** | 2 |

**69 rows per symbol remain `UNCANONICALIZED`** — the surviving
`09:45` row resolves exactly ONE bar's worth of canonicalization (the
day's own final candle); it says nothing about the other 71 bars.
Re-ran the research gate for these 3 symbols' `2026-08-17` directly:
**still `REJECTED`** — the rejection reason shifted from
`INCOMPLETE_COVERAGE` (`CHECKPOINT_87`'s own last-observed state,
before this checkpoint even started) to a NEW, expected
`INCOMPLETE_COVERAGE` variant: `71/72 bars (98.61%) cached`, missing
exactly the `09:40` coordinate. This is a known, temporary, correctly-
predicted consequence of the deletion, not a new defect: the
coverage service's own expected schedule treats `09:40` as a distinct
CLOSE-timestamp slot (representing the `09:35`–`09:40` candle) — the
now-deleted row happened to sit at that same numeric coordinate
PRE-migration (as the raw/OPEN label for the DIFFERENT `09:40`–`09:45`
candle), so removing it makes that slot register as genuinely missing
until the still-pending migration's own cascading `+5min` shift (of
the row currently at `09:35`, and so on down the chain) fills it in
naturally. **This is expected and requires no further action from
this checkpoint** — it will resolve itself the moment a future
checkpoint runs the actual migration for these 3 units.

**Further action IS needed, and is reported here plainly rather than
assumed away**: these 3 days will remain non-research-eligible until
a future checkpoint runs `migration_production_execute` for these 3
now-`DRY_RUN_SAFE` units — exactly the migration this checkpoint's own
rules said NOT to run here. That migration execution is a separate,
future checkpoint's own decision (the mechanism is already proven,
per `CHECKPOINT_83`/`84`; only the explicit "run it now" authorization
is missing).

## Verification — research gate and full suite

`[F]` **Full-range research gate re-run**: common gate-verified day
count across all 4 symbols: **24 — UNCHANGED**. Per-symbol: RELIANCE
`28`, HDFCBANK/INFY `27` each, TCS `24` — identical to
`CHECKPOINT_87`'s own final state. Exactly as expected: this
checkpoint canonicalized zero new data, it only removed a migration
blocker.

`[F]` **Full test suite**: `.venv/Scripts/python.exe -m pytest -q
--reuse-db` — **3391 passed, 7 failed** (703.77s). Exact failure
names, identical to `CHECKPOINT_87`'s own list (same 5 pre-existing +
2 known `--reuse-db` flakes). **Zero new/unexplained failures.**

## New baseline, stated plainly

- **Common gate-verified day count across all 4 symbols: 24** —
  unchanged. **47-day Gainz/VWAP/ORB tuning-resumption criterion:
  still NOT MET** (24 of 47). No strategy tuning was resumed.
- **The 3-row duplicate `CHECKPOINT_87` found is now fully resolved**:
  exactly 3 old rows deleted (backed up first), 3 new rows intact and
  unchanged, all 3 units now `DRY_RUN_SAFE`.
- **Next step, explicitly not taken here**: a future checkpoint would
  need to explicitly authorize and run `migration_production_execute`
  for TCS/HDFCBANK/INFY's `2026-08-17` (3 units, already proven
  `DRY_RUN_SAFE`, 69 rows each, comfortably under the 200-row ceiling)
  to make these days research-eligible — the mechanism is proven, only
  the explicit "run it" decision remains.
- **`CHECKPOINT_86`'s own broader TCS `UNKNOWN`-provenance finding
  remains completely untouched and unauthorized** — this checkpoint
  deliberately did not go anywhere near it, exactly as its own rules
  required.

## Governance compliance

- P3/P4: this checkpoint's own explicit, narrow authorization covered
  exactly 3 named rows, deleted by primary key only, backed up first —
  the most rigorous treatment this session has given any destructive
  operation, matching the checkpoint's own explicit instruction to
  treat it "with the same rigor as every migration-authorization
  checkpoint this session."
- P7/P8: no guard weakened — the collision guard that blocked
  `CHECKPOINT_87` is untouched; this checkpoint changed the DATA that
  triggered it, not the guard itself. No fingerprint/checksum
  semantics changed.
- P9/P10: no strategy logic, registry, or tuning parameter change; no
  tuning resumed (moot — the threshold remains unmet regardless); no
  migration was executed (only dry-run, per this checkpoint's own
  rule).
- P11: commit to `active-development` only (this commit).
- P13: Part 0's re-verification and Part 3's "further action needed?"
  question were both checked via direct, fresh queries — never
  assumed from a prior checkpoint's own description or the current
  checkpoint's own suggested reasoning.
- P15: no speculative directories created — `docs/baselines/` already
  existed; a file was added to it, not a new directory.
- P16: single persistent branch, no new branch created.

`CHECKPOINT_88_SUMMARY.md` — this file — committed alongside the
backup JSON and tracking-document updates. `MEMORY.md` and
`PROJECT_STRATEGY_STATUS.md` updated in the same commit (see below).
