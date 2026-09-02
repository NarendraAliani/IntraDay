# CHECKPOINT 67.12.2-P — VERIFY ONE_MINUTE CANONICALIZATION SCOPE BEFORE TOMORROW'S CAPTURE

```
checkpoint: 67.12.2-P
verdict: ONE_MINUTE_NOT_YET_CANONICAL_CONFIRMED
one_minute_in_proven_scopes: NO
proven_scopes_full_list: [("NSE_EQ", Timeframe.FIVE_MINUTE, "CAS_ERA")]
existing_1m_data_sufficient_for_proof: NO
proof_attempt_result: INSUFFICIENT_EVIDENCE
recommendation_for_tomorrow: SWITCH_TO_5M  (operator decision — see Part D)
commit: <filled after commit>
blockers: []
```

## A. Full allowlist contents [F]

`historical_provider.py` line 153-155:

```python
_PROVEN_INTRADAY_SCOPES: frozenset[tuple[str, Timeframe, str]] = frozenset(
    {("NSE_EQ", Timeframe.FIVE_MINUTE, _ERA_CAS)}
)
```

This is the **entire** frozenset — exactly **one** entry:
`("NSE_EQ", Timeframe.FIVE_MINUTE, "CAS_ERA")`.

Confirmed by reading the full file (not just the section already known from prior
session history) that no `ONE_MINUTE` entry exists, for `CAS_ERA`, `PRE_CAS`, or
`MIXED_UNRESOLVED`. Confirmed also from `_resolve_intraday_proof_scope` (line ~206):
`proven = (segment, timeframe, era) in _PROVEN_INTRADAY_SCOPES` — a strict membership
test, no partial/fuzzy match, no timeframe-only fallback (that fallback was itself
removed in 67.5 per the module's own docstring, precisely to close this kind of gap).

**Answer to Part 1.2**: if tomorrow's capture runs at `--timeframe 1m`, the resulting
`HistoricalBar` rows will resolve `semantics = UNKNOWN`, `canonicalization_permitted
= False`, `proof_status = UNPROVEN` (line 213-215), get stamped
`canonicalization_state = UNCANONICALIZED` (never `CANONICALIZED` — only rows in a
proven scope can reach that state), and will therefore be **REJECTED** by
`ResearchDataGateService` (`research_data_gate.py` line 259,
`is_canonicalized(provenanced_bar.canonicalization_state)` returns `False` for
`UNCANONICALIZED`, driving `ResearchRejectionReason.UNCANONICALIZED_TIMESTAMP`).
The capture will run fine operationally and be entirely unusable for research —
exactly the failure mode the directive describes.

## B. How `(NSE_EQ, FIVE_MINUTE, CAS_ERA)` was proven — the standard [F][D]

The only record of the original proof left in the repository is in comments/docstrings
(the actual verification script or notebook, if one ever existed as a standalone
artifact, is not present anywhere in the tree — `git log --all`, `find`, and repo-wide
grep for "proof"/"interior-bucket"/"67.0" turned up no such script; only prose
descriptions survive in code comments and one migration docstring). Quoting the two
independent places that describe it consistently:

`historical_provider.py` lines 55-58:
> "Dhan's `/v2/charts/intraday` raw candle timestamp is OPEN-of-interval - PROVEN in
> Checkpoint 67.0 for 5m (15/15 interior-bucket OPEN matches, 0/15 CLOSE matches,
> request-boundary confounding explicitly ruled out)."

Migration `0040_historicalbar_split_semantics_from_state.py` lines 23-24:
> "This is the ONLY scope 67.0 empirically proved (RELIANCE, 2026-08-17, 5m, 15/15
> interior-bucket match) — 10,266 rows."

**The standard, as documented** — every element of which a future 1m proof would need
to independently satisfy:

1. **A specific, named instrument and date**: RELIANCE, NSE_EQ, 2026-08-17 (not a
   synthetic or averaged sample — one real, identifiable capture).
2. **A specific timeframe/era pair**: 5-minute, CAS-era (post `CAS_EFFECTIVE_DATE`
   2026-08-03) — the proof is scoped exactly to what was tested, nothing broader.
3. **15 candles sampled, and specifically the "interior" ones** — i.e. bars away from
   the edges of the fetch-request window — with **"request-boundary confounding
   explicitly ruled out"** as a named, deliberate control. This implies the original
   authors recognized that a candle sitting at the very start/end of a requested
   window is ambiguous (its timestamp could be shaped by where the request window
   was cut, not by Dhan's true interval-labeling convention), and excluded those
   edge candles from the sample for that reason.
4. **A binary, falsifiable outcome reported per-candle**: for each of the 15 sampled
   candles, the timestamp was checked against two competing hypotheses — "OPEN of the
   bucket" vs "CLOSE of the bucket" — against some ground truth for where the bucket
   boundary actually falls. The result was unanimous: 15/15 matched OPEN, 0/15
   matched CLOSE. A mixed result would not have cleared this bar.
5. **A full day (or at least enough of the session to have genuine interior candles
   away from both edges)** — the language "interior-bucket" only makes sense if the
   captured window was wide enough that some candles were unambiguously not at either
   edge.

What is **not** preserved in the repo is the literal ground-truth mechanism used to
independently determine "where does this bucket actually start/end" — that
comparison logic itself. Only the conclusion and the control (interior sampling,
boundary-confounding ruled out) survive as documentation. This checkpoint reports
that honestly rather than guessing at a mechanism that cannot be verified from what
remains in the tree.

## C. Attempt against the existing 880 ONE_MINUTE rows, and its result [F]

Queried the actual `HistoricalBar` table directly (read-only, no Dhan call):

```
provenance=REAL_DHAN, timeframe=1m: 880 rows total
  NSE:TCS       220 rows
  NSE:HDFCBANK  220 rows
  NSE:RELIANCE  220 rows
  NSE:INFY      220 rows
canonicalization_state: 100% UNCANONICALIZED (confirms Part 1 finding independently)
```

Per-instrument date/time span (identical structure for all four — shown for
RELIANCE, verified matching for TCS/HDFCBANK/INFY):

```
2026-08-24   44 bars   03:46 UTC (09:16 IST) -> 04:29 UTC (10:09 IST)
2026-08-25   44 bars   03:46 UTC (09:16 IST) -> 04:29 UTC (10:09 IST)
2026-08-26   44 bars   03:46 UTC (09:16 IST) -> 04:29 UTC (10:09 IST)
2026-08-27   44 bars   03:46 UTC (09:16 IST) -> 04:29 UTC (10:09 IST)
2026-08-28   44 bars   03:46 UTC (09:16 IST) -> 04:29 UTC (10:09 IST)
```

**Applying Part B's standard to this data:**

- All 5 dates (2026-08-24 through 2026-08-28) are after `CAS_EFFECTIVE_DATE`
  (2026-08-03) — so era classification is unambiguous (CAS_ERA, no `MIXED_UNRESOLVED`
  straddling problem). This part is fine.
- But the captured window per day is only ~44 minutes (09:16-10:09 IST), a narrow
  slice near market open. NSE cash-equity intraday sessions run 09:15-15:30 IST
  (~375 minutes). This data **never reaches session close**, and the first bar
  (09:16 IST) is itself one minute after the documented session open (09:15 IST) —
  meaning even the "start" of this window is not a clean, independently-known anchor
  (it's ambiguous whether it reflects OPEN-labeling with the very first 09:15-09:16
  candle simply missing from the capture, or something else).
- Every single bar in this 880-row set is therefore at or near an edge of its own
  capture window — there is no interior stretch of the session (e.g. mid-morning bars
  far from both the request's start and any known session boundary) that mirrors what
  67.0 called "interior-bucket" sampling with boundary-confounding ruled out. The
  entire captured span is short enough that "interior vs boundary" is not a
  meaningful distinction here — nearly every bar is within a few minutes of an edge.
- No session-boundary anchor (session close, 15:30 IST) is present anywhere in this
  data to test against, and this checkpoint has no independent corroborating source
  (e.g. reference tick/quote data with known trade timestamps) to substitute for one.

**Result: `INSUFFICIENT_EVIDENCE`.** This is not a borderline call — the existing
880 rows are structurally the wrong shape for this proof, independent of any
reasoning about the actual timestamp values: too narrow a daily window, no
session-boundary anchor, no interior/edge distinction possible, and no second data
source to corroborate against. No attempt was made to force a conclusion from this
data; doing so would risk exactly the "scope leakage" 67.5's fix was written to
prevent.

**What would be needed** for a genuine attempt: a full-session (09:15-15:30 IST)
1-minute capture for at least one instrument on at least one CAS-era date, wide
enough to draw an interior sample of 15+ candles safely away from both the session
open and session close, plus whatever the original 67.0 ground-truth mechanism was
(not currently reconstructable from this repo) or an equivalent independently
verifiable reference for where Dhan's 1-minute buckets truly start/end.

## D. Practical recommendation for tomorrow

**This is a recommendation only — the operator decides, and 67.12.2-H's command is
not being modified here.**

Recommendation: **capture `5m` as the priority** (already proven CAS_ERA/NSE_EQ,
immediately research-eligible and usable for backtesting today), and if `1m` capture
is still wanted operationally (e.g. to keep building the dataset that a future
dedicated 1m-proving checkpoint would need — including a **full-session** capture,
per Part C's "what would be needed"), run it **with the explicit, documented
understanding that those rows will be captured as `UNCANONICALIZED`/`UNKNOWN` and
will NOT pass the research gate** until a dedicated future checkpoint formally proves
`ONE_MINUTE` the way 67.0 proved `FIVE_MINUTE`. That is `CAPTURE_BOTH_WITH_CAVEAT` in
the taxonomy above — offered as the most defensible middle ground, but the choice
between `SWITCH_TO_5M` and `CAPTURE_BOTH_WITH_CAVEAT` (or running `1m` alone knowing
it will be rejected, if the point of tomorrow's run is specifically to gather a
full-session 1m sample for the future proof) is the operator's, not this
checkpoint's, to make.

What should **not** happen: running `--timeframe 1m` as the *sole* capture tomorrow
under the belief (per 65.13/67.12.2-H's original framing) that it will be
research-eligible. As things stand, it will not be — confirmed in Part A/C above.

## E. Scoped design for a dedicated future "prove ONE_MINUTE canonicalization" checkpoint

Not applicable in the form Part 5 anticipates (`CONFIRMED_CANONICAL` was not reached
— Part C returned `INSUFFICIENT_EVIDENCE`), but per the directive's spirit ("if
applicable"), here is what such a checkpoint should be structured to do, so it is not
designed from scratch later. This is a recommendation for a **separate, dedicated,
separately-reviewed checkpoint** — nothing here is applied to
`_PROVEN_INTRADAY_SCOPES`, `provenance.py`, or any timestamp-semantics code in this
checkpoint.

1. **Capture**: a genuine full-session (09:15-15:30 IST) `--timeframe 1m` capture for
   at least one NSE_EQ instrument, on at least one date strictly after
   `CAS_EFFECTIVE_DATE` (2026-08-03) — mirroring 67.0's own choice of a single,
   specific, named instrument/date rather than an aggregate/multi-instrument sample.
2. **Sampling discipline**: draw the evidence sample from **interior** candles only —
   away from both the request-window edges and the session open/close — exactly
   mirroring 67.0's "interior-bucket" control, with the reasoning for which candles
   were excluded stated explicitly (not just asserted).
3. **Adversarial tests to include**, mirroring what 67.0 evidently controlled for:
   - Explicit request-boundary confounding check: show the same OPEN/CLOSE
     classification result holds regardless of where the fetch request window was
     cut (e.g. by re-running the classification against two different request
     windows covering the same interior candles).
   - Session-boundary alignment check: verify the first and last candle timestamps
     of a full-session capture are consistent with one labeling convention and not
     the other (first candle = 09:15 under OPEN-labeling vs 09:16 under
     CLOSE-labeling; last candle = 15:29 under OPEN-labeling vs 15:30 under
     CLOSE-labeling for a 1-minute interval) — an anchor Part C found this
     checkpoint's data structurally could not provide.
   - Cross-timeframe consistency check: since 5m is already proven OPEN for the same
     (NSE_EQ, CAS_ERA) scope, verify that aggregating 1m candles into 5m buckets
     under the OPEN hypothesis reproduces the already-proven 5m OHLC series for the
     same instrument/date (a second, independent corroborating check beyond the raw
     1m timestamps themselves) — something Part C also could not attempt because the
     existing 1m capture window doesn't overlap enough proven 5m data at 1m
     granularity across a full session.
   - Report the binary per-candle OPEN/CLOSE match count exactly as 67.0 did
     (N/N matches, not an aggregate or averaged statistic), and require a unanimous
     result before any scope-list change is proposed.
4. **Explicit non-goals**: this future checkpoint should scope its claim exactly as
   67.0 did — proving 1m for one instrument/date/era combination does NOT
   automatically extend to BSE_EQ, to PRE_CAS 1m data, or to any other exchange
   segment, mirroring the segment-scoping discipline already built into
   `DhanTimestampProofScope`.
5. **Explicit prohibition carried forward**: like this checkpoint, that one must not
   itself edit `_PROVEN_INTRADAY_SCOPES` inline as part of "discovering" the proof —
   it should present the evidence and let a distinct, reviewed decision add the new
   scope tuple, keeping proof-gathering and allowlist-modification as separate,
   auditable steps.
