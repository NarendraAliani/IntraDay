# CHECKPOINT 85 — Diagnose + Recover Interior-Gap Boundary Bars

```
directive: diagnose CHECKPOINT_84's INCOMPLETE_COVERAGE finding across
           all 9 interior-gap days, then recover via real re-fetch if
           confirmed safe
hypothesis: interior-gap days were fetched before CHECKPOINT_69's
           fromDate-exclusive fix landed, carrying the same day-start
           truncation CHECKPOINT_69 already fixed for other days
diagnosis result: CONFIRMED for the dominant pattern (34/36 slots);
           one distinct, unrelated issue found and reported separately
           (TCS/2026-08-24)
recovery result: 36/36 slots now 72/72 COMPLETE — net +71 rows, purely
           additive, 0 duplicate keys, 0 existing rows mutated
gate-verified day count: 18 -> 24 common across all 4 symbols
           (RELIANCE/HDFCBANK/INFY individually at 27; TCS capped at
           24 by a separate, pre-existing, out-of-scope provenance issue)
47-day tuning threshold: still NOT met (24 of 47)
full_suite_result: 7 failed / 3391 passed — identical to CHECKPOINT_84,
           zero new/unexplained failures
commit: (recorded below)
```

## Part 0 — Pre-flight

`[F]` Confirmed via `ls`/`git status`: `CHECKPOINT_85_SUMMARY.md` did
not already exist. Git tree was clean (only the deliberately-
uncommitted `SINGLE_ENV_AUTHORIZATION_PROPOSAL.md`) before this
checkpoint's own writes began.

## Part 1 — Diagnose before acting

`[F]` **Ingestion-timing evidence, checked directly, not assumed**:
`CHECKPOINT_69`'s own fix landed at commit `eb8fa9d`
(`2026-09-07 20:13:30 +0530`). Sampled interior-gap rows'
`ingested_at` values: RELIANCE/`08-18` → `2026-08-31 11:12:04`;
RELIANCE/`08-21` → `2026-08-31 11:12:05`; RELIANCE/`08-26` →
`2026-08-30 10:09:36` — **all well before** `CHECKPOINT_69`'s fix
landed. Compared against a KNOWN post-fix day, RELIANCE/`2026-08-04`
(recovered by `CHECKPOINT_69` itself): `ingested_at` values cluster
around `2026-09-03`/`09-07`, and that day is fully `72/72 complete`.
This is direct, positive evidence for the hypothesis.

`[F]` **Exact missing-bar identification, via `HistoricalDataCoverageService.get_coverage()`
directly** (not inferred from row counts alone), scanned across all
36 candidate slots:
- **34 of 36 slots** show `expected=72, cached=70`, missing exactly a
  2-bar range at the very start of the session (`03:50`–`03:55` UTC in
  most cases; `04:30`–`04:35` for TCS/`08-18`/`08-19`, shifted because
  those two days already carry 8 pre-existing `UNKNOWN`-provenance
  filler rows occupying the true day-start slots). This is **exactly**
  the day-start truncation pattern `CHECKPOINT_69`'s own docstring
  describes: a single-bar widening (the pre-`CHECKPOINT_69` behavior)
  recovers only ONE of the two day-start candles Dhan's exclusive
  `fromDate` semantics discard; the fix's own 2-bar widening is
  required to recover both. RELIANCE/`2026-08-17` (`CHECKPOINT_83`'s
  own unit, outside this checkpoint's 9-day target range) shows the
  identical pattern — confirming this is not new to the days this
  checkpoint targets.
- **2 slots** (RELIANCE `08-25`/`08-26`) additionally carry ONE extra
  isolated single-bar gap at `04:35`, on top of the same day-start
  pattern — flagged honestly as a second, smaller symptom, not
  explained by the day-start hypothesis alone, but structurally
  identical to fix (still just a "currently missing timestamp" a
  fresh, scoped re-fetch can recover, if Dhan's own historical API
  actually holds that candle).
- **1 slot is genuinely different and does NOT fit the hypothesis**:
  TCS/`2026-08-24`. `expected=72, cached=71`, missing only the
  session-**end** bar (`09:45`), not session-start. `ingested_at` is
  `2026-08-24 14:55:24` — the SAME calendar day as the trading date
  itself (a same-day/live-style ingestion, not part of the same batch
  backfill as the other 35 days). All 71 of its existing rows carry
  `provenance=UNKNOWN`, not `REAL_DHAN` — a distinct data-quality
  characteristic (already noted by `CHECKPOINT_84` as the reason this
  unit was ineligible for migration). **Reported honestly: this one
  slot's cause is NOT the `CHECKPOINT_69` day-start truncation
  hypothesis** — a different pipeline, a different missing boundary,
  a different provenance profile.

`[F]` **Safety proof that a re-fetch is purely additive**, established
by direct source inspection before any write:
- `HistoricalDataPreparationService.prepare()` iterates ONLY over
  `report.missing_ranges` — it never re-requests an already-cached
  range (`historical_data_preparation.py:142`).
- `DhanHistoricalBarProvider.fetch()`'s own final line strictly
  filters every returned bar to `start <= bar.timestamp <= end`
  (`historical_provider.py:585`) — `start`/`end` here are exactly
  `missing_range.start`/`.end`, the narrow gap being filled. A
  response can therefore never contain a bar outside the requested
  missing range.
- `DjangoHistoricalBarRepository.bulk_upsert()` DOES use a true
  upsert (`bulk_create(..., update_conflicts=True, unique_fields=
  ["instrument_id", "timeframe", "bar_timestamp"], ...)`,
  `historical_bar_repository.py:158`) — meaning a KEY COLLISION could,
  in principle, overwrite an existing row. **But** since every bar
  `fetch()` can possibly return is confined to the currently-missing
  timestamps (by the point above), and a "missing" timestamp by
  definition has NO existing row at that key, **no collision is
  structurally possible for this recovery** — every write from this
  checkpoint's own recovery action is a genuine INSERT, never an
  UPDATE of a pre-existing row (including the 35 rows-worth of units
  `CHECKPOINT_83`/`84` just canonicalized).

**Conclusion: hypothesis CONFIRMED for 34 of 36 slots (with 2 of those
34 carrying one extra unexplained-but-safely-fixable single-bar gap);
REFUTED for TCS/2026-08-24, whose distinct cause is reported above,
not assumed away.** Proceeded to Part 2 for all 36 slots — the refuted
case was still safe to attempt (same purely-additive guarantee applies
regardless of root cause), with its outcome reported honestly rather
than silently folded into the confirmed-hypothesis narrative.

## Part 2 — Recovery

`[F]` **A real blocker, encountered and resolved before any fetch
could run**: the stored `DhanCredential`'s encrypted access token
could not be decrypted under a fresh, session-only
`SETTINGS_ENCRYPTION_KEY` (the same kind of key `CHECKPOINT_82`/`83`/
`84` generated for their own `.production` boot). Investigated
directly: `encryption.py`'s own documented key precedence shows a
DEVELOPMENT-ONLY fallback (a key deterministically derived from
`DJANGO_SECRET_KEY` via SHA-256) is used whenever `SETTINGS_ENCRYPTION_KEY`
is unset — which is how the credential was originally encrypted, under
ordinary `.development`/`.paper` settings (the same settings
`CHECKPOINT_72`'s own `backfill_daily_coverage` command normally runs
under), not the special production-identity boot procedure. **This
recovery is a plain data backfill, not a migration-authorization
write** — it does not need `VERIFIED_PRODUCTION` identity at all (that
mechanism is `CHECKPOINT_83`'s own, separate, unchanged concern) — so
this checkpoint ran under ordinary `intraday.settings.development`
instead, confirmed to write to the exact same single real database
(`RECON-SINGLE-ENV-AUTHORIZATION`'s own finding: one database
everywhere). Credentials resolved correctly once switched.

`[F]` **Real recovery executed** via the same proven
`HistoricalDataPreparationService.prepare()` path every prior backfill
checkpoint (`CHECKPOINT_69`/`72`/`74`/`81`) has used — the exact same
wiring `backfill_daily_coverage.py` uses (`DhanHistoricalBarProvider`
+ `DhanSettingsService` real credentials), called directly per
`(symbol, day)` slot for the canonical `[03:45, 10:00)` window. All 36
slots (9 days × 4 symbols) attempted:

| Result | Count |
|---|---|
| `COMPLETE`, `before=70/72 → after=72/72`, 2 bars recovered | 33 |
| `COMPLETE`, `before=71/72 → after=72/72`, 1 bar recovered (TCS/`08-24`) | 1 |
| `COMPLETE`, `before=70/72 → after=72/72`, 2 bars recovered across 2 sub-ranges (RELIANCE `08-25`/`08-26`) | 2 |

**36/36 slots now `72/72 COMPLETE`. Zero fetch failures, zero API
errors, zero partial/`NOT_AVAILABLE` outcomes.** Net new rows:
**+71** (35 slots × 2 bars + 1 slot × 1 bar = 71, matches exactly).

`[F]` **P4 — purely additive, confirmed directly**:
- Table-wide duplicate-key check (`(instrument_id, timeframe,
  bar_timestamp)`, `count > 1`) across the full, now-55,205-row table:
  **0 duplicates**.
- Total table row count: `55,134 → 55,205` (**+71**, exactly matching
  `bars_persisted` summed across all 36 outcomes — no unaccounted
  rows).
- Every one of the 35 units `CHECKPOINT_83`/`84` canonicalized was
  re-queried directly: **zero** now show a non-`CANONICALIZED`
  `REAL_DHAN` row — all remain exactly as those checkpoints left them.
- `CHECKPOINT_83`'s own unit (RELIANCE, `2026-08-17` — outside this
  checkpoint's 9-day target range, deliberately never touched) is
  still exactly `70/70 CANONICALIZED`.
- Broader spot-check (15 rows, sampled outside `2026-08-18`–`08-28`
  entirely, across all 4 symbols and other instruments): all sane,
  unchanged values and states — no corruption.
- The 71 newly-inserted rows themselves arrived already
  `canonicalization_state=CANONICALIZED` at fetch time (the 5m/
  NSE_EQ/CAS-era scope is `67.0`-proven, so the provider marks them
  canonicalized directly — no separate migration step was needed for
  these new rows).

`[F]` **Every previously-incomplete day now shows the full expected
72-bar count** — confirmed above, all 36 slots. TCS/`2026-08-24`
reached `72/72` too, though (see Part 3) its residual provenance
issue means row-completeness alone does not make it research-eligible.

## Part 3 — Research gate re-run

`[F]` Re-ran `get_research_eligible_bars()` for all 4 symbols across
the full `2026-08-03`–`09-09` range:

| Symbol | Verified days | Rejections |
|---|---|---|
| RELIANCE | 27 | `2026-08-17` (`INCOMPLETE_COVERAGE`, outside this checkpoint's scope) |
| TCS | 24 | `2026-08-17` (same); `08-18`/`08-19`/`08-24` (`INELIGIBLE_PROVENANCE`) |
| HDFCBANK | 27 | `2026-08-17` |
| INFY | 27 | `2026-08-17` |

**Common across all 4 symbols: 24 days** (up from 18 before this
checkpoint — a genuine, substantial gain of 6 days). Full list:
`08-03`–`08-07`, `08-10`–`08-14`, `08-20`, `08-21`, `08-25`–`08-28`,
`08-31`–`09-04`, `09-07`–`09-09`.

`[F]` **RELIANCE/`2026-08-17` remains rejected** — `CHECKPOINT_83`'s
own single unit was never in this checkpoint's own 9-day target range
(`08-18`–`08-28`), so its own boundary bars were never re-fetched
here. It shows the identical missing-2-bar pattern diagnosed in Part 1
and could very likely be recovered the same way in a future
checkpoint — noted, not fixed here (out of this checkpoint's own
declared scope).

`[F]` **TCS's residual `INELIGIBLE_PROVENANCE` rejections, investigated
directly, reported honestly, NOT fixed**: TCS/`08-18` and `08-19` each
still carry 8 pre-existing `provenance=UNKNOWN` rows (64 `REAL_DHAN` +
8 `UNKNOWN` = 72 total); TCS/`08-24` carries 71 `UNKNOWN` + only the 1
newly-recovered `REAL_DHAN` row. The research gate's provenance check
rejects a day if ANY row in its range carries ineligible provenance —
so these 3 days remain non-research-eligible despite now being
row-count-complete. **This is a different, pre-existing problem from
the one this checkpoint targeted** (boundary-bar truncation) — those
`UNKNOWN` rows already existed before this checkpoint began, and
fixing them would require overwriting already-stored rows (a riskier,
different operation than this checkpoint's purely-additive missing-
range fetch, and outside its authorized scope: P3/P4 forbid mutating
existing rows without separate, explicit authorization). Flagged here
as the honest next blocker for TCS specifically, not investigated
further or attempted.

## New baseline, stated plainly

- **Gate-verified day count, common across all 4 symbols: 24** — up
  from 18 before this checkpoint (+6, a genuine gain from the boundary-
  bar recovery). Per-symbol: RELIANCE/HDFCBANK/INFY at **27** each;
  TCS at **24**, capped by its own separate, pre-existing provenance
  issue.
- **47-day Gainz/VWAP/ORB tuning-resumption criterion
  (`CHECKPOINT_75`/`76`/`79`): still NOT MET.** 24 is closer to 47 than
  the prior 18, but still 23 days short. Stated plainly: this
  checkpoint made real, substantial progress (+6 days) but does not
  reach the threshold.
- **No strategy tuning was resumed** — per this checkpoint's own rule.
- **What would move the count further**: (a) recovering RELIANCE/
  `2026-08-17` the same way (1 day, likely trivial, same mechanism,
  just outside this checkpoint's declared 9-day scope); (b) resolving
  TCS's residual `UNKNOWN`-provenance rows on 3 specific days — a
  separate, not-yet-authorized, higher-risk data-correction question
  (requires touching already-existing rows, not a pure addition); (c)
  the remaining days in the full range that were never part of the
  interior gap at all remain gated by whatever their own individual
  coverage/provenance status is — not audited exhaustively by this
  checkpoint beyond the 24-day common count reported above.

## Governance compliance

- P3/P6: real Dhan network calls and real DB writes, authorized for
  this checkpoint's own recovery purpose, contingent on Part 1's
  diagnosis, exactly as the checkpoint's own rules required.
- P4: purely additive — zero existing rows (including the 35 `CHECKPOINT_83`/
  `84`-canonicalized ones) mutated, relabeled, or deleted; confirmed
  directly via duplicate-key check, row-count delta, and targeted
  re-query of every previously-touched unit. The TCS provenance issue
  was found but deliberately NOT touched, since fixing it would risk
  exactly the kind of existing-row mutation P4 forbids without
  separate authorization.
- P7/P8: no migration-authorization-mechanism change (`CHECKPOINT_83`'s
  own settled work, untouched); no fingerprint/checksum semantics
  changed — this checkpoint used the ordinary data-fetch path, not the
  migration path, at all.
- P9/P10: no strategy logic, registry, or tuning parameter change; no
  tuning resumed despite the (still unmet) threshold check performed.
- P11: commit to `active-development` only (this commit). No source
  code was modified this checkpoint — only data (via the sanctioned,
  proven backfill path) and this checkpoint's own tracking documents.
- P15: no speculative directories created.
- P16: single persistent branch, no new branch created.

`CHECKPOINT_85_SUMMARY.md` — this file — committed alongside the
tracking-document updates. `MEMORY.md` and `PROJECT_STRATEGY_STATUS.md`
updated in the same commit (see below).
