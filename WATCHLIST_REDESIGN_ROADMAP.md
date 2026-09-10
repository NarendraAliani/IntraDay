# Watchlist Page Redesign — Recon + Roadmap

Status: **read-only investigation, deliberately uncommitted** (same
convention as `GAINZ_ROADMAP.md`/`SCANNER_BUILDER_ROADMAP.md`/etc.). No
code was written or modified to produce this document.

**Already decided, not revisited here**: no fundamentals (PE, market
cap, dividend yield, earnings date), no news feed, no holdings/
dividends/forecasts tabs, no L2/order-book grid — none of this data
exists in this project. Price/change%/volume columns, a sparkline, and
reusing `CHECKPOINT-SCANNER-B`'s own Historical/Live mode pattern are
already decided as in-scope.

## Part 1 — Inspection findings

### 1. What the current `Watchlists` page actually does

`[F]` Read `WatchlistPage.tsx` and `watchlist_views.py` in full —
confirmed exactly the prior finding, nothing more: a plain named
instrument list. `POST /watchlists/save/` (name + instrument_ids),
`GET /watchlists/` (list, per-owner), `DELETE /watchlists/<name>/`.
`WatchlistService`/`DjangoWatchlistRepository` store only
`(owner, name, instrument_ids[])` — **no price field, no market-data
join, no price fetch anywhere in this code path.** The page itself
renders each watchlist as `<strong>{name}</strong>: {instrument_ids.join(", ")}`
— literally a comma-separated symbol list with a Delete button. This
matches the operator's own description precisely, confirmed by reading
the code, not assumed from the description alone.

### 2. Existing data sources for a "live-ish" view

`[F]` **`GET /market-data/quotes/` (`current_quotes` view) already
exists and is already used elsewhere** (the instrument picker's own
`useInstrumentUniverse` hook calls it) — `QuoteResponseSerializer`:
`symbol`, `exchange`, `last_price`, `source_timestamp`,
`freshness_age_seconds`, `is_stale`. This reads the latest
`LiveQuoteObservation` tick — real-time, but **only populated while a
live worker is running**, and **carries no change% and no volume**.

`[F]` **`AggregatedBarObservation`** (the same live-session bar table
`SCANNER_BUILDER_ROADMAP.md` found for the screener's own Live mode)
DOES carry `volume` on its underlying model — confirmed directly — but
the existing `BarResponseSerializer` does not currently expose it
(`symbol`/`exchange`/`timeframe`/`interval_start`/`interval_end`/
`open`/`high`/`low`/`close`/`status`/`observation_count`/`data_source`
only). A watchlist's own volume column would need this serializer
extended, or a new one — a small, honest addition (the data already
exists in the row), not a new data source.

`[F]` **No existing endpoint returns price+change%+volume together for
a SET of instruments in one call.** This confirms: a new, thin
read-only endpoint is needed, reusing existing repositories exactly as
`CHECKPOINT-SCANNER-B`'s own `coverage_preview_view`/
`evaluate_screening_rule_view` precedent already established — not a
new data-access pattern, the same one, applied to a simpler read.

`[F]` **change% has no existing computation anywhere** (checked — no
"previous close" concept exists in any current serializer/view). It
would need: latest close vs. the prior trading day's own closing
`HistoricalBar` (or, in Live mode, latest tick vs. that same prior-day
close — there is no "today's own session open" baseline currently
computed either, so prior-close-relative is the only honestly
available convention without inventing a new one).

### 3. Sparkline / charting

`[F]` **No charting library dependency exists in this frontend at
all** (`recharts`/`d3`/anything — zero matches in `package.json`).
`common/components/EquityChart.tsx` (Checkpoint 27) is a hand-rolled,
inline-SVG line chart, explicitly built this way on the stated
principle "do not introduce a huge charting framework without
justification." **A sparkline is a strictly simpler version of the
exact same `buildPath()` idiom** (single series, no axes, no labels,
tiny viewBox) — directly reusable as a new, small, sibling component
(e.g. `Sparkline.tsx`) built the same way, not a new dependency.

### 4. Can the Screener's Historical/Live split be reused directly?

`[F]` **Mostly yes, with one genuine difference worth naming
honestly.** `CHECKPOINT-SCANNER-B`'s own gate pattern
(`ResearchDataGateService` for Historical mode's data-trustworthiness
check) reuses directly — a watchlist's own Historical-mode price
should be equally honest about coverage/canonicalization, not a raw
unchecked `HistoricalBar` read.

The genuine difference: **the Screener was deliberately scoped
Historical-mode-ONLY for its own Phase B** (Live mode explicitly
deferred to a future phase). A watchlist is different in kind — it is
the page an operator glances at CASUALLY, often with no live session
running at all, and it should never show an empty/broken page in that
ordinary case. So a watchlist's own default experience should be:
**Historical mode is the always-available baseline** (last
gate-verified close, clearly dated/labeled), and **Live mode is an
enhancement, offered only when it's actually available** — checked via
a LIGHTWEIGHT, read-only `WorkerRuntimeStatus.worker_state == "RUNNING"`
read (not the full `evaluate_live_paper_readiness()` gate the Live
Paper Operations Console uses, which also considers the kill switch
and session status — irrelevant to a read-only price display that
never starts or stops anything). This is a real, small design decision
this recon makes explicitly, not glossed over: watchlist reuses the
SAME two-mode labeling convention and the SAME honest-data-source
discipline, but its own mode-availability CHECK is simpler and its
own DEFAULT (unlike the Screener's) must work with zero live
infrastructure running.

## Part 2 — Roadmap

### 1. Field/column recommendation

Honest, supportable-today columns only:

- **Symbol** (existing, unchanged — the watchlist's own saved
  instrument_ids).
- **Last price** — `current_quotes` (Live) or the latest gate-verified
  `HistoricalBar` close (Historical).
- **Change %** — `(last price − prior trading day's close) / prior
  close`, computed from `HistoricalBar` for the prior day regardless
  of mode (the only honestly-available baseline, per Part 1 finding
  2) — labeled "vs. previous close," never implied to be "today's
  session change" when no live session exists.
- **Volume** — from `AggregatedBarObservation` (Live, needs the
  serializer extended) or the latest `HistoricalBar` day's own summed/
  last-bar volume (Historical) — labeled honestly as session-to-date
  in Live mode, or the historical day's own total in Historical mode;
  never presented as if they were the same measurement.
- **Sparkline** — a small inline-SVG line over the last N gate-verified
  `HistoricalBar` closes for that symbol (recommend a session-count
  basis, e.g. "last 5 trading days," rather than a literal "7-day"
  label, since this project's own trading calendar has weekends/
  holidays — a literal 7-day window would silently include non-trading
  days with no data). Historical data only, even in Live mode — a
  sparkline showing live intraday movement is a genuinely separate,
  larger feature (an actual intraday chart) and is explicitly NOT
  recommended for this pass.
- **As-of / freshness label** — reusing the existing
  `freshness_age_seconds`/`is_stale` convention `current_quotes`
  already carries in Live mode; in Historical mode, the gate-verified
  trading date itself (e.g. "as of 2026-09-09 close").
- **Explicitly NOT recommended, even though "genuinely supportable"
  in a narrow technical sense**: high/low/open columns. Nothing in the
  reference screenshots' own "attractive and useful" framing asked for
  a full OHLC grid, and adding one risks recreating the "dense
  order-book" clutter the operator's own exclusions already reject in
  spirit. Keep the row scannable.

### 2. Architecture boundary — no new service needed

**Reasoned through, not assumed**: `AdhocScreeningService` exists to
evaluate operator-authored CONDITIONS (field, operator, comparison)
combined via AND/OR against a universe — genuine decision logic. A
watchlist row's own data need is categorically simpler: "fetch the
latest N bars and the latest quote for these M symbols, format them."
There is no condition to evaluate, no combinator, no match/no-match
verdict. **This does not need a new domain service** — a new, thin
view function (`watchlist_market_data_views.py` or an extension of
the existing `watchlist_views.py`) can compose
`DjangoHistoricalBarRepository`/`DjangoAggregatedBarRepository`/
`ResearchDataGateService`/`WorkerRuntimeStatus` directly, exactly the
same "view composes existing repositories, no intermediate service"
shape `coverage_preview_view` already uses successfully. Introducing
an `AdhocWatchlistService` purely to mirror the screener's own
structure would be exactly the kind of unjustified-by-actual-need
abstraction this project's own established discipline (and this
recon's own Part 2 item 2 instruction) warns against.

### 3. Phased build sequence

- **Phase A — backend, read-only, no UI.** One new, thin endpoint
  (e.g. `GET /watchlists/<name>/market-data/`, or a query-param
  variant of the existing `GET /watchlists/<name>/`) that resolves
  each saved instrument's price/change%/volume/sparkline-series for
  BOTH modes, honestly labeled per-instrument exactly like
  `ScreeningInstrumentResult`'s own `NOT_GATE_VERIFIED` precedent (an
  instrument whose Historical data isn't gate-verified reports that
  plainly, never a fabricated or silently-stale price). Fully unit-
  tested against real Postgres fixtures, zero UI change.
- **Phase B — minimal UI.** Extend the existing `WatchlistPage.tsx`
  table (replacing the current comma-separated string) with the new
  columns, a `Sparkline.tsx` component (new, small, inline-SVG,
  following `EquityChart.tsx`'s own established idiom), and a mode
  badge reusing the exact `"Historical mode"` / (a new) `"Live mode"`
  label pattern `ScreenerPage.tsx` established — visually and textually
  consistent across both pages, not a new visual language.
- **Phase C (optional) — auto-refresh while Live mode is active.** A
  polling interval (matching the cadence other live-facing pages
  already use, e.g. the scan-progress poll) ONLY while
  `WorkerRuntimeStatus.worker_state == "RUNNING"` — explicitly NOT
  built in Phase A/B, since it adds real complexity (cleanup on
  unmount, interval management) for a feature whose core value
  (seeing current price/change/volume at a glance) is already
  delivered by A/B's own one-shot load-on-page-visit behavior.
- **Explicitly out of scope, indefinitely**: everything the operator's
  own context already excluded (fundamentals, news, holdings/
  dividends/forecasts, L2/order-book), plus a live intraday sparkline
  (a distinct, larger charting feature, not this redesign's job) and
  any alert/notification-on-price-move mechanism (would start
  resembling automated signal generation, the exact boundary
  `SCANNER_BUILDER_ROADMAP.md` was careful to draw around the
  screener too).

### 4. Honest complications

- **The same live-data-availability constraint applies, with a
  different consequence than the Screener's.** No standing market-data
  service exists in this project — `AggregatedBarObservation` is only
  ever populated while an operator has manually launched a worker.
  Unlike the Screener (which simply doesn't offer Live mode yet), a
  watchlist that a trader might open at any moment, including when
  nothing is running, **must have a working, non-broken DEFAULT
  experience with zero live infrastructure active.** This roadmap's
  own recommendation: Historical mode (last gate-verified close) is
  the default and always-available state; Live mode is additive,
  offered only when the lightweight `WorkerRuntimeStatus` check
  confirms a worker is genuinely running — confirmed explicitly, not
  left as an unstated assumption.
- **Historical mode inherits this project's own current,
  real, actively-changing data-completeness picture** — as of the most
  recent migration checkpoints this session, gate-verified coverage
  per symbol is a moving, currently-partial number, not "every day
  always available." A watchlist row for a symbol/day that isn't
  gate-verified must say so plainly (reusing the same
  `NOT_GATE_VERIFIED`-style honesty the Screener already established),
  never silently show a stale or wrong price.
- **change% and volume both need one clarified convention each**
  before Phase A is built (not fully resolved by this recon, flagged
  honestly for that phase's own first step): change% "vs. previous
  close" is unambiguous once stated, but volume needs an explicit
  decision between "session-to-date running total" (Live) vs. "full
  historical day total" (Historical) being clearly two different
  measurements, not silently conflated — this recon recommends
  labeling each explicitly rather than picking one convention to hide
  the difference.
- **This is a smaller, lower-risk lift than the Screener was** — it
  reuses more (no new domain service, no new condition/rule concept),
  and the "Phase A backend, read-only" step alone would already make
  the existing page meaningfully more useful (even before any UI
  change) once wired to the current one via Phase B. Reasonable to
  prioritize ahead of Screener's own Phase C (Live mode) if the
  operator wants a visible win sooner, since it needs no new
  architecture decision the way Screener's Live mode still does.
