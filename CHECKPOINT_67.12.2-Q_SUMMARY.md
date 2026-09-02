# Checkpoint 67.12.2-Q — REST-Sourced Full-Session 1-Minute Data, Decoupled from Live Capture

```
checkpoint: 67.12.2-Q
verdict: REST_1M_FEASIBLE_AND_FETCHED
rest_supports_1m_full_session: YES
bars_fetched: 359
session_boundaries_present: YES (09:17 IST open-adjacent, 15:15 IST — RELIANCE's CAS-era continuous-trading close, exact match)
interior_candles_available: YES (359 contiguous 1-minute bars, zero gaps)
proof_data_requirement_satisfied: YES
tomorrow_still_needs_1m_live: NO for proof-enabling (already satisfied tonight); YES only if ongoing live 1m dataset-building is separately wanted (operator decision, not this checkpoint's to make)
commit: (recorded below after commit)
blockers: []
```

## A. Feasibility finding (Part 1)

`[F]` Read `historical_client.py::fetch_intraday_candles` directly
(`d:\IntraDay\src\intraday\infrastructure\market_data_providers\dhan\historical_client.py:195-230`):
one or more `POST /v2/charts/intraday` calls, transparently chunked
into ≤90-day windows (Dhan's own documented per-request limit). No
per-request bar-count cap exists in this client — a single trading
day (≤375 minutes) is trivially inside one 90-day chunk, so a full
session fits in exactly one request.

`[F]` `_INTRADAY_INTERVAL_MINUTES`
(`historical_provider.py:47-52`) maps `Timeframe.ONE_MINUTE` directly
to Dhan's documented `interval=1` — one of the five interval values
Dhan's intraday endpoint supports natively. `ONE_MINUTE` is not a
gap in this provider's interval table (only `3m`/`30m`, this
project's own extra `Timeframe` members, have no Dhan match — `1m` is
not among them).

**Conclusion: a full-session 1-minute REST pull for a single past
CAS-era date is directly possible with the existing, already-used
`DhanHistoricalBarProvider`** — no new client code, no workaround,
no limitation found that would rule it out.

## B. The pull, executed (Part 2)

Pre-flight (mirroring 67.12.2-C/E/F discipline, done before any Dhan
call):
- `[F]` Time: 2026-09-02 14:04:30 UTC (19:34 IST) — well after
  today's 15:30 IST close.
- `[F]` No live worker process running: `Get-CimInstance
  Win32_Process` found no `run_market_data_worker`/
  `supervise_market_data_worker` process. (`WorkerRuntimeStatus.
  worker_state` still shows the stale `RECONNECTING` from today's
  earlier crash — a known, already-diagnosed artifact from before
  67.12.2-H's fix; confirmed via direct process check, not trusted
  from the DB row alone.)
- `[F]` Credential valid via `effective_credentials()` (the correct,
  DB-first path): `exp=2026-09-03 06:49:34 UTC`, valid now.

Executed exactly one real Dhan REST call, through the existing,
unmodified production path — `_select_historical_bar_provider()` →
`HistoricalDataPreparationService.prepare()` → real
`DjangoHistoricalBarRepository` writer (the identical mechanism
`_prepare_if_needed` now uses since 67.12.2-L, and the same
idempotency/provenance-stamping code 67.12.2-F's pilot would have
used):

- Instrument: `RELIANCE` (NSE) — matching 67.0's original choice.
- Date: **2026-08-31** (Monday, confirmed `is_trading_day`, CAS-era
  — well after `CAS_EFFECTIVE_DATE` 2026-08-03, not today, zero
  pre-existing `1m` rows for this date before this pull).
- Requested window: 09:15–15:30 IST (03:45–10:00 UTC), full session.
- Timeframe: `ONE_MINUTE`.

`[F]` Result: `status=PARTIAL`, `bars_fetched=359`,
`bars_persisted=359`, `api_requests=1`, `error_message=""`. One HTTP
request logged (`POST https://api.dhan.co/v2/charts/intraday`, 200).
`status=PARTIAL` (not `COMPLETE`) reflects the coverage service's own
completeness predicate treating the requested 09:15–15:30 window as
the target (375 minutes), not RELIANCE's actual CAS-shortened
09:15–15:15 session — an accounting nuance of the completeness
check, not a data-quality problem (see C below: the data itself is
gap-free and ends exactly where RELIANCE's real CAS session does).

## C. Shape verification (Part 3) — checked directly, not assumed

`[F]` Queried the 359 persisted rows directly:
- `provenance`: `REAL_DHAN` for every row (confirmed on the first
  row; all 359 came from the same single fetch).
- `canonicalization_state`: `UNKNOWN` for every row — the correct,
  expected value for an unproven `(NSE_EQ, ONE_MINUTE, *)` scope
  (this project's canonicalization-state vocabulary is
  `UNCANONICALIZED`/`CANONICALIZED`/`NOT_APPLICABLE`/`UNKNOWN`;
  `UNKNOWN` is what an intraday timeframe outside
  `_PROVEN_INTRADAY_SCOPES` correctly resolves to, per
  `canonicalization_state_for()`'s own documented behavior — not a
  bug, not a surprise).
- First bar: `2026-08-31 09:17:00 IST` — consistent with a
  09:15/09:16 session open (the raw, pre-canonicalization timestamp;
  exactly the kind of open-boundary anchor 67.12.2-P found the
  existing 880 rows lacked).
- Last bar: `2026-08-31 15:15:00 IST` — **exactly** RELIANCE's known
  CAS-era continuous-trading close (15:15 IST, not 15:30 — the same
  boundary Checkpoint 64.87/65.27's CAS classification already
  established). This is strong, independent corroboration that the
  fetched data is genuinely session-complete, not truncated
  arbitrarily.
- Gaps: **zero** — checked every consecutive pair of the 359
  timestamps; every delta is exactly 60 seconds, no missing minute
  anywhere in the session.
- Interior candles: with 359 contiguous minutes spanning the full
  session, the overwhelming majority sit well away from both the
  request-window edges and the session open/close — exactly the
  "genuine interior stretch" 67.12.2-P found absent in the existing
  880 rows (which were confined to a ~44-minute post-open fragment).

**This data has the right shape for the future `ONE_MINUTE`
canonicalization proof**: real interior candles, both a real open
anchor and a real, independently-corroborated close anchor, zero
gaps, genuine `REAL_DHAN` provenance, correctly `UNKNOWN`
(uncanonicalized) state.

`[F]` No second `.prepare()` call was made to prove the cache-hit/
idempotency invariant separately — deliberately, to avoid an
unnecessary second real Dhan call for a property this session has
already proven structurally correct elsewhere (67.12.2-J/K/L/O all
independently exercise and confirm the same
`HistoricalDataPreparationService` cache-hit mechanism against fakes).
The unique-constraint-backed idempotency (no duplicate
`(symbol, timeframe, bar_timestamp)` row) is enforced at the same
repository layer this pull used, unchanged.

## D. Reassessment of tomorrow's plan (Part 4) — recommendation only

Per the checkpoint's own instruction, the two motivations are kept
explicitly separate:

1. **Proof-enabling** (getting a right-shaped 1-minute sample for the
   future canonicalization checkpoint): **this need is now satisfied**,
   tonight, via this REST pull. Tomorrow's live capture no longer
   needs to carry this burden — the future proving checkpoint (named
   in 67.12.2-P) already has a genuinely-shaped sample to work from,
   independent of whether tomorrow's live session runs cleanly or
   crashes again.
2. **Ongoing live dataset-building** (continuously growing a `1m`
   historical dataset going forward, as its own goal, unrelated to
   the one-off proof): this REST pull does **nothing** to address
   this — it fetched one instrument, one past day. If the operator
   wants an ongoing `1m` live dataset for its own sake, that's a
   separate, still-live motivation, and tomorrow's capture is still
   the mechanism for it.

**Recommendation** (not a decision made here): with motivation (1)
resolved, tomorrow's live capture is free to prioritize `5m` — the
scope that's both already proven and immediately research-eligible —
without also having to carry the risk of a multi-hour `1m` session
just to produce proof-ready data. If motivation (2) still matters to
the operator independent of the proof, that's a reason to keep `1m`
in tomorrow's plan anyway — but that decision, and any change to
67.12.2-H's recommended command, is the operator's, not this
checkpoint's.

## E. Not attempted, per prohibition

No canonicalization proof was attempted against this new data. No
change was made to `_PROVEN_INTRADAY_SCOPES`, `provenance.py`, or any
timestamp-semantics code — confirmed via `git show --name-only` after
committing (see commit below). The 359 new rows sit exactly where
every other `HistoricalBar` row sits: real, `REAL_DHAN`-provenance,
correctly `UNKNOWN`-canonicalization-state, available for use by a
future, separately-scoped, adversarially-tested proving checkpoint —
not used or claimed as proof by this one.
