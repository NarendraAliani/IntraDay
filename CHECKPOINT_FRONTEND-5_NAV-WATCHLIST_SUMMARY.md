# CHECKPOINT-FRONTEND-5 (Nav Dropdown + Navbar Wrapping + Watchlist Edit)

**Naming note, flagged explicitly**: `CHECKPOINT_FRONTEND-5_SUMMARY.md`
already exists at the repo root from an **earlier, unrelated**
checkpoint (an icon-audit sweep — `BacktestingWorkbenchPage.tsx`/
`HistoricalMarketDataCard.tsx`/`ReportsOverviewPage.tsx` glyphs). This
checkpoint's own directive reused the identifier "CHECKPOINT-FRONTEND-5"
for a different topic (nav dropdown, navbar wrapping, watchlist edit).
Per the standing "check before writing to any file that might already
exist" discipline, the existing file was **not overwritten** — this
summary is written to `CHECKPOINT_FRONTEND-5_NAV-WATCHLIST_SUMMARY.md`
instead, and the collision is reported here rather than silently
resolved.

Three distinct, real issues, all fixed. No live session launched, no
strategy/registry change, exactly the three issues named — no broader
redesign.

## Issue 1 — Nav dropdown required two clicks to close

**Root cause, confirmed directly**: `App.tsx`'s nav groups used the
native `<details>`/`<summary>` disclosure with `open={containsActive
|| undefined}` — the `open` attribute was driven by whether the
CURRENT SCREEN lived inside that group, not by real open/closed
intent. Once an operator selected an item inside a group, that group
now "contained the active screen," so React forced `open` back to
`true` on every subsequent render — **the group containing the active
screen could never actually be closed at all**, only a DIFFERENT
group's dropdown would close (since its own `containsActive` went
false). There was also no click-outside handler and no Escape
handling.

**Fix**: nav open/closed state is now a single, fully controlled
`openGroupId: string | null` in `AppShell`. The summary's native click
is `preventDefault()`-ed and replaced with explicit
`setOpenGroupId(...)` toggling; selecting an item calls
`setOpenGroupId(null)` alongside `setScreen(...)`; a `mousedown`
listener on `document` closes the dropdown on any click outside the
`<nav>` (via a `ref`); a `keydown` listener closes it on `Escape`.
Styling (`nav-group__toggle--active` for "you are here") is
unchanged and still independent of open/closed state.

**Tested**: new `src/app/NavDropdown.test.tsx` (6 tests) proves:
open/close via the same toggle; close-on-item-select even though the
selected screen now lives in that group (the exact bug); a group
containing the active screen can still be closed by its own toggle;
close on outside click; close on Escape; opening a different group
closes the first. Verified visually via real-browser Playwright
screenshot too (dropdown open → select Screener → dropdown fully
closed, navigated correctly, in one action).

## Issue 2 — Navbar wrapped to multiple lines

**Investigated directly with real evidence before deciding the fix**,
per the checkpoint's own explicit instruction — measured
`.app-shell__header`'s own bounding box via Playwright at 960 / 1024 /
1280 / 1366 / 1400 / 1440 / 1920px viewports:

| viewport | `main.width` (before fix) | header rows (before fix) |
|---|---|---|
| 960–1920px | **960px at every width** | **3 rows at every width** |

**Root cause: a genuine, viewport-independent layout bug, not a
narrow-screenshot artifact.** `<header>` lived inside `<main>`, which
caps at `--page-max-width: 960px` (the page's own reading-width
token, correct for page CONTENT). The header's own content (brand +
5 nav entries + theme selector + identity) measures **≈1393px** of
required width — so `main`'s 960px cap meant the header wrapped to 3
lines **at every desktop width tested, including 1920px**, since
widening the browser past 960px never gave the header any more room.

**Fix**: `<header>` moved OUTSIDE `<main>` into its own full-bleed
`.app-shell__header-bar` wrapper with a new, chrome-only
`--shell-max-width: 1440px` token (deliberately NOT reusing the
already-reserved `--page-max-width-wide` token, which is documented
for a different future purpose — a new token keeps that reservation's
own intent intact). `main`'s own 960px reading-width cap is completely
unchanged for every other page. Horizontal padding at the 768px/480px
breakpoints is now mirrored onto the header bar so it stays visually
aligned with `main` at every width (placed carefully AFTER the base
rule in source order — an earlier attempt put the media-query
overrides before the base rule, which would have made the base rule
win at every width due to equal CSS specificity; caught and fixed
before commit).

**Result, measured again after the fix**:

| viewport | header rows (after fix) |
|---|---|
| 960px | 3 (unchanged — the header's own `--shell-max-width` cap is 1440px, but `main`-width itself IS still 960px only at exactly this boundary width, giving no more room than before) |
| 1024–1366px | **2** (clean split: brand+nav on one row, identity block on its own row below — not a broken 3-way wrap) |
| ≥1400px | **1** (single line, matching the operator's own expectation) |

This is reported honestly as a **deliberate two-tier responsive
behavior** (single line ≥1400px, a clean 2-row split 961–1399px, the
pre-existing full column stack ≤640px unchanged) rather than an
oversold "fixed at every width" claim — 1366px (a very common laptop
resolution) is 27px short of the single-line threshold. Verified
visually via Playwright screenshot at 1280px: a clean, intentional-
looking 2-row layout, not an ugly wrap.

## Issue 3 — No way to edit an existing watchlist

**Backend investigated first, per the RULES ("no backend changes
unless a genuine, small gap is found")**: `WatchlistService.save()` /
`DjangoWatchlistRepository.save()` (confirmed directly by reading both
files) is **already an UPSERT** — `WatchlistRecord.objects.
update_or_create(owner_username=owner, name=name, defaults={...})`.
Editing an existing watchlist's instrument list is exactly a second
`saveWatchlist()` call with the same name and a different
`instrument_ids` list — **zero backend code changes were needed** for
this half of the capability. Proven with a new backend test
(`test_save_again_with_same_name_edits_instrument_list_in_place`):
saving twice under the same name leaves exactly one watchlist row,
with the updated instrument list.

**Rename — explicitly decided OUT OF SCOPE for this checkpoint,
stated plainly rather than silently skipped**: there is no atomic
rename operation (`(owner, old_name) -> (owner, new_name)`); the
repository is keyed by `(owner, name)`, and "renaming" via the
upsert path would only ever create a second watchlist under the new
name while leaving the old one behind — not a real rename. This is a
genuinely separate, small feature (a dedicated rename endpoint/method)
left for a future checkpoint, not silently dropped.

**Frontend**: `WatchlistPage.tsx` gained an `editingName` state. An
"Edit" button per watchlist section loads that watchlist's current
`instrument_ids` into the existing `InstrumentPickerMulti` and locks
the name field (`disabled`, since rename is out of scope); the submit
button becomes "Save changes" (vs. "Save Watchlist" for a new one) and
a "Cancel" button appears, restoring the blank create-new form. The
same `saveWatchlist()` call is reused for both create and edit paths.

**Coexistence with `CHECKPOINT-WATCHLIST-A`/`B`'s market-data
table — confirmed, not assumed**: the edit form and the
`WatchlistMarketDataSection` table render as two independent sections
on the same page; editing one watchlist's instruments does not affect
another's table, and the just-edited watchlist's own table (still
showing its pre-edit data until a page reload) sits directly below its
own edit form with no visual or functional conflict — verified via
Playwright screenshot showing both simultaneously in both themes.

**Tested**: two new Vitest cases in `WatchlistPage.test.tsx` — Edit
loads the existing instruments (pre-checked in the picker) with the
name field locked, adding an instrument and clicking "Save changes"
calls `saveWatchlist` with the SAME (locked) name and the updated
instrument list, and editing state clears after a successful save;
Cancel restores the blank create-new form untouched. One new backend
test (above) proves the upsert-based edit path directly against real
PostgreSQL.

## Testing summary

- **New test files**: `frontend/src/app/NavDropdown.test.tsx` (6
  tests), plus 2 new tests in `WatchlistPage.test.tsx` (now 8 total),
  plus 1 new backend test in
  `test_watchlist_and_research_status_api.py` (now 7 total).
- **Full frontend suite**: `npm run typecheck` clean; `npx vitest run`
  → **388 passed / 388** (37 test files), zero regressions.
- **Full backend suite**: `poetry run pytest tests/unit -q` → **5
  failed / 3412 passed** — all five failures are the exact same
  pre-existing, unrelated set this session's own pre-flight baseline
  already had (`test_checkpoint_64_52_database_first_backtest.py` ×2,
  `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`,
  `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`,
  `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`)
  — no regression introduced.
- **Real-browser Playwright screenshots (both themes)**, network-
  mocked, not repo files: nav dropdown open → item selected → closed
  in one action (Issue 1); the header at 1280px showing the clean
  2-row split, and the watchlist edit form coexisting with its own
  market-data table (Issue 3), both themes.

## Files touched

- `frontend/src/app/App.tsx` — controlled nav dropdown state, header
  moved outside `<main>`.
- `frontend/src/app/styles.css` — `--shell-max-width` token, header-bar
  CSS restructure (cascade-order corrected), `.watchlist-page__form-actions`.
- `frontend/src/app/NavDropdown.test.tsx` — new.
- `frontend/src/features/backtesting/WatchlistPage.tsx` — edit
  capability.
- `frontend/src/features/backtesting/WatchlistPage.test.tsx` — 2 new
  tests.
- `tests/unit/infrastructure/api/test_watchlist_and_research_status_api.py`
  — 1 new backend test.

No changes to `WatchlistService`, `DjangoWatchlistRepository`, or any
other backend file — confirmed directly via `git status`, not assumed.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
