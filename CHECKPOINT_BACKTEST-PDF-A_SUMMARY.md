# CHECKPOINT-BACKTEST-PDF-A — Recon + PDF Report Export (Phase A)

No filename collision — confirmed via `ls` before writing.

## Part 1 — Recon

1. **Confirmed exactly what data already exists**, reading
   `BacktestingWorkbenchPage.tsx`'s own `BacktestResultsPanel` and the
   backend's ONE canonical result shape
   (`research/backtesting/serialization.py::to_json_dict()`, the exact
   dict `GET /backtesting/results/<backtest_id>/` already serves):
   capital/P&L/costs/return% (`initial_capital`, `final_capital`,
   `net_pnl`, `return_percent`, `gross_profit`/`gross_loss` — the
   FRONTEND itself sums `gross_pnl`/`costs` client-side from the trade
   list for its own "Gross P&L"/"Total Costs" tiles, but `gross_profit`/
   `gross_loss` are ALREADY separately pre-computed on `metrics`, so
   this checkpoint's own PDF uses those directly rather than re-summing
   trades), win rate, profit factor, max drawdown (+duration bars),
   Sharpe (trade-level, non-annualized), **and Sortino (trade-level,
   non-annualized) — already fully computed and present on `metrics`,
   confirmed directly, not assumed**, total trades, the mark-to-market
   equity/drawdown curves, the per-trade ledger, the exact Data
   Quality & Assumptions disclaimer text, the Research-Quality
   Validation diagnostics (bar/signal/trade counts, warm-up bars,
   skipped signals, rejected trades, data gaps), and — for a
   multi-instrument historical run — "Results by Instrument"
   (`PerInstrumentResults` in `BacktestingWorkbenchPage.tsx`).
2. **No PDF-generation dependency existed anywhere** (confirmed via
   `pyproject.toml`/`package.json` grep) — added `reportlab` (backend,
   the actual generator) and `pypdf` (dev-only, for this checkpoint's
   own text-extraction test verification) via `poetry add`.
3. **Re-confirmed directly, not from memory: no sector/fundamental
   data source exists anywhere in this project** (`grep` across
   `src/intraday`) — the only two files matching "sector" are explicit
   disclaimers (`market_regime.py`: "No sector/index/breadth/sentiment/
   OI data"; `price_vs_ma_pct.py`: "sectorwise DMA... deferred"). The
   existing on-screen "Results by Instrument" (per-instrument, never
   per-sector) is confirmed as the correct, honest substitute — Page 4
   mirrors it exactly.

**A real structural finding made along the way**: `BacktestingWorkbenchPage.tsx`'s
own "Results by Instrument" is NOT a single combined multi-instrument
`BacktestResult` object — a multi-instrument historical run produces N
genuinely SEPARATE `BacktestResult` rows (one per instrument), linked
only by `HistoricalBacktestRunProgress.result_backtest_ids: Record
<instrument_id, backtest_id>` on the run's own snapshot. Confirmed by
reading `PerInstrumentResults`'s own fetch logic
(`getBacktestResult(resultBacktestIds[instrumentId])` per instrument).
This directly shaped Part 3's endpoint design (below).

## Part 2 — Field list, confirmed and built to exactly

- **Page 1 — Summary**: strategy identity (id/spec/code/config
  version), instrument, timeframe, date range, position sizing,
  initial/final capital, net P&L, return %, a KPI grid (Win Rate,
  Profit Factor, Max Drawdown, Sharpe, Total Trades, Total Signals),
  real vector equity/drawdown charts from the SAME `mark_to_market_curve`
  the frontend already renders.
- **Page 2 — Signal/Trade Breakdown**: Signals Generated, trades taken
  vs. skipped (with the exact same skip-reason labels already shown in
  "Research-Quality Validation" — "same-direction, position already
  open" / "insufficient capital"), **Pass %/Fail % defined precisely**
  in the PDF's own text ("Pass % = winning trades ÷ total trades ×
  100; Fail % = losing trades ÷ total trades × 100" — computed from
  the real `winning_trades`/`losing_trades`/`total_trades` counts, not
  `100 − win_rate` alone, since a trade with an exactly-zero net P&L
  counts as neither), total profit (`gross_profit`) vs. total loss
  (`gross_loss`) shown separately, Investment vs. Returns together.
- **Page 3 — Ratio Analysis**: Profit Factor, Sharpe, **and Sortino**
  — all three ALREADY fully computed fields, zero new derivation.
  **Calmar was considered and deliberately excluded**, stated
  explicitly in the PDF's own footnote: a Calmar ratio needs an
  ANNUALIZED return, and this project has no established, honest
  trading-day-annualization convention for an intraday-only backtest
  window — inventing one here risks a number that LOOKS precisely
  computed while resting on an unstated, arbitrary assumption.
- **Page 4 (conditional)**: "Results by Instrument" — added only when
  the caller supplies `?run_id=`, one row per instrument (Net P&L, Win
  Rate, Total Trades), explicitly labeled as NOT sector-wise.
- **Every page's footer**: the exact on-screen disclaimer text —
  "RESULT, not a promise" + trust level, the real `data_quality` label
  (with the SAME "NOT SUITABLE FOR TRADING-GRADE PERFORMANCE CLAIMS"
  warning for `SAMPLE_BAR`), the real cost-model verified/assumption
  badge, the real transaction-cost/slippage assumption text, and the
  real survivorship-bias limitation note — reused verbatim from
  `result["data_quality"]`/`result["cost_model_identity"]`, never
  reworded or dropped.

**KPI card visual pattern**: reused the same label-above-value grid
idea `BacktestingWorkbenchPage.tsx`'s own `.backtest-results__kpi`/
`Dashboard`'s own `.dashboard__grid` tiles use (label in muted text,
value in bold, boxed cell) — the one shape a PDF table cell can
actually express; a literal CSS-grid equivalent doesn't exist in
PDF, so this is the closest honest analogue, not a reinvented style.

## Part 3 — Backend PDF generation (built)

- **`application/services/backtest_pdf_report.py`** — pure function
  `build_backtest_report_pdf(result: dict, *, sibling_results:
  list[dict] | None = None) -> bytes`. Consumes EXACTLY the
  `to_json_dict()` shape already served by `GET /backtesting/results/
  <id>/` — no second, parallel result representation. Zero new
  backtest computation: every metric is either copied verbatim or a
  pure arithmetic rollup over data already on the result (Pass %/
  Fail %, matching the same "sum already-computed trade fields"
  discipline the frontend's own `totalGrossPnl`/`totalCosts` already
  uses client-side).
- **Charts are real vector line charts**, not just numbers —
  `reportlab.graphics.charts.lineplots.LinePlot`, built from the SAME
  `mark_to_market_curve` series `EquityCurveChart`/`DrawdownChart`
  already render on-screen. reportlab's own charting genuinely
  supports this without needing matplotlib or any other extra
  dependency (confirmed by building and rendering them, not assumed).
- **`GET /api/v1/config/backtesting/results/<backtest_id>/report/`**
  (new view, `backtesting_views.py`, registered in `urls.py`) — reuses
  `BacktestingService.get_result()` (the SAME read path
  `get_backtest_result` already uses) for the primary result. Optional
  `?run_id=<run_id>` query param resolves sibling instrument results
  via `DjangoBacktestRunRepository().get(run_id).result_backtest_ids`
  — the EXACT same repository/field the existing run-progress endpoint
  already exposes, never a second universe-resolution mechanism, per
  the RULES' own explicit instruction. A sibling that fails to resolve
  is skipped honestly (a per-instrument failure is already a
  documented real possibility on the run snapshot's own
  `failed_instruments`), never breaking the single-result report the
  operator actually asked for.
- Response: `Content-Type: application/pdf`,
  `Content-Disposition: inline` — read-only, `IsAuthenticated` only
  (matching `get_backtest_result`'s own permission level exactly).

## Testing

- **`tests/unit/infrastructure/api/test_checkpoint_backtest_pdf_a.py`**
  (new, 4 tests, real Postgres) — runs a REAL backtest first (against
  the deterministic `NSE:FIXTURE01` fixture, `test_backtesting_api.py`'s
  own established zero-network payload, reused verbatim), then
  requests its PDF report:
  - **A real text-extraction check** (`pypdf`), not merely "a PDF was
    produced" — confirms `page_count == 3` for a single-instrument
    result and that every field label from Part 2's list genuinely
    appears in the extracted text (Win Rate, Profit Factor, Sharpe,
    Sortino, Pass %/Fail %, Total Profit/Total Loss, "RESULT, not a
    promise", "Data quality").
  - 404 for an unknown `backtest_id`; 401/403 for an unauthenticated
    request.
  - **The multi-instrument `?run_id=` path**: two real, independent
    backtests (same fixture instrument, deliberately different bar
    ranges — see the real finding below), a real
    `DjangoBacktestRunRepository` snapshot linking them, confirms the
    PDF genuinely grows to 4 pages with "Results by Instrument" and
    the correct instrument id present.
- **A genuine, real finding caught and fixed while writing this test,
  not the production code**: `_deterministic_backtest_id()`
  (`research/backtesting/engine.py`) derives identity from
  configuration + DATA identity + cost-model identity — deliberately
  NOT `strategy_values` (by design: "same bars, different cost model
  must never collide"). Two backtests differing ONLY in
  `strategy_values` therefore produce the SAME `backtest_id` and
  silently overwrite each other — a real, pre-existing, by-design
  behavior of the (unmodified) backtest engine, not something this
  checkpoint touches or is in scope to change. The test was adjusted
  to vary the date range instead, genuinely producing two independent
  results — documented here rather than silently worked around.
- **Full backend suite**: `poetry run pytest tests/unit -q` → **5
  failed / 3418 passed** (up from 3414 — the 4 new tests) — the exact
  same 5 pre-existing, unrelated failures every prior checkpoint's own
  baseline has had; no regression.
- **OpenAPI schema generation** (`manage.py spectacular --fail-on-warn`)
  — clean, zero warnings, confirming the new endpoint's `@extend_schema`
  (a plain `OpenApiResponse(description="PDF file")`, since the
  response body is a binary file, not a JSON serializer) is well-formed.

## RULES compliance

- No sector-wise data anywhere — confirmed unavailable, not
  fabricated.
- No new backtest computation — every PDF field is either copied
  verbatim from the existing `to_json_dict()` payload or a pure
  arithmetic rollup over already-computed trade-level fields (Pass %/
  Fail %), matching the exact discipline the frontend's own results
  panel already uses.
- **No frontend "Download PDF" button** — Phase A is backend-only, per
  this project's own established phased discipline; confirmed
  directly via `git status` (only backend files + the two dependency
  manifest files changed).
- No strategy code changes, no registry change, no live session
  launched.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
