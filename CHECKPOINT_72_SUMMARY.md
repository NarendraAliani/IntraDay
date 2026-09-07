# CHECKPOINT 72 — Summary

Scope: a lightweight, OPERATOR-TRIGGERED routine that keeps RELIANCE/
TCS/HDFCBANK/INFY's `5m` coverage current as trading days pass, so the
real dataset can grow without a manual checkpoint every day. Market
closed. No strategy code changes, no registry change, no
`RESEARCH_ACTIVE` status change. Tooling/process checkpoint only.

```
mechanism_chosen: Django management command (backfill_daily_coverage),
                  manually triggered - NOT wired to Celery Beat, NOT
                  auto-scheduled by this checkpoint
new_fetch_mechanism: NONE - reuses HistoricalDataPreparationService.
                     prepare() verbatim, same path every prior
                     checkpoint has used
idempotency_proven: YES - 10 unit tests (fakes only) + one real,
                    explicitly-reported test against production data
                    (0 api_requests, 0 rows changed)
p4_discipline: YES - upsert-by-identity only, proven directly (test 6)
incidental_finding: the pre-existing 2026-08-17..08-28 gap is missing
                    BOTH its day-start AND day-end bar every day
                    (70/72, not just the day-start bar) - refines, does
                    not change, CHECKPOINT_71's finding; NOT fixed here
default_lookback_adjusted: 10 -> 7 days specifically because of the
                           above finding (see §3)
operator_action_required: YES - see §5, nothing runs automatically
memory_md_updated: YES - confirmed below
commit: (recorded below)
blockers: []
```

## 1. Design options considered

**Option A — manual script, operator runs it by hand.** Simplest,
most operator control, but relies on remembering; no automation at
all if the operator forgets for a few days (mitigated by the routine
itself being idempotent and safe to run late — see §2).

**Option B — Django management command + Windows Task Scheduler.**
Same command as Option A, but the operator can OPTIONALLY register it
with Task Scheduler themselves for automatic daily execution.
Trade-off: requires a one-time manual setup step (Task Scheduler GUI
or `schtasks`), and — critically — this checkpoint does **not** and
**cannot** register that scheduled task on the operator's behalf (no
admin/interactive session available to this agent, and doing so
silently would violate this project's own "no surprise automation"
discipline, restated explicitly in this checkpoint's own instructions).

**Option C — an existing daily process.** Checked first, as instructed
— **one already exists**: `src/intraday/celery.py`'s `beat_schedule`
already runs `market_data_ingestion_tick` (every 60s),
`emergency_square_off_check_tick` (every 15s), and
`eod_sequence_tick` (daily, 10:15 UTC) automatically, with no manual
trigger, once a Celery worker + beat process are running. **Deliberately
NOT reused for this routine.** Reason: every one of those 3 existing
tasks either has no real network side effect
(`emergency_square_off_check_tick`, `eod_sequence_tick` are pure
domain-state transitions) or its network call is gated behind the
scanner's own explicit `ScannerConfiguration` activation
(`market_data_ingestion_tick` — no active configuration, no Dhan call).
A Celery Beat entry for THIS routine would make a REAL, unconditional
Dhan REST call every day **automatically, forever, with no per-run
operator action** — directly in tension with P6 ("no Dhan network call
outside an explicitly authorized data-fetch checkpoint") and this
checkpoint's own explicit rule 5 ("do not silently register... no
surprise automation, mirrors how `LIVE-*` checkpoints always required
an explicit launch"). Every real Dhan REST call this entire session
has been triggered by an explicit checkpoint or an explicit operator
command — this routine preserves that property instead of quietly
ending it.

**Chosen: Option A/B combined** — a Django management command
(`backfill_daily_coverage`), runnable manually right now, with
Windows Task Scheduler setup **documented, not performed** (§5), so
the operator can opt into daily automation on their own explicit
terms whenever (if ever) they choose to.

## 2. Idempotency and safety — proven, not asserted

`src/intraday/application/services/daily_coverage_backfill.py` is a
thin, infrastructure-free application service (confirmed: it is NOT
among the violations in the pre-existing, unrelated
`test_application_services_and_contracts_stay_infrastructure_free`
failure — see §4) wrapping exactly two new pieces of logic:

1. `most_recent_closed_trading_day(as_of)` — walks backward from
   `as_of` using the SAME `is_trading_day`/`build_session_for` calendar
   machinery every checkpoint this session has used, never a hardcoded
   clock guess.
2. `run_daily_backfill(...)` — computes a `[most_recent_closed_trading_day
   - lookback_days, most_recent_closed_trading_day]` window and calls
   `HistoricalDataPreparationService.prepare()` ONCE PER SYMBOL, for
   the fixed 4-symbol set, completely unmodified.

**No new fetch mechanism, no new provider code, no new persistence
path** — every actual read/write goes through the exact same
`DhanHistoricalBarProvider` + `DjangoHistoricalBarRepository` +
`HistoricalDataPreparationService` triangle `CHECKPOINT_69`/`70`/`71`
already used.

**New test file**,
`tests/unit/application/services/test_checkpoint_72_daily_coverage_backfill.py`
— 10 tests, fakes only, no database, no real network:
- `most_recent_closed_trading_day`: after-close/before-close/weekend/
  naive-datetime-rejected (4 tests).
- **Idempotency**: running twice on the same `as_of` makes ZERO new
  provider calls the second time, `api_requests==0`,
  `bars_fetched==0`, `cache_hits` matches exactly what CAS-aware
  coverage expects (test 5).
- **P4 discipline, proven directly**: every persisted bar's exact
  field values (`open`/`high`/`low`/`close`/`volume`) are captured
  after run 1, the routine is run again, and every value is asserted
  byte-for-byte unchanged — no new key added, no key removed, no value
  mutated (test 6).
- A later `as_of` (simulating "the next day") fetches only the
  genuinely new day, never re-fetching what a prior run already cached
  (test 7).
- A weekend `as_of` is a safe, correct no-crash outcome — contributes
  zero new EXPECTED bars for the weekend days themselves, and only
  the genuinely new trading day(s) inside the window are fetched
  (test 8).
- Default lookback is used when not overridden (test 9); a provider
  returning zero bars for a zero-expected-bar window produces a clean,
  honest `PreparationOutcome`, never a fabricated success or a crash
  (test 10).

All 10 pass. `[F]` Full suite re-run this checkpoint (`--reuse-db`):
see §4.

**Real-mechanism test, explicitly reported (not a fake)**: ran the
actual command (no `--dry-run`) against the real, unmodified
production database and real Dhan credentials this checkpoint:

```
RELIANCE [2026-08-31..2026-09-07]: status=COMPLETE cache_hits=432 bars_fetched=0 bars_persisted=0 api_requests=0
TCS      [2026-08-31..2026-09-07]: status=COMPLETE cache_hits=432 bars_fetched=0 bars_persisted=0 api_requests=0
HDFCBANK [2026-08-31..2026-09-07]: status=COMPLETE cache_hits=432 bars_fetched=0 bars_persisted=0 api_requests=0
INFY     [2026-08-31..2026-09-07]: status=COMPLETE cache_hits=432 bars_fetched=0 bars_persisted=0 api_requests=0
```

**`api_requests=0` for all 4 symbols — genuinely zero Dhan calls made**,
confirmed by `HistoricalBar` row counts being byte-identical before and
after (RELIANCE 2071, TCS/HDFCBANK/INFY 1994/1995, unchanged). This
proves the idempotency property end-to-end against real data, not just
against the unit tests' fakes — running this command today, right now,
against the current real dataset is a genuine no-op, exactly as
designed, because `CHECKPOINT_70`/`71` already backfilled through
`2026-09-07`.

## 3. Incidental finding: the old gap is worse than previously recorded (not fixed here)

While choosing `DEFAULT_LOOKBACK_DAYS`, a **10-day** value was tried
first and its resulting window — checked live against today's real
date (`2026-09-07`) — landed its start boundary exactly on
`2026-08-28`, the LAST day of the already-known
`2026-08-17`–`2026-08-28` gap. A direct coverage check on that
boundary surfaced a **more complete characterization of that
pre-existing gap than `CHECKPOINT_71`'s own recon recorded**: every one
of those 10 days is missing **both** its day-start bar (`03:50 UTC`)
**and** its day-end bar (`09:45 UTC`) — 70 bars/day, not 72, uniformly
across all 10 days (checked directly: `min=03:55 UTC, max=09:40 UTC`
for every single day in the block). `CHECKPOINT_71`'s recon correctly
identified the CANONICALIZATION-STATE root cause (pre-write-time-logic
rows) but did not check the exact bar COUNT within that block — this is
a refinement of that finding, not a contradiction or a new gap.

**Not fixed, not further investigated, per this checkpoint's own
explicit rule 4.** Response was purely defensive: `DEFAULT_LOOKBACK_DAYS`
was set to **7** (not 10) specifically so this routine's window can
never reach back far enough to touch that block, now or for the
foreseeable future — a deliberate, documented design choice (see the
constant's own docstring), not an accidental avoidance. This finding
is reported here because it materially informed this checkpoint's own
design decision, but resolving it remains, as instructed, entirely the
operator's own deferred choice (the same `67.7`–`67.13-C` migration
already on record).

## 4. Full suite regression check

`.venv/Scripts/python.exe -m pytest -q --reuse-db`, full suite, run
directly (backgrounded due to runtime).

**Result: 7 failed, 3292 passed**, 652.84s. Exact names:

1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_migration_67_11_6_backup_restore_rehearsal.py::test_canary_backup_restores_with_exact_field_preservation_in_disposable_db`
4. `test_migration_67_12_pre_integrity_hardening.py::test_h_live_backup_restored_three_way_equality`
5. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
6. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
7. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**5 of these are the SAME pre-existing failures documented at every
prior checkpoint this session.** The other 2 (#3, #4) are the SAME
stale-disposable-table-row flake already documented and root-caused at
`CHECKPOINT-GAINZ-C`'s own §4/§5 — investigated directly again here,
not assumed benign: re-ran both in isolation with `--reuse-db` and got
the identical fingerprint-mismatch failures, then re-ran with
`--create-db` (forces a clean test database) and both **passed**.
Neither test file, nor anything either imports, appears anywhere in
this checkpoint's diff. `[F]` Confirmed directly that neither new file
(`daily_coverage_backfill.py`, `backfill_daily_coverage.py`) appears
among the `test_application_services_and_contracts_stay_infrastructure_free`
violation list (grepped for the new filenames in that test's own
failure output — no match). **Zero genuine regressions.**

## 5. What the operator needs to do to activate this

**Nothing is required** — the routine is already runnable manually
today:

```
.venv\Scripts\python.exe manage.py backfill_daily_coverage
```

Add `--dry-run` to preview the window without contacting Dhan or
writing anything; add `--lookback-days N` to override the 7-day
default for a one-off catch-up (e.g. after a longer-than-usual gap in
running it) — this does NOT change the default, only that one
invocation.

**To automate it daily (entirely optional, operator's own choice,
NOT performed by this checkpoint):**

1. Open Task Scheduler (`taskschd.msc`) → **Create Basic Task**.
2. Name it something like "IntraDay daily coverage backfill".
3. Trigger: **Daily**, at a time comfortably after market close —
   e.g. **16:00 IST** (safely after the 15:30 close and any same-day
   settlement delay).
4. Action: **Start a program**.
   - Program/script: `D:\IntraDay\.venv\Scripts\python.exe`
   - Add arguments: `manage.py backfill_daily_coverage`
   - Start in: `D:\IntraDay`
5. Finish. Optionally check "Run whether user is logged on or not" if
   the operator wants it to run unattended (requires storing the
   operator's own Windows credential in the task, a standard Task
   Scheduler prompt — no code change or admin action by this
   checkpoint is involved).

This is documented instructions only, per this checkpoint's own rule
that anything requiring admin/interactive setup gets written up for
the operator rather than attempted as a workaround. **No Task
Scheduler entry has been created by this checkpoint.**

## `MEMORY.md` update — confirmed made

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording:
the routine's existence and mechanism (`backfill_daily_coverage`,
manual/operator-triggered only, 7-day rolling lookback), how the
operator triggers and monitors it (§5 above, condensed), the Celery
Beat "why not" decision, and the incidental gap-severity refinement
from §3. Matches the file's existing structure and tone. **Confirmed
explicitly here, as this checkpoint's own instruction required.**

## Governance compliance

- P3: the only real DB-write attempt this checkpoint was the
  explicitly-reported real-mechanism test in §2, which made **zero**
  actual writes (`api_requests=0`, row counts unchanged, confirmed
  directly).
- P4: proven directly via a dedicated unit test (test 6), not merely
  assumed from the underlying `prepare()`/`bulk_upsert()` contract.
- P6: no unconditional/automatic Dhan network call exists anywhere in
  this codebase as a result of this checkpoint — the new command is
  operator-triggered only, and Celery Beat was deliberately NOT used
  (§1).
- P9: no strategy logic touched.
- `registry.py`: not touched, not relevant to this checkpoint.
- P10: no scanner activation, no live-market interaction.
- P11/P16: this summary, `MEMORY.md`, the new application service, the
  new management command, and the new test file are committed to
  `active-development` only.
