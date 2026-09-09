# CHECKPOINT 86 — Recover RELIANCE/TCS/HDFCBANK/INFY 08-17 + Diagnose (Not Fix) TCS Provenance Issue

```
directive: (1) recover 2026-08-17's boundary bars for all 4 symbols,
           checking whether the gap applies beyond RELIANCE; (2)
           diagnose, read-only, TCS's residual UNKNOWN-provenance rows
part 1 result: all 4 symbols recovered to 72/72 COMPLETE, net +8 rows,
           purely additive, 0 duplicates
part 1 gate effect: RELIANCE individually 27 -> 28; common count across
           all 4 symbols UNCHANGED at 24 (bottlenecked by TCS/other
           reasons, not by 08-17 completeness anymore)
part 2 result: TCS's UNKNOWN rows are NOT an isolated TCS anomaly - part
           of a much broader, pre-existing pattern spanning 5,100 rows
           across 23 instruments (mostly non-target symbols); confirmed
           the existing upsert mechanism will NEVER naturally supersede
           them (coverage already reports these days "complete");
           no fix attempted, findings reported for a future checkpoint
full_suite_result: 7 failed / 3391 passed — identical to CHECKPOINT_85,
           zero new/unexplained failures
commit: (recorded below)
```

## Part 0 — Pre-flight

`[F]` Confirmed via `ls`/`git status`: `CHECKPOINT_86_SUMMARY.md` did
not already exist. Git tree was clean (only the deliberately-
uncommitted `SINGLE_ENV_AUTHORIZATION_PROPOSAL.md`) before this
checkpoint's own writes began.

## Part 1 — Recover 2026-08-17's boundary bars, all 4 symbols

`[F]` **Checked directly, not assumed**: queried
`HistoricalDataCoverageService.get_coverage()` for `2026-08-17` across
all 4 symbols before touching anything. **All 4 symbols were
incomplete**, not just RELIANCE:
- RELIANCE: `70/72`, missing one 2-bar range (`03:50`–`03:55`).
- TCS/HDFCBANK/INFY: `70/72` each, missing two separate 1-bar ranges
  (`03:50` and `09:45`) — a day-start AND day-end gap, a variant of
  the pattern, not identical to RELIANCE's own but still purely a
  "currently missing timestamp" problem the same mechanism handles.

`[F]` **Safety proof re-verified** (not merely cited from
`CHECKPOINT_85`) before any write: re-read `historical_data_preparation.py`'s
`prepare()` — still only ever iterates `report.missing_ranges`;
re-read `historical_provider.py`'s `fetch()` — its final line still
strictly filters every returned bar to `start <= bar.timestamp <= end`
(the exact missing-range boundaries passed in); re-read
`historical_bar_repository.py`'s `bulk_upsert()` — still a true
upsert on `(instrument_id, timeframe, bar_timestamp)`, but a
collision remains structurally impossible here because the fetched
bars can only ever fall inside the currently-missing (i.e.
currently-absent) range. Unchanged since `CHECKPOINT_85`; confirmed by
re-reading the code, not by assuming it still holds.

`[F]` **Real recovery executed**, same proven wiring
(`HistoricalDataPreparationService` + real `DhanHistoricalBarProvider`
+ real `DhanCredential`, run under ordinary `.development` settings —
this is a plain data backfill, not a migration-authorization write, so
it needs no special production-identity boot, exactly as
`CHECKPOINT_85` established):

| Symbol | Before | After | Fetched | Persisted | API requests |
|---|---|---|---|---|---|
| RELIANCE | 70/72 | 72/72 | 2 | 2 | 1 |
| TCS | 70/72 | 72/72 | 2 | 2 | 2 |
| HDFCBANK | 70/72 | 72/72 | 2 | 2 | 2 |
| INFY | 70/72 | 72/72 | 2 | 2 | 2 |

**4/4 symbols now `72/72 COMPLETE`. Zero fetch failures.** Net new
rows: **+8** (2 per symbol, matches exactly).

`[F]` **P4 — purely additive, confirmed directly**:
- Table-wide duplicate-key check across the full, now-55,213-row
  table: **0 duplicates**.
- Total table row count: `55,205 → 55,213` (**+8**, exact match).
- RELIANCE's own `2026-08-17` (`CHECKPOINT_83`'s own migrated unit):
  re-queried directly — all originally-`CANONICALIZED` 70 rows remain
  exactly `CANONICALIZED`, spot-checked for unchanged OHLC values; the
  2 newly-fetched rows joined at `CANONICALIZED` too (5m/NSE_EQ/
  CAS-era is `67.0`-proven, so new fetches arrive pre-canonicalized —
  no separate migration step needed for these new rows specifically).
- TCS/HDFCBANK/INFY's pre-existing 70 `REAL_DHAN` rows for `08-17`
  remain exactly `UNCANONICALIZED`, untouched — this checkpoint made
  no migration write, only a data-completeness fetch; their 2 new rows
  arrived `CANONICALIZED` (same 67.0-proof reason) but the day as a
  whole is not yet migration-canonicalized for these 3 symbols.
- Broader spot-check (10 rows, sampled outside `2026-08-17` entirely,
  across all 4 target symbols and other instruments): all sane,
  unchanged values and states.

`[F]` **A finding worth stating plainly, not glossed over**: TCS/
HDFCBANK/INFY's `2026-08-17` rows were never targeted by any migration
checkpoint (`CHECKPOINT_83` targeted RELIANCE alone; `CHECKPOINT_84`
targeted the OTHER 9 interior-gap days, deliberately excluding
`08-17`). So even fully row-complete, these 3 symbols' `08-17` remains
`UNCANONICALIZED` and cannot pass the research gate on completeness
recovery alone — confirmed directly below.

## Research gate re-run (Part 1's own verification step)

`[F]` Re-ran `get_research_eligible_bars()` for `2026-08-17`
specifically, all 4 symbols:
- RELIANCE: **ACCEPTED** (now genuinely complete AND canonicalized).
- TCS/HDFCBANK/INFY: **REJECTED, `UNCANONICALIZED_TIMESTAMP`** — the
  rejection reason SHIFTED from `INCOMPLETE_COVERAGE` (before this
  checkpoint) to `UNCANONICALIZED_TIMESTAMP` (after) — proving the
  boundary-bar fix genuinely worked and the NEXT gate is now the
  binding constraint, exactly as predicted before running the fetch.

`[F]` Full-range re-scan (`2026-08-03`–`09-09`, all 4 symbols):
RELIANCE's own individual verified-day count rose **27 → 28**.
**Common gate-verified count across all 4 symbols remains 24** —
unchanged from `CHECKPOINT_85`, since TCS was already the binding
constraint at 24 (via its own separate `INELIGIBLE_PROVENANCE`
rejections on `08-18`/`08-19`/`08-24`, investigated in Part 2 below;
`08-17`'s rejection reason changing does not raise TCS's own count).
**Recovering TCS/HDFCBANK/INFY's `08-17` migration status (an actual
migration-execution unit, not just a boundary-bar fetch) would be
needed to move the common count further on this specific day — out of
this checkpoint's own authorized scope** (no migration-authorization
write was authorized here, only the boundary-bar recovery).

## Part 2 — Diagnose (read-only) TCS's `UNKNOWN`-provenance rows

**No code changed, no data changed, no fix attempted, per this
checkpoint's own explicit rule.**

`[F]` **Exact rows and metadata, TCS/`08-18`/`08-19`/`08-24`**:

| Day | UNKNOWN rows | ingested_at | source | canon state | semantics | Timestamps |
|---|---|---|---|---|---|---|
| 08-18 | 8 | `2026-08-20 11:36:23` (all 8, identical) | `API_FETCH` | `NOT_APPLICABLE` | `UNKNOWN` | `03:50`–`04:25` |
| 08-19 | 8 | `2026-08-20 11:34:49` (all 8, identical) | `API_FETCH` | `NOT_APPLICABLE` | `UNKNOWN` | `03:50`–`04:25` |
| 08-24 | 71 | `2026-08-24 14:55:24`/`:25` (2 sub-batches) | `API_FETCH` | `NOT_APPLICABLE` | `UNKNOWN` | `03:50`–`09:40` |

`[F]` **Origin, inferred from direct source-code inspection, not
guessed**: the codebase has exactly ONE call site that ever writes
`HistoricalBar` rows via the standard live-ingestion path
(`historical_data_preparation.py:252`,
`self.writer.bulk_upsert(...)`), and it always passes
`provenance=provider_provenance`, where `provider_provenance =
getattr(self.provider, "provenance", PROVENANCE_UNKNOWN)`. The two
CURRENT provider implementations both stamp a fixed, non-`UNKNOWN`
provenance unconditionally (`DhanHistoricalBarProvider.provenance =
PROVENANCE_REAL_DHAN`, `init=False`; `SyntheticHistoricalBarProvider.provenance
= PROVENANCE_SYNTHETIC_TEST`, `init=False`) — so `UNKNOWN` can only
result if the provider object active at ingestion time exposed NO
`.provenance` attribute at all (the `getattr(...)` fallback), and
likewise no `.canonicalization_state_for()`/`.source_timestamp_semantics_for()`
hooks (both also fell back to their own `UNKNOWN` defaults for these
rows). All rows show `source=API_FETCH` — a real fetch attempt, not a
manual/scripted insert — but through a provider that predates (or
otherwise never implemented) the provenance/canonicalization hook
system this codebase's current two providers both carry. **`[I]`
High-confidence inference**: these rows are remnants of an early or
experimental ingestion path from before the provenance-tracking
system existed, left in place rather than being retroactively
corrected.

`[F]` **This pattern is NOT isolated to TCS — a much broader,
pre-existing characteristic of the dataset**, found by scanning the
whole table: **5,100 rows total carry `provenance=UNKNOWN`**, spanning
**23 distinct instruments**, almost entirely NON-target symbols
(`ADANIPORTS`/`ADANIENT`/`ADANIENSOL`/`ADANIPOWER`/`ADANIGREEN`/`ATGL`
at 533 each; `SAMPANN` 525; `IFCI` 150; several TATA-group symbols and
`JIOFIN` at 75–90 each). **TCS is the only one of the 4 primary
trading symbols affected (87 rows total, exactly matching the 3 days'
counts: 8+8+71); RELIANCE/HDFCBANK/INFY have ZERO `UNKNOWN`-provenance
rows anywhere.** `ingested_at` spans `2026-08-18 10:24:45` through
`2026-08-24 14:55:27` (194 distinct timestamps — many small, separate
ingestion events, not one bulk operation). This materially changes
how concerning the finding is: it is a known, broad, systemic
characteristic of this project's earlier bulk-seeded dataset — not a
new defect, and not specific to TCS's own 3 flagged days.

`[F]` **Confirmed directly: the existing upsert mechanism will NEVER
naturally supersede these rows.** Queried
`HistoricalDataCoverageService.get_coverage()` for TCS/`08-18`
directly: `expected=72, cached=72, complete=True, missing_ranges=()`.
Coverage counting is provenance-blind — it only checks presence at
each expected timestamp — so the 8 `UNKNOWN` rows already satisfy the
coverage check and `prepare()` would make **zero** provider calls for
this range, ever, regardless of how many times it's re-run. **A fresh
fetch does NOT naturally correct this — it must be deliberately
forced.**

`[F]` **Proposed approaches (NOT implemented), for a future
checkpoint's own explicit decision**:
1. **Force-overwrite via a modified fetch call** (bypass the
   missing-range-only logic, explicitly re-request the already-
   "cached" range and let `bulk_upsert()`'s `update_conflicts=True`
   overwrite the existing `UNKNOWN` rows with fresh `REAL_DHAN` data).
   This is a genuine mutation of existing rows — squarely inside P4's
   prohibition ("no `HistoricalBar` mutation, relabel, backfill, or
   deletion") and would need explicit, separate operator authorization
   before any future checkpoint attempts it. It is also the most
   thorough fix: if the underlying OHLCV values in these `UNKNOWN`
   rows are themselves stale or wrong (not yet checked — this
   diagnosis did not compare them against a fresh, read-only Dhan
   response), only a real re-fetch would correct the prices
   themselves, not just the metadata.
2. **Metadata-only correction** (leave OHLCV values as-is, only
   relabel `provenance`/`canonicalization_state`/`source_timestamp_semantics`
   for these 87 TCS rows) — lower blast-radius than option 1 (no price
   data touched), but still a mutation forbidden by P4 without
   explicit authorization, and carries its own risk: it would be
   *asserting* these values are trustworthy `REAL_DHAN` data without
   having actually re-verified them against Dhan, which could
   silently promote bad data to research-eligible status — the exact
   failure mode P4's "never silently overwrite" spirit exists to
   prevent, per this checkpoint's own directive.
3. **Delete + fresh fetch** (delete the 87 rows, then let `prepare()`'s
   normal missing-range logic re-fetch them cleanly, going through the
   real `DhanHistoricalBarProvider` and stamping correct provenance
   naturally) — the cleanest RESULT, but requires a DELETE, explicitly
   named in P4's own prohibition list, and is irreversible without a
   backup — would need the same canary-backup discipline the migration
   path already uses before any such operation is authorized.

**No recommendation is made here beyond laying out the honest
trade-offs** — per this checkpoint's own instruction, this becomes a
future checkpoint's own explicit decision, not this one's. If a future
checkpoint pursues this, option 1 or 3 (both involve a genuine real
re-fetch and verification against Dhan, not just relabeling
unverified data) are more defensible than option 2 on data-integrity
grounds, though both cost more (real API calls, an explicit
mutation/deletion authorization, and — for option 3 — a canary backup
of the 87 rows before deletion).

## New baseline, stated plainly

- **Common gate-verified day count across all 4 symbols: 24** —
  unchanged from `CHECKPOINT_85` (Part 1's `08-17` recovery raised
  RELIANCE's own individual count `27 → 28` but did not move the
  common count, since TCS remains the binding constraint at 24 for a
  separate, unrelated reason).
- **47-day Gainz/VWAP/ORB tuning-resumption criterion: still NOT MET**
  (24 of 47). No strategy tuning was resumed.
- **What would move the common count further**: (a) a migration-
  execution unit for TCS/HDFCBANK/INFY's `2026-08-17` (now row-complete,
  needs canonicalization — a separate, not-yet-authorized migration
  write, using the already-proven `CHECKPOINT_83` mechanism on a new
  unit); (b) resolving TCS's residual `UNKNOWN`-provenance rows on 3
  days via one of the 3 proposed approaches above — explicitly a
  future checkpoint's own decision, not attempted here.

## Governance compliance

- P3/P6 (Part 1): real Dhan network calls and real DB writes,
  authorized for this checkpoint's own recovery purpose, purely
  additive, confirmed directly.
- P4: Part 1 confirmed purely additive (0 duplicates, all previously-
  touched rows re-verified unchanged). Part 2 made ZERO data changes —
  investigation only, exactly as this checkpoint's own rule required;
  no fix attempted despite identifying what would look like a
  "simple" one.
- P7/P8: no migration-authorization-mechanism change; no fingerprint/
  checksum semantics changed — Part 1 used the ordinary data-fetch
  path, not the migration path, at all.
- P9/P10: no strategy logic, registry, or tuning parameter change; no
  tuning resumed despite the (still unmet) threshold check performed.
- P11: commit to `active-development` only (this commit). No source
  code was modified this checkpoint — only data (Part 1, via the
  sanctioned, proven backfill path) and this checkpoint's own tracking
  documents.
- P13: Part 2's diagnosis used three search shapes before concluding
  the pattern's scope — exact-row query (TCS's own 87 rows), adjacent-
  vocabulary scan (whole-table `provenance=UNKNOWN` scan surfacing 23
  instruments), and source-level call-site search (`bulk_upsert(`
  grepped across the whole codebase to find the single real call
  site) — not a single query taken as conclusive.
- P15: no speculative directories created.
- P16: single persistent branch, no new branch created.

`CHECKPOINT_86_SUMMARY.md` — this file — committed alongside the
tracking-document updates. `MEMORY.md` and `PROJECT_STRATEGY_STATUS.md`
updated in the same commit (see below).
