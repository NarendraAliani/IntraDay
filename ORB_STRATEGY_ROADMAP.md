# Opening Range Breakout (ORB) Strategy — Phased Roadmap (Recon)

Read-only investigation. No production code written or modified this
checkpoint. `gainz_compatible_research.py` (paused) and
`vwap_mean_reversion.py` (Phase D complete, also paused for tuning)
were not touched.

## 0. Headline finding: no ORB feature exists; the session-reset pattern IS reusable, but ORB genuinely needs one more real piece VWAP never needed — a session's own `market_open` instant, already available from an existing function, not a new one

`[F]` No opening-range/ORB feature exists anywhere in `signal_
intelligence.feature_engine` — confirmed directly, not assumed:
directory listing shows no `orb.py`/`opening_range.py`, and
`rolling_breakout.py` — the one existing feature with "breakout" in
its name — is confirmed, by directly re-reading its own formula
(`prior_high_t = max(high_(t-N)..high_(t-1))`, a fixed TRAILING
N-bar lookback with no session concept at all), to be a genuinely
different computation shape from what ORB needs. **This distinction
is real, not a naming coincidence to gloss over**: `rolling_breakout`
re-evaluates its own N-bar window fresh at every bar, forever, all
session long; ORB needs exactly ONE fixed window, anchored to the
first N minutes of each trading day specifically, never re-evaluated
after that window closes.

**The honest answer to Part 1.2, stated precisely**: `CHECKPOINT-VWAP-A`'s
own session-reset pattern (`bar.timestamp.date()` grouping, no `Bar`-
level session marker) is necessary but NOT sufficient for ORB. VWAP
never needed to know WHEN within a day a bar falls — only WHICH day,
so it could reset its accumulator. ORB genuinely does need intra-day
clock position (bars 1-3 of a session's 5m sequence are structurally
different from every bar afterward). **This is a real, additional
requirement — not glossed over.** But it does NOT require any NEW
logic in `domain/session/calendar.py`/`resolver.py` — those modules
were re-checked directly (both files' full function lists) and
neither exposes a dedicated "minutes since session open" primitive,
but **`TradingSession.market_open` already IS the exact fact needed**:
`build_session_for(session_date, as_of)` (already used by `walk_
forward.py`, `historical_data_coverage.py`, and others this session)
returns a `TradingSession` whose `market_open` field is a real,
already-UTC-converted instant for that exact calendar date — IST
09:15 correctly converted, no new conversion logic to write. ORB's
"is this bar within the opening window" test reduces to pure
timestamp arithmetic against an already-resolved value:
`bar.timestamp <= session.market_open + window_duration`. One extra
step beyond VWAP's own pattern (resolving `market_open` once per
distinct date the same way `ResearchEligibleBars.sessions_by_date`
already resolves session shape once per date, per that type's own
established precedent) — but the underlying resolver function itself
is not new.

**One simplifying fact confirmed directly**: `TradingSession.market_open`
is a pure calendar fact for the date (09:15 IST), unaffected by the
CATEGORY_I_CAS/CATEGORY_II_NON_CAS distinction that only matters for
the CLOSE side (15:15 vs 15:30 IST) — ORB's opening-window logic needs
no category-awareness at all, unlike anything that touches session
*end*.

## 1. ORB-specific inspection (Part 1)

### 1.1 — No existing ORB feature (confirmed above)

### 1.2 — Session-reset pattern reusable, PLUS a real, additional piece — both confirmed directly, neither invented nor glossed over

Covered above. Summary: `bar.timestamp.date()` grouping (VWAP's
pattern) handles "which session"; `TradingSession.market_open`
(an EXISTING function's EXISTING field, `build_session_for()`) handles
"where in that session" — together, sufficient, no new
resolver-level logic needed in `domain/session/`.

### 1.3 — First-15-minutes window = exactly 3 bars of `5m`

`[F]` Confirmed via this project's own established `Bar.timestamp`
convention (CLOSE-time, re-confirmed `GAINZ_ROADMAP.md` §1.6 and
`VWAP_STRATEGY_ROADMAP.md` §1.3, not re-derived): the opening window
`09:15`–`09:30` IST, on a `5m` grain with close-anchored timestamps,
covers exactly **3 bars**: close `09:20` IST (the `09:15`–`09:20`
candle), close `09:25` IST, close `09:30` IST. The window's own high/low
is therefore `max(high)`/`min(low)` across those 3 bars, and the
feature has NO output for those first 3 bars themselves (the range
isn't complete yet) — the first possible signal-relevant bar is the
4th, `09:35` IST close, exactly mirroring `rolling_breakout.py`'s own
"no output until the window is genuinely complete" warm-up
convention, applied here to a session-relative window instead of a
trailing one.

## 2. Design summary — deliberately small, matching VWAP's own discipline

**Entry (breakout, not reversion)**: BUY when `close > opening_range_
high` (price closes above the first-N-minute range); SELL when
`close < opening_range_low`.

**Exit — single target only, explicitly avoiding the Gainz/`atr_
volatility_breakout` T2/T3-unreachable mistake a second time**:
`target = entry + target_range_multiplier × range_size` (where
`range_size = opening_range_high - opening_range_low`); `stop = the
OPPOSITE side of the range itself` (a BULLISH breakout's stop is
`opening_range_low`, not an independently-chosen ATR multiple) — or,
as a configurable alternative, a tighter fraction of the range
(`stop = entry - stop_range_fraction × range_size`). Using the range's
own opposite boundary as the natural stop (rather than a fixed ATR
multiple invented independently, Gainz's own mistake) means stop
distance is inherently proportional to how wide the actual opening
range was that day — a real, structural difference from both Gainz's
and even VWAP's stop design.

**Parameters (4, matching VWAP's own "genuinely small" precedent)**:
1. `opening_range_minutes` — window duration, default `15`.
2. `target_range_multiplier` — target distance as a multiple of the
   range's own size, default e.g. `1.0` (target = one range-width
   beyond entry).
3. `stop_range_fraction` — stop distance as a fraction of the range
   (`1.0` = the opposite boundary itself; `<1.0` = a tighter stop
   inside the range).
4. `atr_lookback` — **not required for entry/target/stop math at
   all** (unlike Gainz/VWAP, ORB's own target/stop are defined
   entirely in terms of the range's own size, no ATR dependency) —
   listed here only as an open design question for Phase B to decide
   (§3 below), not assumed necessary.

## 3. Does this design share VWAP's or Gainz's exit-mechanism characteristics, or neither? — reasoned explicitly, not assumed

**Neither, by construction — a genuinely different exit-distance
scale than both prior strategies, reasoned through directly:**

- **Gainz's problem** (`CHECKPOINT_73`/`75`): SL/T1 chosen as
  INDEPENDENTLY-picked ATR multiples, with T2/T3 further multiples
  beyond that — MFE analysis showed price rarely travels far enough to
  reach the outer rungs, regardless of exit-ordering mechanism.
- **VWAP's structure** (which avoided that specific trap, per its own
  roadmap's §3 reasoning, though still never validated profitable):
  target distance scales with the SAME distance the entry condition
  already proved price could travel (back to VWAP, from wherever the
  N×ATR entry deviation put it).
- **ORB's structure is different again**: target and stop are BOTH
  defined directly in terms of the range's OWN size — a quantity
  determined entirely by the market's own realized volatility in the
  first N minutes of THAT SPECIFIC DAY, not a fixed ATR multiple
  chosen in advance at all. A wide opening range on a volatile day
  produces proportionally wide targets/stops that day; a narrow range
  on a calm day produces proportionally tight ones. This is a
  genuinely self-scaling design, not shared with either prior
  strategy's own mechanism — **reasoned expectation only, not yet
  tested**: whether this self-scaling property actually produces a
  more reachable target in practice is an empirical question for
  Phase B/D to answer, explicitly not assumed here just because the
  mechanism is different.

**Applying `CHECKPOINT_75`'s lesson explicitly, from the start**: Phase
B (below) will compute and report the MFE/MAE distribution as part of
its OWN first walk-forward look, the same discipline
`VWAP_STRATEGY_ROADMAP.md` already established and `CHECKPOINT-VWAP-B`
already followed — not deferred to a later diagnostic checkpoint the
way Gainz's own MFE analysis was.

## 4. Phased build sequence

**Phase A — the opening-range feature itself**. New module,
`signal_intelligence/feature_engine/opening_range.py`,
`compute_opening_range(definition, bars) -> tuple[FeatureValue, ...]`
(matching the `Definition`-object dispatch shape `CHECKPOINT-VWAP-A`
chose over `candle_body_ratio.py`'s alternative, since this checkpoint
takes one real parameter — `opening_range_minutes` — unlike VWAP's own
zero-parameter case, so the parameterized `RollingBreakoutDefinition`-
style shape is the more directly applicable existing precedent this
time, not VWAP's own zero-field special case).

Computation: per trading day (grouped via `bar.timestamp.date()`,
VWAP's proven pattern), resolve that date's `TradingSession.market_open`
via `build_session_for()` (§1.2's confirmed, sufficient mechanism);
accumulate running high/low across bars whose `timestamp <= market_open
+ opening_range_minutes`; once that window closes, EVERY subsequent
bar in the same session emits the SAME frozen `(range_high, range_low)`
pair as its feature value — a single fixed fact per day, not a moving
window. No output for the first 3 bars themselves (per §1.3's warm-up
finding) or for any day whose bars don't yet cover a complete window
(e.g. a partial/incomplete real-time session). Representation choice
to decide in Phase A itself (not pre-judged here): a single feature
emitting a composite value, or two parallel fields
(`opening_range_high`/`opening_range_low`) — `price_delta.py`'s
"smallest canonical representation" precedent argues for the fewest
fields that lose no information; since high and low are two genuinely
independent numbers (unlike `rolling_breakout`'s mutually-exclusive
breakout/breakdown case), two parallel fields is the more likely
correct choice, to be confirmed when Phase A is actually built. Wired
into `field_registry.py` AND `compute_feature_series()`'s dispatch,
both required (per `CHECKPOINT-GAINZ-A`'s own documented finding, cited
again by `CHECKPOINT-VWAP-A`, cited a third time here).

**Phase B — the strategy itself**. New file,
`trading_engine/strategy_execution/strategies/orb_breakout.py` (name
to be finalized in that checkpoint), single profile, `build_trade_plan()`
producing a SINGLE target (per §2/§3's own design, no T2/T3 ladder).
Computes and reports its own MFE/MAE distribution on its first real
backtest run, per §3's explicit instruction, not deferred.
`registry.py` NOT touched.

**Phase C — 2-3 config presets**, varying `opening_range_minutes`
and/or `target_range_multiplier` (e.g. a tight/classic/wide window
family, or a conservative/aggressive target-multiple family) — exact
shape decided in that checkpoint, following the same real-behavioral-
divergence proof discipline `CHECKPOINT-GAINZ-C`/`CHECKPOINT-VWAP-C`
both already established.

**Phase D — walk-forward validation, mandatory gate**. Same discipline
as every other strategy: `run_walk_forward_backtest()` direct,
`min_oos_days=3, min_folds=3`, through the REAL `ResearchDataGateService`,
against the current real gate-verified dataset (17 real trading days as
of `2026-09-08`, `CHECKPOINT-VWAP-D`'s own last-checked figure — Phase D
of THIS thread should re-check the actual current count directly
rather than assume it hasn't grown, per every prior Phase D's own
discipline). No `RESEARCH_ACTIVE` status change.

## 5. Most important honest complications

1. **The intra-day clock-position requirement is real** (§1.2) — not a
   blocker (an existing function, `build_session_for()`, already
   supplies exactly the fact needed), but Phase A is not a pure
   copy-paste of `vwap.py`'s own accumulator shape; it needs its own
   per-date `market_open` resolution step VWAP never required.
2. **The self-scaling target/stop design is a reasoned expectation,
   not a proven advantage** (§3) — Phase B/D must report honestly if
   ORB's own MFE distribution does or does not actually show a
   different, more favorable shape than VWAP's or Gainz's; the
   mechanism being different from both prior strategies' own designs
   is not, by itself, evidence it produces a better result.
3. **A breakout hypothesis is a third, genuinely different market
   assumption** from both existing trend-following strategies (`ema_
   crossover`/`sma_trend_filter`/`atr_volatility_breakout`, all
   trend-following) and VWAP's own mean-reversion hypothesis — Phase
   D's result should be read on its own terms, the same caution
   `VWAP_STRATEGY_ROADMAP.md` §5 already gave for comparing VWAP
   against the trend strategies.
4. **`atr_lookback` is listed as an open question, not a settled
   parameter** (§2) — ORB's core entry/target/stop math needs no ATR
   at all (unlike Gainz/`atr_volatility_breakout`), so Phase B should
   explicitly decide whether ATR earns a place in this design (e.g. as
   an additional filter) or is left out entirely, rather than
   including it by inertia because every other strategy this session
   has used it.
