# VWAP Mean-Reversion Strategy — Phased Roadmap (Recon)

Read-only investigation. No production code written or modified this
checkpoint. `gainz_compatible_research.py` was not touched (it is
paused per `CHECKPOINT_75`'s explicit resumption criterion).

## 0. Headline finding: no VWAP feature exists; session-anchoring needs a genuinely new computation shape, but the tools to build it already exist elsewhere in the codebase

`[F]` No VWAP feature exists anywhere in `signal_intelligence.
feature_engine` — confirmed directly (not assumed from the name),
three search shapes: (1) `grep -rli vwap` across the feature-engine
directory returns only `field_registry.py`, and only because that
file's own header COMMENT explicitly documents VWAP's absence
("No RSI/VWAP/MACD/Bollinger/Supertrend entry is fabricated —
Checkpoint 26 Part 4 explicitly forbids listing indicators that do not
exist"); (2) directory listing of `feature_engine/` shows no
`vwap.py`; (3) no `VWAP`/`VolumeWeighted` class exists in
`definitions.py`. This is a genuinely new feature to build, not a
Gainz-style "check if it secretly already exists" situation.

**The session-anchoring requirement is real and NOT satisfied by any
existing feature-engine pattern** — every current feature
(`relative_volume.py`, `rolling_breakout.py`, etc.) uses a FIXED,
instrument-agnostic trailing lookback (`deque(maxlen=N)`), which has
no concept of "reset at a date boundary" at all. **This is a genuinely
different computation shape, not a parameter tweak to an existing
one** — reported honestly, not minimized. However, the exact tool
needed already exists and is already proven ELSEWHERE in this
codebase (just not yet inside `feature_engine/` itself) — see §1.2.

## 1. VWAP-specific inspection (Part 1)

### 1.1 — No existing VWAP feature (confirmed above)

### 1.2 — Session-reset shape: not a `deque(maxlen=N)` problem, but a proven `bar.timestamp.date()` grouping pattern already exists

`[F]` `domain/session/calendar.py` (`build_session_for`,
`session_for_instant`, `is_trading_day`) and `domain/session/
resolver.py` (`resolve_market_session`, `resolve_market_session_for_
instant`) are both **per-instant/per-date resolvers** — given one
`datetime` or `date`, they answer "what session is this," not
"iterate this `tuple[Bar, ...]` and tell me where each trading day
starts." Neither is a drop-in fit for a feature-engine `compute_*`
function's own signature (`compute_x(definition, bars: tuple[Bar,
...]) -> tuple[FeatureValue, ...]`).

`[F]` **The actual reusable pattern already exists, just not inside
`feature_engine/`**: `research/backtesting/walk_forward.py` already
groups an entire `bars` tuple by trading day, using exactly
`bar.timestamp.date()` (UTC) as the grouping key
(`bars_by_date: dict[date, list[Bar]] = {}`, populated via
`bars_by_date.setdefault(bar.timestamp.date(), []).append(bar)` —
`walk_forward.py:128-130`, and again at `:214-216`). That module's own
header comment (`walk_forward.py:25`) explicitly notes this matches
`Bar.timestamp`'s own UTC/close-time semantics. **This is directly
reusable for VWAP**: iterate `bars` in order, and whenever
`bar.timestamp.date()` differs from the previous bar's date, reset the
running `Σ(price×volume)`/`Σ(volume)` accumulators to zero before
including that bar — a genuinely new "session-reset accumulator"
shape for `feature_engine/`, but built from an already-proven,
already-tested grouping primitive, not an unproven idea.

### 1.3 — `Bar.timestamp.date()` alone is sufficient; no explicit session marker needed

`[F]` Confirmed via `GAINZ_ROADMAP.md`'s own already-established
finding (§1.6, re-verified here, not re-derived): `Bar.timestamp` is
UTC, bar CLOSE time, by explicit design
(`domain/market_data/contracts.py:59-67`: "IST wall-clock conversion
happens only at the presentation boundary, never here"). NSE/BSE cash
equity trading hours (09:15–15:30 IST) map to `03:45`–`10:00` UTC —
**comfortably inside a single UTC calendar date, never crossing UTC
midnight**, for every real trading session this platform handles.
`.date()` grouping in UTC is therefore a reliable, sufficient signal
for "which trading day does this bar belong to" — **no separate
session-boundary marker is needed on `Bar` itself**, and no IST
conversion needs to enter the feature-engine layer at all (consistent
with `GAINZ_ROADMAP.md` §1.6's own "IST is deliberately kept OUT of
this layer" conclusion for the whole `Strategy` interface).

**One inherited discipline, not a new problem**: like every existing
`compute_*` function, a VWAP implementation must still guard against a
mixed-instrument/mixed-timeframe `bars` tuple (the same defensive
check `rolling_breakout.py` already established as this project's own
precedent) — noted here so Phase A doesn't skip it, not because
anything new was found.

## 2. Design summary — deliberately small, 4 parameters

**Direction: mean-reversion.** BUY when `close < session_VWAP - N×ATR`
(price has fallen meaningfully below the session's volume-weighted
average, expecting reversion up); SELL when `close > session_VWAP +
N×ATR` (expecting reversion down).

**Exit**: target = session VWAP itself (or a configurable fraction of
the deviation reverted, e.g. `close_enough_fraction × N×ATR` back
toward VWAP — kept as a SINGLE target, not a 3-rung ladder, deliberately
avoiding the exact structural trap `CHECKPOINT_73`/`75` diagnosed in
Gainz). Stop = a wider multiple of ATR beyond the entry deviation
(`M×ATR` where `M > N`, e.g. `N=1.5, M=2.5`).

**Parameters (4, not more)**:
1. `vwap_deviation_atr_multiplier` (`N`) — entry trigger distance.
2. `stop_loss_atr_multiplier` (`M`, `M > N`) — hard stop beyond entry.
3. `atr_lookback` — the existing, already-proven `atr.py` computation,
   reused verbatim (no new ATR logic).
4. `target_reversion_fraction` (0 < fraction ≤ 1.0) — how much of the
   deviation must revert before exit; `1.0` = "must return all the way
   to VWAP," `<1.0` = a partial-reversion target closer to entry.

No scoring formula, no multi-condition bull/bear tally — a single,
directly falsifiable hypothesis ("price mean-reverts to session VWAP
beyond N×ATR deviation"), matching this checkpoint's own explicit
anti-overfitting framing.

## 3. Does this design naturally avoid Gainz's T2/T3-unreachable problem?

**Likely yes, but for a DIFFERENT and better-grounded reason than "the
target is closer" alone — reasoned through against Part 1's actual
findings, not assumed.**

`CHECKPOINT_75`'s MFE diagnostic found Gainz's problem was NOT
primarily the exit-ordering mechanism — it was that **price genuinely
rarely travels 2×–3× ATR in the favorable direction at all** on this
instrument/timeframe (only 17.6% of Gainz trades reached 2.0× ATR MFE,
1.5% reached 3.0×). A VWAP target is NOT a fixed ATR multiple decided
in advance — **it moves with the actual session VWAP**, which itself
sits somewhere between roughly `0×` and the entry deviation's own
`N×ATR` distance from price at any given moment. Since entry itself
only ever fires once price has ALREADY moved `N×ATR` away from VWAP,
the target distance (back to VWAP) is, by construction, approximately
the SAME order of magnitude as the entry deviation — not a multiple
beyond it. This means the entry condition and the exit target are
built from the SAME distance scale, unlike Gainz's SL/T1 (both ATR
multiples chosen independently of what price had already done) vs.
T2/T3 (further multiples price rarely reaches). **The reasoning holds
up under Part 1's findings**: this design structurally avoids asking
for a price movement LARGER than what historically happens, because
the target is defined relative to where price already proved it can
reach (the VWAP anchor), not as an independently-chosen larger
multiple. This is a genuine architectural difference from Gainz's
ladder, not just a smaller number.

**One honest caveat, not glossed over**: this reasoning assumes VWAP
itself doesn't drift further away during the trade (e.g. a strong
trend day where VWAP keeps moving WITH an adverse move rather than the
position reverting toward it) — this is exactly what the stop
(`M×ATR`, `M > N`) exists to bound, and is a real risk Phase D's
walk-forward validation must actually measure, not an assumption to
carry forward untested.

**Trailing-stop lesson from `CHECKPOINT_75`, applied as a DESIGN
consideration from the start**: `CHECKPOINT_75` found ~17-25% of
losing trades had genuine favorable excursion before reversing —
worth designing for here too, from day one, not patched in later. A
VWAP mean-reversion trade that moves favorably toward VWAP and then
reverses away again is a natural candidate for either (a) a trailing
stop once price crosses some fraction of the way back to VWAP, or (b)
simply noting that since VWAP itself is the target, "price approached
VWAP and reversed" IS visible in the trade's own MFE/MAE data without
needing a separate mechanism — Phase B should compute and report this
explicitly (reusing `SimulatedTrade.mfe`/`.mae`, already free/existing
fields) as part of its own first walk-forward read, not defer it to a
future diagnostic checkpoint the way Gainz did.

## 4. Phased build sequence

**Phase A — the VWAP feature itself** (session-anchored, new
computation shape per §1.2). Single new module,
`signal_intelligence/feature_engine/vwap.py`,
`compute_session_vwap(definition, bars) -> tuple[FeatureValue, ...]`
following the exact existing pattern (frozen `dataclass` definition in
`definitions.py`, mixed-instrument/timeframe guard, Decimal
arithmetic, no-look-ahead — VWAP at bar N uses only bars `0..N` within
that trading day). Wired into `field_registry.py` as a new
`_derived(...)` entry and into `compute_feature_series()`'s dispatch
branch, exactly matching `CHECKPOINT-GAINZ-A`'s own `rolling_breakout`
precedent (registry entry + dispatcher branch, both required — the
dispatcher is an explicit if/elif chain, a registry entry alone is
insufficient, per that checkpoint's own documented finding). Tested in
isolation against hand-computed VWAP values for a small synthetic
session, plus a session-reset test (two consecutive days, confirming
day 2 does not inherit day 1's accumulators) and the mixed-instrument
rejection test every existing feature carries.

**Phase B — the strategy itself**. New file,
`trading_engine/strategy_execution/strategies/vwap_mean_reversion.py`
(or similar), matching the real `Strategy` Protocol exactly
(`parameter_schema()`, `required_features()`, `evaluate()`,
`build_trade_plan()` for the single VWAP target + wider stop), single
profile only (no multi-profile complexity Gainz never needed either).
Computes and reports MFE/MAE distribution on its own first real
backtest run as part of this phase's own test evidence (per §3's
explicit instruction), not deferred. `registry.py` NOT touched —
stays unregistered/unreachable from the live scanner, matching every
strategy-development checkpoint's own established discipline this
session.

**Phase C — 2–3 config presets** (tight/normal/wide deviation bands,
e.g. `N=1.0`/`1.5`/`2.0`), created via the real
`StrategyConfigurationService.save_configuration()` path (never a raw
ORM insert), each preset's gating behavior proven with a real,
hand-computed test case the same way `CHECKPOINT-GAINZ-C` proved its 3
presets actually diverge in `direction`, not just in an attached
evidence number.

**Phase D — walk-forward validation, mandatory gate**. Same
discipline as every other strategy this session:
`run_walk_forward_backtest()` direct call, never `BacktestingService.
run()`, `min_oos_days=3, min_folds=3` for direct comparability,
through the REAL `ResearchDataGateService` (not bypassed). **Explicit
advantage over Gainz's own Phase D**: this strategy can use the
NOW-WORKING, gate-verified real dataset from day one — currently 17
real trading days (16 gate-verified + `2026-09-08`, growing daily via
`CHECKPOINT_72`'s `backfill_daily_coverage` routine) — rather than
inheriting Gainz's history of gate rejections (`LIVE-2`) and
bypass-only results (`68.4`) before the fix landed (`CHECKPOINT_69`).
No `RESEARCH_ACTIVE` status change at this phase either — that remains
the same manual, operator-level decision the roadmap's own Phase D
finding already established for every strategy.

## 5. Most important honest complications

1. **The session-reset computation shape is genuinely new for
   `feature_engine/`** (§1.2) — not a blocker (the grouping primitive
   is already proven in `walk_forward.py`), but Phase A is not a
   copy-paste of `rolling_breakout.py`'s own shape; it needs its own
   design and its own dedicated session-boundary test coverage.
2. **VWAP drift risk during a trending session** (§3's caveat) is real
   and untested until Phase D actually runs — the design reasoning
   that this strategy avoids Gainz's T2/T3 problem is sound given
   Part 1's findings, but it is a reasoned expectation, not yet a
   proven one, and Phase D must report honestly if VWAP itself moves
   too much during typical holding periods to make the target
   reliable.
3. **This is a mean-reversion hypothesis on intraday cash-equity data**
   — a genuinely different market assumption than any of the 4
   existing strategies (all trend/breakout-oriented). Phase D's
   walk-forward result should be read on its own terms, not compared
   directly against `CHECKPOINT_71`'s cross-strategy trend-strategy
   findings as if they were testing the same kind of edge.
