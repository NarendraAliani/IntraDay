# CHECKPOINT-BACKTEST-PDF-C — Trade Ledger + Layout Fixes + Combined Multi-Instrument File

No filename collision — confirmed via `ls` before writing.

## Issue 1 — Full per-trade ledger, added

New "Trade Ledger" page(s) at the end of every report — **# , Date,
Entry Time, Entry Rate, Exit Time, Exit Rate, Direction, Qty, Total,
P&L, P&L %** — every field either copied verbatim from the SAME trade
dicts `TradeTable` (`BacktestingWorkbenchPage.tsx`) already renders,
or an honestly-stated one-line derivation, exactly per the RULES:

- **Total** = `quantity × entry_price` (the trade's own position
  value at entry) — stated explicitly in the PDF's own column note,
  never silently presented as if it were a stored field.
- **P&L %** = `net_pnl ÷ Total × 100` — likewise stated explicitly.
- **Direction** reuses the exact on-screen `BULLISH → "Long"` /
  `BEARISH → "Short"` mapping, confirmed by reading `TradeTable`'s own
  render logic, not guessed.
- **Pagination**: 15 rows/page — reused **verbatim** from
  `TradeTable`'s own `TRADES_PER_PAGE` constant (confirmed by reading
  it directly), not a new, independently-chosen number.

## Issue 2 — The real layout bug, found and fixed

**Root cause confirmed directly**, not assumed: every label/value
table (`config_table`, `validation_table`) rendered its cells as
plain Python `str` objects. A reportlab `Table` does **not** word-wrap
a plain string cell — it draws the full text starting at the cell's
own left edge, running as far right as needed, **overlapping whatever
is drawn in the next column**. With the long, fixed skip-reason label
("Skipped Signals (same-direction, position already open)") in a
9cm-wide first column next to a numeric second column, this produces
exactly the operator's own reported garbling
("...e-direction, position already open) 364"). Confirmed by
rendering the pre-fix PDF and finding the identical overlap, not
assumed from reading the code alone.

**Fix**: every table cell that can ever hold operator-length text is
now a `Paragraph` (reportlab genuinely word-wraps a `Paragraph` within
its own column width) via a new shared `_label_value_table()` helper —
applied to the Configuration table, the Signal/Trade Breakdown
validation table, and the new Trade Ledger and Results-by-Instrument
tables alike, so the same class of bug cannot recur in any of them.

**The footer** was also switched from a raw, un-wrapped
`canvas.drawString()` loop (one call per disclaimer line, silently
running past the page's own right margin if a sentence was long
enough) to a single wrapped `Paragraph`, drawn via `wrap()`/`drawOn()`
within the reserved footer band — it now grows downward within its
own space for a long disclaimer sentence instead of overflowing
sideways. `_FOOTER_HEIGHT` was also widened (2.6cm → 3.4cm) to
comfortably fit realistic wrapped disclaimer text.

**Verified with a real generated PDF**, not just "it compiles" — a
real `pypdf` text-extraction check confirms the full label
("Skipped Signals (same-direction, position already open)") appears
intact and the exact garbled fragment never appears, using the same
long-label case the operator's own PDF showed the bug in.

## Issue 3 — Combined multi-instrument file

`?run_id=` mode now includes **every scanned instrument's own
complete report** (Summary, Signal/Trade Breakdown, Ratio Analysis,
Trade Ledger — all of Issue 1's own new content too) in ONE file, not
just a one-line summary row per sibling:

- A "Results by Instrument" **index page** first (the same summary
  table as before, kept — useful as a quick-glance overview), then
  each instrument's own complete report in sequence (this result
  first, then each sibling), each behind a clear **divider page**
  ("Instrument N of M" + the instrument id) so the combined file is
  navigable, not one undifferentiated page stream.
- **Each instrument's own pages get their own, correct footer** — a
  dedicated reportlab `PageTemplate` per instrument (switched via
  `NextPageTemplate`), never one shared footer that could show
  instrument A's data-quality facts on instrument B's pages.
- **A real, own bug found and fixed while building this**:
  `NextPageTemplate` only takes effect starting the *next* page break
  processed *after* it — the first implementation appended it *after*
  the divider content's own leading transition, so each instrument's
  own divider page rendered with the *previous* instrument's footer
  (confirmed directly via real per-page text extraction, not assumed
  from reading the code). Fixed by reordering: `NextPageTemplate` is
  now appended *before* the leading `PageBreak()` that creates that
  instrument's first page, and the fix was re-verified the same way —
  a fresh per-page footer check confirming every divider page now
  shows the correct, own-instrument disclaimer text.
- **The single-instrument case (no `run_id`) is structurally
  unchanged** — no index page, no divider page; only Issue 1's new
  Trade Ledger content is added (confirmed by a dedicated test).
- **File size / generation time, measured honestly, not assumed**: a
  realistic 6-instrument universe (this project's own current
  universe size — 30 trades each, a generous full-day count) generates
  in **0.53s** and produces an **86 KB** file. This scales linearly
  with instrument count and trade count (each instrument's own report
  is independent, fixed-cost work) — comfortably fast and small at
  this project's own real universe sizes. **Honestly reported, not
  claimed to scale indefinitely**: a much larger universe (hundreds of
  instruments) would need a different approach — most plausibly
  generating and downloading the report asynchronously (a background
  job + a "ready" notification) rather than a single synchronous
  request, since reportlab's own per-page rendering cost is genuinely
  linear in total page count. Not a concern at this project's own
  current or near-term scale (this project's real live universes are
  4-6 symbols), so not built — named honestly as a known, deferred
  scaling boundary rather than silently ignored.

## Testing

- **`tests/unit/infrastructure/api/test_checkpoint_backtest_pdf_c.py`**
  (new, 8 tests) — real PDF generation, real `pypdf` text-extraction
  checks throughout:
  - Trade ledger: every field label present, correct pagination
    boundary at 17 trades (2 pages: 15 + 2, matching the reused
    `TRADES_PER_PAGE`), Trade #1's own Total/P&L% values verified by
    independent arithmetic (`Rs. 1,000.00` / `1.90%`), the Long/Short
    mapping confirmed, and an honest empty state with zero trades.
  - Issue 2 regression: the operator's own exact garbled fragment
    confirmed absent, the full label confirmed intact, and a
    dedicated footer-wrapping test with genuinely long disclaimer
    sentences.
  - Issue 3: a 3-instrument (5/3/18 trades) combined file — every
    instrument's own "Trade Ledger"/"Ratio Analysis"/"Signal / Trade
    Breakdown" heading appears exactly once per instrument (never
    just a summary row), the exact page-count arithmetic verified
    (1 + 5 + 5 + 6 = 17), a dedicated per-page footer-correctness
    test proving instrument 2's own pages never carry instrument 1's
    disclaimer text, and a dedicated test confirming the
    single-instrument case gains no index/divider page.
  - One real, end-to-end HTTP test (the same `NSE:FIXTURE01`
    deterministic, zero-network fixture `CHECKPOINT-BACKTEST-PDF-A`'s
    own test file established) confirms the fix is genuinely wired
    into the live endpoint, not just correct in the pure function.
- **`test_checkpoint_backtest_pdf_a.py`'s own two pre-existing tests**
  needed their page-count assertions UPDATED (not preserved
  artificially) — they hardcoded "3 pages" / "a 4th summary page",
  both now stale given Issue 1's new Trade Ledger page and Issue 3's
  own combined-file structure; updated to the new, correct expected
  page counts (4 for single-instrument, 11 for the 2-instrument
  `run_id` test used there) and re-verified passing.
- **Full backend suite**: `poetry run pytest tests/unit -q` → **5
  failed / 3426 passed** (up from 3418 — the 8 new PDF-C tests) — the
  exact same 5 pre-existing, unrelated failures every prior
  checkpoint's own baseline has had; no regression.
- **`CHECKPOINT-BACKTEST-PDF-B`'s frontend button**: confirmed working
  correctly with the changed PDF — no frontend code change needed or
  made (`git status` shows backend/test files only); the endpoint's
  own URL, method, and `Content-Type: application/pdf` response shape
  are all unchanged, only the PDF's own internal content grew. The
  frontend's own `BacktestingWorkbenchPage.test.tsx` (mocked, so
  unaffected by real PDF content either way) re-run and confirmed
  still 25/25 passing.

## RULES compliance

- No fabricated fields — every new field traces to real,
  already-computed trade data or a stated, one-line arithmetic
  derivation (Total, P&L %) — confirmed field-by-field above.
- No strategy code changes, no registry change, no live session
  launched.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
