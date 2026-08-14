# Placeholder & Feature-State Architecture

Checkpoint 32 Parts 4-6, 16. Establishes ONE consistent way this
platform represents a capability that is not (yet) fully available —
so no page invents its own visual/status language, and no unavailable
feature is ever presented as working.

## Status taxonomy

Six states, used identically everywhere a capability or report type is
represented:

| State | Meaning |
|---|---|
| `AVAILABLE` | Fully working today, for its documented scope. |
| `PARTIAL` | Works, but with a known, documented limitation (e.g. REST polling instead of continuous WebSocket coverage). |
| `PLANNED` | Not started; no architectural blocker, just not built yet. |
| `BLOCKED` | Not built because a genuine prerequisite is unmet (e.g. no persistent-process infrastructure) — the blocker must be stated explicitly. |
| `NOT_YET_IMPLEMENTED` | Deliberately out of scope for every checkpoint so far, often by explicit safety rule (e.g. live order placement). |
| `RESEARCH_ONLY` | Works, but only as a research/backtesting artifact — never a claim of production readiness. |

`BLOCKED` always carries a `blocker` string explaining *why*, and
usually a `prerequisite` string explaining what would unblock it — a
bare "Blocked" badge with no explanation is never sufficient (Part 4's
"why unavailable, if blocked" requirement).

## The one shared mechanism

`frontend/src/common/components/CapabilityStatus.tsx` — a single React
component accepting `title`/`description`/`status`/`blocker`/
`prerequisite`/`documentationLink`/`expectedCheckpoint`. Every page that
needs to represent an unavailable, partial, planned, or blocked
capability renders this component — never handcrafted per-page markup
(Part 5's explicit "do not duplicate handcrafted placeholder markup
across pages"). It is never used for a capability that genuinely works
end-to-end; that case renders its real UI.

Two data sources feed it, both under `frontend/src/features/reports/`:

- `capabilityRegistry.ts` — `CAPABILITY_REGISTRY`, grouped by product
  area (Research / Market Data / Trading / Notifications), the single
  list every "what can this platform do" question should read from.
- `reportCatalogue.ts` / `marketDataQualityReport.ts` — presentation
  mirrors of the backend's `application.reporting` contracts (see
  `REPORTING_ARCHITECTURE.md`).

## Discoverability

Every capability in `CAPABILITY_REGISTRY` is reachable from the
**Reports** navigation entry (`ReportsOverviewPage.tsx`), added
alongside the existing Configuration/Settings/Market Data/Strategies/
Backtesting/Compare/Watchlists/Strategy Monitor entries in
`app/App.tsx`'s nav — no routing library, same `useState`-toggle
pattern this project has used since Checkpoint 9 (still appropriate at
nine screens; unchanged philosophy).

Additionally, capabilities already have PARTIAL/BLOCKED context inline
on their own natural page, not only on the Reports page — e.g.
`LiveMarketDataMonitor.tsx`'s `DataQualityBanner` (Checkpoint 31)
explains SAMPLE_BAR status right where a user would look for it. The
Reports page is the **exhaustive index**; inline banners are the
**contextual** surfacing — both exist, neither replaces the other.

## Not confused with TODO/FIXME/dummy code

This project already has a placeholder-marker scanner (enforced
elsewhere in the test suite) that flags developer `TODO`/`FIXME`/stub
comments as unfinished work. The mechanism in this document is a
**deliberate, typed, domain-level status contract** — a real
`CapabilityState` value, rendered by real, tested UI — not a code
comment promising future work. `CapabilityStatus` components and
`CAPABILITY_REGISTRY`/`REPORT_CATALOGUE` entries are excluded from
that scanner's concerns by construction: they contain no `TODO`/
`FIXME`/dummy-implementation markers, only honest status data. The
scanner itself was not weakened or reconfigured this checkpoint.

## Current capability snapshot (see `CAPABILITY_REGISTRY` for the live list)

```
Research
  Backtesting                    AVAILABLE
  Portfolio Backtesting          AVAILABLE
  Comparison                     AVAILABLE
  Independent Reference Validation  AVAILABLE
  Walk Forward Analysis          PLANNED
  Monte Carlo Simulation         PLANNED
  Robustness Validation          PLANNED

Market Data
  Live Market Data Monitor       PARTIAL
  Trading-Grade Bars             BLOCKED
  WebSocket Live Feed            BLOCKED
  Gap Recovery                   BLOCKED

Trading
  Strategy Execution (Live)      NOT_YET_IMPLEMENTED
  Paper Trading                  PLANNED
  Order Management               PLANNED
  Risk Engine                    PLANNED
  Live Execution                 NOT_YET_IMPLEMENTED

Notifications
  Telegram                       AVAILABLE
  Discord                        AVAILABLE
  WhatsApp                       NOT_YET_IMPLEMENTED (out of scope per project rules)
  AI Agent Controls               NOT_YET_IMPLEMENTED
```

## What this checkpoint deliberately did not do

Did not add a placeholder to every single low-level function or
internal module — this document and `CAPABILITY_REGISTRY` cover
*product-level* capabilities a user, developer, administrator, or
report consumer would reasonably look for, not an exhaustive audit of
every empty `trading_engine/*` scaffolding directory (those are
already documented in `DOMAIN_BOUNDARIES.md`/`ARCHITECTURE.md` as
intentional Checkpoint-4 scaffolding, not a gap this checkpoint needed
to re-announce).
