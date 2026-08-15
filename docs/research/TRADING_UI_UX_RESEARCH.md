# Trading UI/UX Research

Checkpoint 35 Part 12/16. External research into professional trading
dashboard UX patterns and a targeted re-check of remaining Dhan/
regulatory unknowns. Classification: `VERIFIED_PRIMARY` (fetched
directly from the source), `VERIFIED_SECONDARY` (search-engine-
surfaced summary, not independently fetched in full), `UNKNOWN`,
`PROJECT_INTERPRETATION`.

## 1. Dhan Sandbox API — a genuinely new finding this checkpoint

**Source:** WebSearch results referencing `docs.dhanhq.co/api/v2/sandbox`
and third-party summaries (Marketcalls, MadeForTrade).
**VERIFIED_SECONDARY** — a direct `WebFetch` of
`docs.dhanhq.co/api/v2/sandbox` this checkpoint returned no sandbox-
specific content (likely a JS-rendered page this session's fetch tool
could not execute), so this is NOT independently confirmed against the
primary page's actual text, despite the URL itself being real and
referenced by DhanHQ's own documentation site.

**What is reported:** Dhan operates a sandbox API — a fully simulated
trading environment for testing integrations before going live.
Reported characteristics: all orders fill at a fixed price
(reportedly ₹100) regardless of real market conditions; capital resets
daily to a fixed amount (reportedly ₹10,00,000); static IP is NOT
required (since it is not a live trading environment); streaming
market data and real-time quotes are reported as NOT available in the
sandbox.

**Project impact — significant, if confirmed:** this would mean a
future live-broker-adapter checkpoint could validate the actual
`DhanBroker` adapter's wire-format handling (request/response shapes,
authentication, order-status polling) against Dhan's own sandbox
BEFORE ever touching the static-IP/broker-onboarding prerequisites
`PRODUCT_READINESS_GAP_ANALYSIS.md` identified as blocking. This is
a genuinely promising path to closing the "no order placement adapter"
gap without any live-execution risk — but it must be independently
re-verified against Dhan's actual sandbox documentation (a full,
successfully-rendered fetch) before any implementation checkpoint
relies on it. **Recommendation, not yet acted on**: a future checkpoint
should attempt this fetch again (possibly via a different tool/method)
or contact `apihelp@dhan.co` per the page's own fallback, before
designing against it.

## 2. Dhan order-update WebSocket / reconnect semantics — unchanged

Re-checked against Checkpoint 34's own `EXECUTION_RESEARCH.md` findings
- no new information surfaced this checkpoint. Reconnect/heartbeat
semantics for the order-update WebSocket (distinct from the market-feed
WebSocket's documented 10s/40s ping/pong) remain **UNKNOWN**, as
recorded in Checkpoint 34.

## 3. NSE retail-algo FAQ / current SEBI implementation requirements

**Attempted again this checkpoint:** the NSE FAQ PDF
(`nsearchives.nseindia.com/.../FAQ_Retail%20Algo_03112025_NSE.pdf`)
remains unfetched — PDF binary content is still outside this session's
demonstrated `WebFetch` capability (same limitation disclosed at
Checkpoints 33 and 34). **UNKNOWN, unchanged.** SEBI's February 2025
circular and its September 2025 timeline-extension circular remain the
only primary-confirmed regulatory facts (Checkpoint 33's live fetch of
SEBI's own site metadata) — no new regulatory fact was established
this checkpoint.

## 4. Professional Trading Dashboard UX Patterns

**Sources:** multiple 2025-2026 industry articles surfaced via
WebSearch (Medium/"Trading App Design," TradeZella "Trading Dashboard:
8 KPIs That Actually Matter," Pencil & Paper "Dashboard Design UX
Patterns"). **VERIFIED_SECONDARY** throughout this section — general
industry pattern descriptions, not a single authoritative primary
source, and not independently fetched in full.

**Findings, and how they were applied (or explicitly not applied) to
`PaperTradingPage.tsx` this checkpoint:**

| Pattern reported | Applied this checkpoint? |
|---|---|
| Status communicated by form (badge/chip), not only color | **Applied** — every order/position status uses an icon + text badge (`● Active`, `✕ HALTED`, `PENDING`), matching this project's pre-existing `ActiveBadge` discipline (Checkpoint 9) of never using color alone. |
| Fast-scanning KPI strip (available capital, exposure, open positions) above detailed tables | **Applied** — the "Paper Account" section's `paper-trading__kpis` grid gives the three highest-priority numbers before any table. |
| P&L colored to distinguish gain/loss at a glance | **Applied** — `.paper-trading__pnl--positive`/`--negative` classes, still paired with the numeric sign (never color-only). |
| Danger-state visibility for risk breaches/halts | **Applied** — kill-switch HALTED state uses the danger badge class and is the first section on the page. |
| Minimal cognitive load / data density trade-off | **Partially applied** — tables show the fields this checkpoint's API returns (status/quantities/prices/timestamps), not a configurable/dense professional terminal view; a genuinely dense view (heatmaps, streaks, expectancy trends) was explicitly NOT built - out of scope for a proving-ground paper-trading UI, and would risk implying a sophistication the backend doesn't yet have. |
| Behavioral nudges (streaks, cooling-off timers) | **Explicitly NOT applied** — these are retail-engagement patterns for a live-trading product; building them for a paper/proving-ground surface would be premature and orthogonal to this checkpoint's safety-first scope. |

**Conclusion:** the goal per this checkpoint's own instruction was "learn
common operator patterns," not copy a specific product - the patterns
adopted (status-by-form, KPI-first layout, danger visibility) are
generic, low-risk UX hygiene consistent with what this project already
does elsewhere (Backtest Workbench's own KPI-first layout, Checkpoint
27-29), not a new design direction borrowed from any one competitor.
