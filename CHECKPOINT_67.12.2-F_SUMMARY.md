# Checkpoint 67.12.2-F (3rd attempt) — Historical Backfill Pilot: COMPLETE

```
checkpoint: 67.12.2-F
verdict: PILOT_COMPLETE
symbols: [RELIANCE, TCS, HDFCBANK]
date_range_requested: 2026-08-05 to 2026-09-01
trading_days_skipped: [2026-08-08, 2026-08-09, 2026-08-15, 2026-08-16, 2026-08-22, 2026-08-23, 2026-08-29, 2026-08-30] (all weekends, correctly excluded)
rows_inserted: 20521
rows_skipped_duplicate: 0 explicit skips (idempotency instead expressed as partial-range fetches — see B)
rows_rejected: 0
rate_limit_events: 0
invariant_violations: 0
commit: (recorded below after commit)
blockers: []
```

## Preamble — this is a re-attempt

The first attempt at this checkpoint today HALTED at Part 0 (a stale
`WorkerRuntimeStatus` row read `RECONNECTING` despite no process
actually running — see `git log` for that commit). With the user's
explicit authorization, that one known-stale row was corrected to
`STOPPED` as a one-time data fix (not a code change), and this
checkpoint was re-run from Part 0 through completion. All three Part 0
gates now pass on their own merits, re-verified independently below.

## A. Part 0/1 findings

**Part 0** (re-verified, not assumed from the correction alone):
1. `WorkerRuntimeStatus(dhan).worker_state = STOPPED`, `stop_requested_at
   = None`. Pass.
2. 67.12.2-E's addendum confirmed complete (its own commit `67ff25a`
   already established this; re-confirmed here via check 3).
3. `ScannerConfiguration(dhan)`: `universe_mode=ALL_CONFIGURED`,
   `timeframe=3m`, `selected_instrument_ids=()` — exactly the
   originally recorded values. Pass.

**Part 1** — Dhan's documented limits, read from
`docs/architecture/DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md`:
- Intraday requests capped at **90 days of data per single request**
  (already implemented as chunking in `historical_client.py`, not
  newly discovered). Intraday data available going back **5 years** —
  no lookback concern for a 20-trading-day window.
- Rate limit: no endpoint-exact figure directly quoted from Dhan's
  page. The document's own "Data APIs" category (5/sec, 100,000/day)
  is a **medium-confidence inference** for `/v2/charts/*` endpoints,
  not a directly-quoted mapping. Per this checkpoint's own fallback
  instruction, used the most conservative documented figure anywhere
  in the project instead: **1 request/second** (the high-confidence,
  independently-confirmed "Quote APIs" rate from Checkpoint 22/23).
- REST vs. WebSocket quota independence: **inferred, not confirmed** —
  the rate-limit table lists "Data APIs" and "Quote APIs" as separate
  named categories, suggesting independent quotas, but Dhan's page
  does not explicitly state this. Reported as an open, medium-
  confidence item, not treated as settled.

## B. What was actually fetched vs. requested

Exactly as scoped: 3 symbols × 20 trading days = 60 `(symbol, day)`
pairs, timeframe `ONE_MINUTE`, full session (09:15–15:30 IST request
window). 8 calendar weekend days within the range correctly excluded
(listed in the header block).

**All 60 requests succeeded** (60 real `POST /v2/charts/intraday`
calls, all HTTP 200), paced at 1 request/second between calls, zero
rate-limit-shaped responses.

`[F]` **Idempotency was expressed as partial-range re-fetching, not a
simple row-level skip** — this is the existing, correct
`HistoricalDataPreparationService` behavior (the same mechanism
67.12.2-J/K/O's tests already verify against fakes), observed here
against real data for the first time in this pilot:
- 15 of 60 `(symbol, day)` pairs already had 44 pre-existing rows
  (from the original narrow capture earlier this session) — the
  service correctly fetched only the **missing** 315 bars for each
  (359 full session − 44 already-present = 315, confirmed exactly for
  every one of those 15 pairs), never re-fetching or duplicating the
  44 that already existed.
- 1 pair (`RELIANCE`/`2026-08-31`) was already **fully** covered (from
  67.12.2-Q's own pull earlier tonight): `bars_fetched=0`,
  `bars_persisted=0` — correctly zero new rows. **One minor
  inefficiency worth naming honestly**: the preparation service still
  made a real HTTP request for this already-fully-covered date (the
  same `PARTIAL`-status coverage-accounting nuance 67.12.2-Q already
  found — the completeness check compares against the full
  09:15–15:30 request window rather than these instruments' actual
  09:17–15:15 CAS-shortened session, so it never reports `COMPLETE`
  and always re-attempts a fetch for the "missing" 09:15–09:17/
  15:15–15:30 fringe). This wasted one API call, not any data
  correctness — zero duplicate rows resulted.
- The remaining 44 pairs had no pre-existing data: full 359-bar
  fetches.

**Total: 20,521 new rows inserted** (0 rejected, 0 explicit duplicate
skips because the service's own missing-range logic prevented
duplicates from ever being requested in the first place, rather than
fetching-then-discarding).

## C. Invariant check results — all clean, checked directly

Over the full 21,540-row scope (3 symbols × 20 days, pre-existing plus
newly inserted):
- **OHLC sanity**: 0 violations (`low <= min(open,close)`,
  `high >= max(open,close)`, `high >= low` all hold for every row).
- **Non-positive prices**: 0.
- **Negative volume**: 0.
- **Duplicate `(symbol, timeframe, bar_timestamp)`**: 0 groups.
- **Provenance**: 100% `REAL_DHAN` (21,540/21,540) — no row in scope
  stamped anything else.
- **Session-window compliance**: 0 timestamps outside 09:15–15:30 IST.
- **Per-day bar count**: **exactly 359 bars for every one of the 60
  `(symbol, day)` pairs** — perfectly uniform, matching these three
  `CATEGORY_I_CAS` instruments' known CAS-shortened continuous-trading
  window (09:17–15:15 IST inclusive, 359 one-minute bars), with zero
  gaps in any day for any symbol.

## D. Recommendation

The pilot succeeded cleanly across all 60 requested units with zero
rate-limit events and zero data-quality problems. Per this
checkpoint's own "do not over-engineer" instruction, no generalized
backfill framework was built. If a future checkpoint decides to widen
this:
- The one real inefficiency found (a wasted request on an
  already-fully-covered date, caused by the coverage predicate's
  full-window vs. CAS-shortened-window mismatch) is worth fixing
  before scaling this up meaningfully — at 1 req/sec pacing it's cheap
  today, but would compound linearly with a much larger symbol/date
  matrix.
- The REST-vs-WebSocket quota independence question (Part 1) should be
  confirmed directly with Dhan (or empirically, cautiously) before ever
  running a wide REST backfill concurrently with a live WebSocket
  capture — this pilot deliberately never tested that combination
  (Part 0 explicitly refused to run while anything live was active).
- This is unwired from `is_research_eligible()` deliberately, per this
  checkpoint's own scope — these 20,521 new rows are real, correctly
  provenance-stamped `HistoricalBar` data, but (per 67.12.2-L/P) will
  not pass the research-eligibility gate until `ONE_MINUTE`
  canonicalization is separately, formally proven (67.12.2-Q already
  produced one genuinely well-shaped sample for that future proof;
  this pilot now adds many more).
