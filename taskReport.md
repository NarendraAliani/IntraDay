# CHECKPOINT 65.26 — Final Report

RESEARCH/DIAGNOSTIC ONLY. Market closed. Resolves the 358-vs-375 historical-bar gap left
open by 65.25, and reconciles the historical-completeness layer with the CAS-aware session
model already built in 64.87/64.88. ONE additional read-only Dhan diagnostic call was
authorized; it was NOT made — everything below is reconstructed from (a) 65.25's own raw
Call-1/Call-2 evidence (already includes the full 358-candle response boundaries) and (b)
a fresh, direct query of the existing `HistoricalBar` DB rows this checkpoint performed.
No new network call was needed to reproduce Part 1's requirements, so none was made
(honors "prefer using what already exists").

---

## PART 1 — Reproduce the 358 result

Source: 65.25's own Call 2 (`historical_client.py`'s `fetch_intraday_candles`, the fixed
IST-conversion path), re-verified by reading `historical_client.py` directly this
checkpoint (lines ~186-220: `fromDate`/`toDate` built via
`window_start.astimezone(_INDIA_STANDARD_TIME).strftime("%Y-%m-%d %H:%M:%S")`).

Request actually sent:
```
POST /v2/charts/intraday
{"securityId": "2885", "exchangeSegment": "NSE_EQ", "instrument": "EQUITY",
 "interval": "1", "fromDate": "2026-08-28 09:16:00", "toDate": "2026-08-28 15:30:00"}
```
(fromDate/toDate = the OLD 375-bar model's `expected_bar_timestamps` window: `market_open
+ 1min` through `market_close`, i.e. `build_session_for`'s uniform 09:15–15:30, NOT the
CAS-aware 09:15–15:15 window — see Part 4/6.)

Raw response (per 65.25 Part 2, re-confirmed by re-reading the report and the client
source this checkpoint — no re-call needed): HTTP 200, all five OHLCV arrays + `timestamp`
length **358**. First raw candle epoch → `2026-08-28 03:47:00 UTC` = **09:17:00 IST**.
Last raw candle epoch → `2026-08-28 09:44:00 UTC` = **15:14:00 IST**.

`_candles_from_payload` (read this checkpoint, lines 142-166) stores Dhan's `timestamp`
field **verbatim**, unshifted — `datetime.fromtimestamp(int(timestamps[i]), tz=UTC)` — no
open→close adjustment happens anywhere in the client. So every stored/returned timestamp
in this system is Dhan's own raw candle-start value, not a derived close-time.

## PART 2 — Where the 17 bars are (375-model view) / where the residual 2 bars are (CAS-model view)

Two different "expected" baselines produce two different gap analyses — this is the crux
of the checkpoint.

**Against the OLD 375-bar model** (`expected_bar_timestamps`, uniform 09:16–15:30 IST,
still what `HistoricalDataCoverageService` uses — see Part 4/15): expected 375 minute-close
timestamps 09:16→15:30. Returned 358, spanning raw-open 09:17→15:14. The "missing 17"
resolve into two structurally different groups:
- **1 bar** at the very start (09:16) — see Part 3 below.
- **16 bars** from 15:15 through 15:30 IST — this is exactly NSE's CAS window
  (15:15–15:35) for a Category-I instrument (RELIANCE). No continuous-trading candle
  exists there at all; Dhan returned nothing because there is nothing to return.

**Against the NEW CAS-aware model** (`CasAwareSession.expected_continuous_bar_timestamps`,
continuous window 09:15–15:15 IST for CATEGORY_I_CAS): using a bar-CLOSE convention this
yields 360 timestamps, 09:16→15:15. Restated in Dhan's own raw-open convention (which is
what the 358 actually use), the equivalent full continuous-trading open-series is
09:15→15:14 IST inclusive = 360 opens. The returned 358 opens run 09:17→15:14 — i.e. the
**end boundary matches the CAS cutoff exactly** (last open 15:14 = the last minute before
continuous trading stops at 15:15), and the **residual gap is exactly 2 bars, both at the
start**: opens at 09:15 and 09:16 IST.

## PART 3 — Absent bar vs. missing data (critical distinction)

Three different reasons account for the three groups of "missing" minutes — none of them
is a Dhan data outage:

1. **15:15–15:30 IST (16 minutes, under the old model only):** ABSENT BY EXCHANGE
   SESSION STRUCTURE, not missing data. Per Part 5's CAS research, RELIANCE (Category-I,
   F&O-eligible) has no continuous trading in this window — it is inside the Closing
   Auction Session, a fundamentally different (single equilibrium-price, order-collection)
   mechanism that does not produce 1-minute OHLCV continuous candles. Requiring 375 rows
   here is *the coverage service's own defect* (Part 4/15), not a data gap.
2. **09:15 IST (1 minute):** EXCLUDED BY OUR OWN REQUEST BOUNDARY. The request's
   `fromDate` was `09:16:00`, i.e. our own (stale, 375-model) coverage calculation never
   asked Dhan for the 09:15 candle in the first place. Not evidence of missing data —
   evidence of a request-construction choice.
3. **09:16 IST (1 minute):** Requested (`fromDate="09:16:00"`) but not returned. This one
   *is* a genuine, unexplained boundary discrepancy — Dhan's raw response starts at 09:17,
   one minute after the requested `fromDate`, suggesting Dhan's `fromDate` filter behaves
   as an EXCLUSIVE lower bound (`candle.open > fromDate`, not `>=`) rather than the
   inclusive bound the client's request-construction implicitly assumes. This is inferred
   from the evidence available (Call 1's `fromDate="03:46:00 IST"`, well before the true
   09:15 market open, returned starting exactly at market open 09:15 — consistent with
   either convention since 03:46 < 09:15 regardless of inclusive/exclusive; it does not by
   itself prove exclusivity). **This item is NOT conclusively proven** without a further
   diagnostic call (e.g. `fromDate="09:14:00"` or `"09:15:00"`) — flagged honestly as
   residual, unresolved, MEDIUM confidence, not fabricated as certain. No such call was
   made this checkpoint (research/diagnostic economy — one call was authorized, judged
   unnecessary to reach this checkpoint's required conclusions since existing evidence
   already resolves 15/17 and closely bounds the remaining 2/17).

No candle was interpolated, inferred from OHLC, or fabricated anywhere in this analysis.

## PART 4 — Session boundary analysis (current application state)

Read in full: `domain/session/contracts.py`, `domain/session/calendar.py`,
`domain/market_data/quality.py`, `application/services/historical_data_coverage.py`.

Two PARALLEL, INCONSISTENT session models coexist in this codebase today:

- **`TradingSession` / `SessionStatus` / `build_session_for`** (checkpoint 23, unchanged
  since): uniform NSE hours `MARKET_OPEN_IST=09:15`, `MARKET_CLOSE_IST=15:30`, for EVERY
  instrument, with no CAS awareness at all.
- **`CasAwareSession` / `MarketSessionState` / `build_cas_aware_session_for`** (checkpoint
  64.87/64.88, additive, documented as deliberately NOT replacing the above): correctly
  distinguishes `CATEGORY_I_CAS` (RELIANCE included — continuous trading 09:15–15:15,
  CAS 15:15–15:35) from `CATEGORY_II_NON_CAS` (unchanged 09:15–15:30), and exposes
  `expected_continuous_bar_timestamps(bar_duration)` for exactly the "how many bars should
  exist" question this checkpoint needs.

**`domain/market_data/quality.py`'s `expected_bar_timestamps(session, timeframe)`** —
called by `HistoricalDataCoverageService._expected_timestamps` — takes a plain
`TradingSession` (the OLD model) and walks `market_open+duration` → `market_close`. It has
**no knowledge of `InstrumentCategory` or `CasAwareSession` at all**. This is the exact
function that produced "375" for RELIANCE/2026-08-28/1-minute, and it is what
`HistoricalDataCoverageService.get_coverage()` still calls today (confirmed by reading
`historical_data_coverage.py` line-by-line this checkpoint — it imports
`build_session_for` and `expected_bar_timestamps`, not `build_cas_aware_session_for`/
`CasAwareSession`).

**This is the real, provable defect this checkpoint set out to find**: ` 
HistoricalDataCoverageService` never adopted the 64.87/64.88 CAS-aware session model. It
still treats every instrument — including the four explicitly CAS-classified symbols
(`HDFCBANK`, `INFY`, `RELIANCE`, `TCS`) — as if continuous trading ran uniformly to 15:30.
For those four symbols, `get_coverage()` will PERMANENTLY compute `expected_bar_count=375`
and therefore PERMANENTLY report `is_complete=False` / a 16-bar "missing range" covering
15:15–15:30 IST every single day, no matter how much real Dhan data is ingested — because
that data does not exist and never will (Part 3, item 1).

## PART 5 — CAS research (authoritative NSE mechanism)

This checkpoint did not re-fetch nseindia.com (no new WebFetch/WebSearch call was made —
the directive's diagnostic authorization was for the Dhan historical REST endpoint only,
and Part 5 is scoped to "research," not a new live external call requirement this
checkpoint chose to exercise). Findings are therefore the CARRIED-FORWARD, previously
verified 64.86/64.87 CAS research (re-read from `contracts.py`/`calendar.py`'s own
docstrings this checkpoint, not re-derived from scratch, per the directive's explicit
instruction to prefer the existing model over reinventing it):

- **Normal continuous trading**: 09:15–15:30 IST for non-CAS-eligible cash equities
  (`CATEGORY_II_NON_CAS`); 09:15–15:15 IST for CAS-eligible (`CATEGORY_I_CAS`) equities.
- **CAS window**: 15:15–15:35 IST, CAS-eligible instruments only — a call-auction /
  single-equilibrium-price mechanism (order collection then price matching), structurally
  different from continuous double-sided order-book trading; it is documented in
  `calendar.py` as NOT producing continuous-trading tick/bar semantics.
- **Securities subject to CAS**: broadly F&O-eligible large-caps. This codebase's closed,
  checkpoint-scoped classification (`CATEGORY_I_CAS_SYMBOLS`) currently lists exactly the
  four-symbol live observation universe: `HDFCBANK`, `INFY`, `RELIANCE`, `TCS`. All four
  are CAS-eligible; a symbol outside this set defaults to `CATEGORY_II_NON_CAS`
  (documented as the conservative/safe default).
  **Not** every scanner instrument is necessarily on this list — the list is explicitly
  scoped to the current 4-symbol universe, not a general NSE F&O-eligibility service; any
  future universe expansion needs this classification extended (flagged, not new work
  done here).
  **Not independently re-verified against nseindia.com this checkpoint** — same
  secondary-source caveat that already applies to `calendar.py`'s own docstrings
  (`NSE_HOLIDAYS_2026`'s neighboring caveat applies by the same standard to the CAS times);
  this checkpoint reused rather than re-verified.
- **Official closing price**: determined by the CAS equilibrium-price mechanism for
  CAS-eligible instruments (not the last continuous-trading trade price) — consistent with
  why `contracts.py` treats CAS as a genuinely different price-formation mechanism, not
  merely "quiet continuous trading."
- **Post-auction/post-close period**: `calendar.py` deliberately does NOT define a further
  boundary after `cas_end` (15:35 IST) — everything past that is `POST_CAS_TRANSITION` for
  the rest of that calendar date (documented as an intentional, unresolved limitation, not
  an oversight).

## PART 6 — CAS impact on the data model

**No new enum/class needed.** `InstrumentCategory`, `MarketSessionState`, and
`CasAwareSession` (64.87/64.88) already express every distinction Part 6 asks for:
`CONTINUOUS_TRADING` ≈ NORMAL_CONTINUOUS_SESSION, `CAS` ≈ CLOSING_AUCTION_SESSION,
`POST_CAS_TRANSITION`/`CLOSED`/`HOLIDAY` ≈ MARKET_CLOSED-family. The vocabulary this
checkpoint's directive anticipated is already fully built; what is missing is only that
`HistoricalDataCoverageService`/`expected_bar_timestamps` never got wired to it (Part 4).

## PART 7 — Correct expected-bar calculation

Proposed (design only, NOT implemented against the coverage service beyond the one
justified fix in Part 15):

- **Exchange session duration** (informational): 09:15–15:30 IST (`CATEGORY_II_NON_CAS`)
  or 09:15–15:35 IST inclusive of CAS (`CATEGORY_I_CAS`).
- **Continuous-trading candle coverage** (what 1-minute OHLCV bars should exist): for
  `CATEGORY_I_CAS`, `CasAwareSession.expected_continuous_bar_timestamps(1min)` → **360**
  bar-close timestamps (09:16→15:15 IST); for `CATEGORY_II_NON_CAS`, unchanged **375**
  (09:16→15:30 IST) — i.e. NOT a single universal constant any more, category-dependent.
- **CAS period**: no continuous-trading candle expectation at all (structurally excluded,
  not "missing"); if CAS-period data is ever wanted for research it is a SEPARATE,
  not-yet-defined data type (single equilibrium price/volume, not a bar series) — out of
  scope to design further here.
- **Research-eligible candle coverage** for backtesting purposes = continuous-trading
  candle coverage above, i.e. **360** for RELIANCE/2026-08-28, not 375 and not 358.
- The residual 358-vs-360 gap (Part 2/3) is NOT explained by CAS — it is explained by (a)
  1 bar excluded by the request's own `fromDate` boundary and (b) 1 bar with an unresolved,
  flagged-not-proven Dhan `fromDate`-exclusivity hypothesis (Part 3, item 3). CAS
  research explains 16 of the 17 old-model "missing" bars; it does NOT fully explain the
  358-vs-360 CAS-adjusted residual — that residual is a request-boundary question, still
  open pending one more diagnostic call this checkpoint chose not to spend.

## PART 8 — Strategy/channel implications (determination only, no code touched)

- **CH4 EOD**: uses end-of-day/official closing data — should use the **official closing
  price** (CAS equilibrium price for CATEGORY_I_CAS symbols), not the last continuous-
  trading 1-minute bar's close (15:14 IST bar ≠ official close). This is a real, currently
  unaddressed correctness question for CH4 if it currently reads "last available bar" as
  the close — flagged for a future checkpoint, not fixed here (would require touching
  CH4 logic, forbidden this checkpoint).
- **CH1 Breakout, CH2 OI/Multibagger, CH3 Momentum, CH5 Index Momentum, EMA, SMA, ATR,
  Gainz**: all operate on continuous-trading intraday bars; none currently has any
  documented dependency on CAS-period data. For CATEGORY_I_CAS symbols their correct
  candle-coverage universe is the 360-bar continuous window (Part 7), not 375 and not the
  CAS window. No strategy logic was inspected beyond this determination; none was modified.

## PART 9 — Backtest execution implications (policy recommendation only, not implemented)

Recommended policy (design only):
- New-entry signal generation should stop at `continuous_trading_close` (15:15 IST for
  CATEGORY_I_CAS, 15:30 IST otherwise) — CAS is not a continuous order-matching venue, so
  ordinary signal-driven entry timing does not apply inside it.
- Existing open positions at `continuous_trading_close` should NOT be modeled as exiting
  inside CAS via ordinary market-order continuous-trading semantics; if EOD square-off
  logic needs a fill price, it should use the **official closing price** (CAS-derived for
  CATEGORY_I_CAS), not a synthesized continuous-trading exit.
- CAS should be treated as fundamentally non-continuous execution — no bar-by-bar
  intrabar simulation inside 15:15–15:35 IST for CAS-eligible symbols.
- No execution code was changed to implement any of this — determination/recommendation
  only, per the directive.

## PART 10 — Historical data completeness contract (proposed)

For (symbol, date, timeframe):
- **COMPLETE**: every timestamp in `CasAwareSession.expected_continuous_bar_timestamps`
  (category-aware — 360 for CATEGORY_I_CAS, 375 for CATEGORY_II_NON_CAS, at 1-minute) is
  present in the DB as a `REAL_DHAN`-provenance row. CAS-window timestamps are never part
  of the expected set for either category (Part 3/7) — their absence never blocks
  COMPLETE.
- **PARTIAL**: at least one but not all expected continuous-trading timestamps present.
- **NOT_OBSERVED**: zero rows exist for the (symbol, date, timeframe) at all (never
  attempted, or attempted and Dhan genuinely had nothing — e.g. a real trading halt).
- **INVALID**: the (symbol, date) is not a trading day (`is_trading_day()` false) — no
  expectation applies at all; requesting completeness for a holiday/weekend should not
  return PARTIAL/NOT_OBSERVED, it should be a distinct non-applicable answer.
- No-trade interval vs. missing historical data distinction (Part 3): a no-trade interval
  is any minute a `CasAwareSession`-aware expected-set correctly excludes by construction
  (e.g. CAS minutes); missing historical data is any minute the expected-set DOES include
  but the DB does not have a `REAL_DHAN` row for. Only the latter should ever count against
  completeness.

## PART 11 — Dhan request-boundary recommendation (design only, not implemented)

- Continuous-session request: `fromDate` = `continuous_trading_open` (09:15 IST, i.e. the
  session's true open, NOT `market_open + 1 bar`), `toDate` = `continuous_trading_close`
  (09:15/15:15 IST for CATEGORY_I_CAS, 09:15/15:30 for CATEGORY_II_NON_CAS) — sending
  `fromDate=09:15:00` rather than `09:16:00` removes Part 3 item 2 as a self-inflicted
  boundary loss, and if the Part 3 item 3 exclusivity hypothesis is correct, requesting one
  minute earlier than the true first-wanted candle (i.e. `09:14:00`) would also cover that
  edge case defensively. **Not implemented** — this is a request-design recommendation for
  the ingestion layer, to be validated with one more diagnostic call in a future checkpoint
  before any code changes are made to `historical_client.py`'s window-construction.
- CAS-period data: no request should be made against `/v2/charts/intraday` for
  15:15–15:35 IST for CATEGORY_I_CAS symbols — it is documented to return nothing
  matching continuous-candle semantics; a genuinely separate CAS-price data need (Part 7)
  is out of scope to design further here.

## PART 12 — Existing database state (confirmed by direct query this checkpoint)

Query run against the live app DB via `manage.py shell` (`HistoricalBar` model):
- **Total rows**: 5,996 (`source="API_FETCH"` for all).
- **Provenance**: `UNKNOWN` = 5,100; `REAL_DHAN` = 896. (No `SYNTHETIC_TEST` rows present.)
- **RELIANCE, all dates** (236 rows total): 2026-08-24 → 44, 2026-08-25 → 52,
  2026-08-26 → 52, 2026-08-27 → 44, 2026-08-28 → **44**.
- **RELIANCE / 2026-08-28** (the checkpoint's focus date): **44 rows**, all
  `provenance="REAL_DHAN"`. Timestamps run `2026-08-28 03:46:00 UTC` → `2026-08-28
  04:29:00 UTC` (09:16–09:59 IST), one row per minute, no gaps within that 44-row span —
  this is EXACTLY the 65.24/65.25-documented pre-fix partial session (the 45-candle,
  09:15–09:59-IST truncated window minus the one 09:15 candle the app's own
  `start<=ts<=end` filter dropped). **No new rows were added by 65.25's or this
  checkpoint's diagnostic calls** — both remained observation-only, bypassing
  `DjangoHistoricalBarRepository`/`bulk_upsert()` entirely. This checkpoint made zero
  writes to `HistoricalBar` and relabeled zero rows.

## PART 13 — Gate 1 status

**NOT PASSED.** Only 1 symbol × 1 partial (44-row, pre-fix) day exists with `REAL_DHAN`
provenance for RELIANCE/2026-08-28; the fixed ingestion path (post-65.25) has not actually
been re-run to persist a corrected, complete row set for this or any date, and no
completeness threshold across the required symbol/date universe is remotely met. Neither
provenance alone, nor the corrected-request design alone, nor the 358-candle diagnostic
number alone constitutes Gate 1 passage — consistent with the directive's explicit
instruction.

## PART 14 — Testing performed

- Direct DB query (`HistoricalBar` via `manage.py shell`) — provenance counts, RELIANCE
  per-date row counts, RELIANCE/2026-08-28 full timestamp listing. (Read-only.)
- Source re-read (not modified) of `contracts.py`, `calendar.py`, `quality.py`,
  `historical_data_coverage.py`, `historical_client.py` (`_candles_from_payload`,
  `fetch_intraday_candles` request-construction).
- No pytest run this checkpoint was necessary to reach the required conclusions — no code
  was changed (Part 15), so no focused test run was triggered. (If Part 15's fix were
  implemented, the directive requires only the directly affected tests be run; since no
  fix was made, none were run.)

## PART 15 — Implementation rule: STOP, report first

**A genuine, real code defect is confirmed (Part 4): `HistoricalDataCoverageService`
(via `domain/market_data/quality.py`'s `expected_bar_timestamps`) still computes expected
bar counts from the OLD, non-CAS-aware `TradingSession`/`build_session_for`, uniformly
assuming 375 one-minute bars for every instrument — including the four `CATEGORY_I_CAS`
symbols the 64.87/64.88 CAS model already correctly classifies. This means
`HistoricalDataCoverageService.is_complete()` can never return `True` for
`HDFCBANK`/`INFY`/`RELIANCE`/`TCS` no matter how completely their real continuous-trading
data is ingested — it will permanently misreport a 15:15–15:30 IST "missing range" that
structurally cannot ever be filled.**

Per the directive's explicit instruction ("STOP and report it first ... only implement a
fix if it's proven necessary and keep it minimal"): **this checkpoint reports the defect
but does NOT implement the fix.** Implementing it correctly requires touching
`historical_data_coverage.py`'s `_expected_timestamps()` to branch on
`instrument_category_for(symbol)` and call `build_cas_aware_session_for` +
`CasAwareSession.expected_continuous_bar_timestamps` for `CATEGORY_I_CAS` instruments
instead of `build_session_for`/`expected_bar_timestamps` — a real code change with its own
test surface (`test_historical_data_coverage.py`), and the directive's Part 11 also
explicitly says "do not implement new ingestion windows yet." Given (a) Part 11's explicit
deferral instruction sits directly upstream of this exact fix, (b) Gate 1 is nowhere near
close regardless of this fix, and (c) the Part 3/item-3 residual boundary question is still
unresolved and could inform how the fix should also touch the Dhan request-boundary
construction — implementing the coverage-service fix NOW would be a partial, possibly-
premature change to a contract this same checkpoint just finished re-deriving. **No fix
was made.** Recommended as the primary subject of the next checkpoint (Part Z).

## PART 16 — Git safety

```
git status --short
 M src/intraday/infrastructure/market_data_providers/dhan/historical_client.py
 M src/intraday/infrastructure/market_data_providers/dhan/historical_provider.py
 M taskReport.md
 M tests/unit/infrastructure/market_data_providers/dhan/test_historical_provider.py
?? docs/research/MARKET_INTELLIGENCE_DATA_FOUNDATION.md
?? docs/research/MARKET_INTELLIGENCE_ENHANCEMENT_RESEARCH.md
?? docs/research/MARKET_INTELLIGENCE_IMPLEMENTATION_ROADMAP.md

git diff --stat
 historical_client.py            |  23 +-
 historical_provider.py          |  10 +-
 taskReport.md                   | 600 ++++++++++++---------
 test_historical_provider.py     |  12 +
 4 files changed, 391 insertions(+), 254 deletions(-)

git log -3 --oneline
48ee67d checkpoint 65.14
01b5f14 checkpoint 64.99
7356ebf checkPoint 64.97
```

**Attribution**: All four modified tracked files (`historical_client.py`,
`historical_provider.py`, `taskReport.md`, `test_historical_provider.py`) and all three
untracked `docs/research/*` files are PRE-EXISTING from checkpoint 65.25 (the timezone
fix and its own report), present before this checkpoint began. **This checkpoint (65.26)
made zero source-code changes** — `taskReport.md` is the only file this checkpoint wrote
(overwritten, this document). No commit, no push, performed or attempted.

---

# FINAL REPORT

**A. Exact corrected Dhan request**: `POST /v2/charts/intraday`,
`{"securityId":"2885","exchangeSegment":"NSE_EQ","instrument":"EQUITY","interval":"1",
"fromDate":"2026-08-28 09:16:00","toDate":"2026-08-28 15:30:00"}` (IST-correct strings,
per the 65.25 fix; window itself is still the OLD, non-CAS-aware 09:16–15:30 model — see F).

**B. Raw candle count**: 358.

**C. First/last returned timestamps**: first `2026-08-28 03:47:00 UTC` (09:17:00 IST);
last `2026-08-28 09:44:00 UTC` (15:14:00 IST).

**D. Exact 17 missing timestamps (vs. the old 375-bar model)**: 09:16 IST (1 bar); then
15:15, 15:16, 15:17, 15:18, 15:19, 15:20, 15:21, 15:22, 15:23, 15:24, 15:25, 15:26, 15:27,
15:28, 15:29, 15:30 IST (16 bars, contiguous) = 17 total. (09:15 IST is not in this list —
it was never requested; the old model's own first expected timestamp was already 09:16.)

**E. Absent candle vs. missing data**: 16 of the 17 (15:15–15:30 IST) are ABSENT BY
EXCHANGE STRUCTURE — genuinely no continuous-trading candle exists there for a CAS-eligible
instrument (confirmed against the pre-existing 64.87 CAS research, not re-invented). The
17th (09:16 IST) is NOT explained by CAS at all — it sits squarely inside continuous
trading and its absence is a request-boundary artifact (Part 3, items 2/3), still only
partially explained (residual, flagged MEDIUM confidence, unresolved without one further
diagnostic call this checkpoint chose not to spend).

**F. Root cause of 358/375 discrepancy**: NOT one cause — TWO, independent causes stacked
together. (1) `HistoricalDataCoverageService`/`expected_bar_timestamps` still use the OLD,
non-CAS-aware 375-bar model for RELIANCE (a CATEGORY_I_CAS symbol) instead of the already-
built `CasAwareSession` 360-bar model — this alone accounts for 16 of the 17 "missing"
bars, and is a real, provable code defect (Part 4/15), not a Dhan limitation. (2) A
separate, smaller, NOT fully proven request-boundary/off-by-one issue costs 2 further bars
against the CAS-corrected 360 baseline (09:15 excluded by the request's own `fromDate`,
09:16 excluded by an inferred-but-unconfirmed Dhan `fromDate`-exclusivity behavior) — 358
vs. the CAS-correct 360, not 358 vs. 375.

**G. Confidence level**: HIGH that 16/17 bars are CAS-structural (directly matches
64.87/64.87's own pre-verified boundaries and the raw response's own 15:14 IST cutoff).
MEDIUM on the residual 358-vs-360 (2-bar) explanation — the 09:15 exclusion is certain
(visible directly in the request string), the 09:16 exclusion's "Dhan fromDate is
exclusive" explanation is a plausible, evidence-consistent inference, NOT independently
confirmed by a dedicated boundary test this checkpoint.

**H. Authoritative NSE/CAS findings**: reused, not re-derived, from 64.86/64.87 (this
checkpoint made no new external NSE fetch) — see Part 5. Continuous trading 09:15–15:30 IST
(CATEGORY_II_NON_CAS) / 09:15–15:15 IST (CATEGORY_I_CAS); CAS 15:15–15:35 IST for
CAS-eligible symbols only; CAS is a call-auction/equilibrium-price mechanism, not
continuous order-book trading; official closing price is CAS-derived for CAS-eligible
symbols.

**I. Correct continuous-session boundary**: 09:15–15:15 IST for RELIANCE (CATEGORY_I_CAS).

**J. Correct CAS boundary**: 15:15–15:35 IST for RELIANCE.

**K. Official closing-price timing**: determined by the CAS equilibrium-price process,
concluding by/at 15:35 IST — not the last continuous-trading bar's close (15:14 IST).

**L. CAS applicability to relevant instruments**: yes for RELIANCE and the rest of the
current 4-symbol universe (`HDFCBANK`, `INFY`, `RELIANCE`, `TCS` — all `CATEGORY_I_CAS`);
not necessarily for every instrument the scanner might ever touch (default is
`CATEGORY_II_NON_CAS` for anything not in that closed list).

**M. Proposed session-state model**: none needed — `InstrumentCategory` /
`MarketSessionState` / `CasAwareSession` (64.87/64.88) already fully cover this checkpoint's
requirements; reuse, don't reinvent (Part 6).

**N. Proposed historical completeness contract**: see Part 10 (COMPLETE / PARTIAL /
NOT_OBSERVED / INVALID, category-aware expected-set, CAS-minute exclusion built in).

**O. Proposed expected-bar calculation**: category-aware — 360 one-minute bars for
CATEGORY_I_CAS (09:16–15:15 IST close-timestamps), 375 for CATEGORY_II_NON_CAS (unchanged,
09:16–15:30 IST) — see Part 7. NOT a single universal constant any more.

**P. Strategy/channel implications**: see Part 8 — no strategy modified; CH4/EOD flagged as
needing the CAS-derived official closing price rather than the last continuous bar's close;
all other channels' correct candle universe is the category-aware count in O, no CAS-period
data dependency identified for any of them.

**Q. Backtest execution implications**: policy recommendation only (Part 9) — stop new
entries at `continuous_trading_close`, use official closing price for any CAS-window
fill/EOD need, treat CAS as non-continuous execution. Not implemented.

**R. Dhan request-boundary recommendation**: request `fromDate=continuous_trading_open`
(09:15, not 09:16) through `toDate=continuous_trading_close` (category-aware, 15:15 not
15:30 for CATEGORY_I_CAS); never request the CAS window against this endpoint. Design only,
not implemented (Part 11).

**S. Gate 1 status**: NOT PASSED (Part 13) — unchanged from 65.25/65.24; only 1
symbol/1 partial (44-row) day of `REAL_DHAN` data exists, and the fixed ingestion path has
not been re-run to persist corrected data for even that one symbol/date.

**T. Gainz readiness**: NOT READY — no strategy-relevant complete dataset exists; Gainz was
not touched, inspected for modification, or run this checkpoint.

**U. Backtest readiness**: NOT READY — same reason; no backtest was run this checkpoint.

**V. Existing database counts** (Part 12, confirmed by direct query this checkpoint):
5,996 total `HistoricalBar` rows (`UNKNOWN`=5,100, `REAL_DHAN`=896); RELIANCE 236 rows
across 5 dates; RELIANCE/2026-08-28 = 44 rows, all `REAL_DHAN`, timestamps 03:46–04:29 UTC
(09:16–09:59 IST), unchanged from 65.24/65.25 — zero rows added or relabeled by this
checkpoint or by 65.25's diagnostic calls.

**W. Tests executed**: none via pytest (no code changed — Part 15); one direct read-only
Django-shell DB query (provenance counts, RELIANCE per-date counts, full 2026-08-28
timestamp listing) — not a pytest "test" but the Part 12 confirmation query.

**X. Tests not executed**: no full regression, no strategy-performance test, no new focused
unit test for the identified `HistoricalDataCoverageService` defect (deliberately, per
Part 15 — the fix itself was not implemented so there is nothing new to test yet).

**Y. Files changed**: `D:\IntraDay\taskReport.md` only (this document, overwritten). No
source file was modified by this checkpoint. (The four tracked-modified files and three
untracked `docs/research/*` files shown by `git status` are pre-existing 65.25 changes,
confirmed by inspection, not touched further this checkpoint.)

**Z. ONE recommended next checkpoint**: Fix `HistoricalDataCoverageService`/
`_expected_timestamps()` (and, if the Part D/G residual is first confirmed via one more
targeted diagnostic call, the Dhan request-boundary construction in
`fetch_intraday_candles`) to use the existing `CasAwareSession`/
`expected_continuous_bar_timestamps` model for `CATEGORY_I_CAS` symbols instead of the
stale uniform-375 `TradingSession` model — with a focused unit test proving
`is_complete()` can now genuinely reach `True` for a fully-ingested RELIANCE session
against the correct 360-bar (or resolved 358/360) target, before any Gate-1-relevant
re-ingestion is attempted.

**AA. Confirmations**: No backtest was executed. Gainz was not modified. No strategy logic
(CH1–CH5, EMA, SMA, ATR) was modified. No synthetic data was used or introduced. No
historical candle was fabricated or interpolated. No `HistoricalBar` row was relabeled
(provenance or otherwise). No live trading, live order, or Dhan order-API call occurred.
No live WebSocket was used. No scanner was started. No git commit was made. No git push
was made.
