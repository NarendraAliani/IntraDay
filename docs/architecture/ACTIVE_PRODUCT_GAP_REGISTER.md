# Active Product Gap Register (Checkpoint 36 Part 3)

Fresh re-audit, not an append to `PRODUCT_READINESS_GAP_ANALYSIS.md`
(Checkpoint 33/34's register, left intact as a historical record). Status
taxonomy per Checkpoint 36 Part 1:

`IMPLEMENTED_AND_TESTED` | `IMPLEMENTED_BUT_NOT_VALIDATED` |
`PARTIALLY_IMPLEMENTED` | `DESIGNED_ONLY` | `BLOCKED` |
`EXTERNAL_DEPENDENCY` | `UNKNOWN`

Priority: P0 (blocks any further trading-readiness progress) / P1 (blocks
operational confidence) / P2 (real gap, not urgent) / P3 (nice to have).

## P0

| Gap | Status | Evidence |
|---|---|---|
| Strategy-generated orders never reach paper trading automatically | `IMPLEMENTED_BUT_NOT_VALIDATED` | `PaperSignalExecutionService` exists and is unit-tested (8/8 passing, this checkpoint) against synthetic bars supplied directly by the test. It has never been exercised against a real bar feed, a scheduler, or an operator-triggered API call — "validated" here means "proven correct on inputs the caller controls," not "proven correct in the actual runtime it would run in." |
| No automated trigger connects live/aggregated bars to `PaperSignalExecutionService` | `DESIGNED_ONLY` | Deliberately not built this checkpoint (see `STRATEGY_TO_PAPER_SELECTION.md`, "What is explicitly NOT done"). Blocks any claim that strategy-driven paper trading is operational end-to-end without a human manually constructing bars. |
| Kill switch / emergency square-off for open positions | `BLOCKED` | `TradingHaltStatus` gates new order submission (proven, this checkpoint's own kill-switch test included). There is no code path that force-closes an *already open* paper position when the kill switch activates. Remains blocked pending an explicit, reviewed design for what "emergency square-off" means for a paper (not real) broker — building it hastily risks a false sense of safety that wouldn't transfer to live trading. |

## P1

| Gap | Status | Evidence |
|---|---|---|
| Automatic end-of-session expiry scheduling | `PARTIALLY_IMPLEMENTED` | `PaperBroker.force_expire_end_of_session()` (Checkpoint 34) and its manual API trigger (Checkpoint 35) both work and are tested. Nothing calls it automatically at session close — an operator must remember to call it. Named as a gap since Checkpoint 32's runtime-architecture decision; still true. |
| Market-data feed classification is manual, not enforced | `PARTIALLY_IMPLEMENTED` | `AggregatedBarObservation` (Checkpoint 24A) carries quality metadata, but nothing in `paper_signal_execution.py` or `PaperTradingService` currently *reads* that classification and refuses `TRADING_GRADE`-only paths from being fed `SAMPLE_BAR` data, because no automatic feed exists yet (see P0 row above) to even attempt the mistake. The moment an automated trigger is built, this becomes a hard requirement, not a future one. |
| Instrument master coverage | `UNKNOWN` (re-confirmed, not re-audited this checkpoint) | Not re-investigated this checkpoint under time constraints; carried forward from Checkpoint 34's own finding rather than re-verified — flagged here so it is not silently dropped from tracking. |
| Session/holiday calendar correctness | `UNKNOWN` (re-confirmed, not re-audited this checkpoint) | Same as above — explicitly not re-verified this checkpoint; do not treat its absence from this register as "resolved." |
| Clock/time integrity monitoring (drift detection) | `DESIGNED_ONLY` | No implementation found this checkpoint via targeted `grep` for clock-drift/NTP-style checks; not deepened this checkpoint. |
| Observability / control plane | `PARTIALLY_IMPLEMENTED` | Existing capability-status UI components and read APIs (Checkpoint 33-35) provide *some* visibility (order/trade/position/funds state), but there is no dedicated operational dashboard (queue depth, last successful sync timestamp, error rates) as Part 15 envisions. Not built this checkpoint. |
| Frontend operator dashboard depth | `PARTIALLY_IMPLEMENTED` | `PaperTradingPage.tsx` (Checkpoint 35) is functional but oriented around order entry and raw table monitors, not an at-a-glance operational summary. Not rebuilt this checkpoint — correctly scoped as lower priority than the Part 4-6 core bridge under this checkpoint's own stated priorities. |

## P2

| Gap | Status | Evidence |
|---|---|---|
| Frontend/backend dependency vulnerabilities | `IMPLEMENTED_AND_TESTED` (as in: fully investigated and classified, not "fixed") | See `ACTIVE_PRODUCT_OPERATIONAL_RESEARCH.md` Part 3 — 5 npm advisories (all dev-only, unreachable given actual config) and 8 pip advisories (both packages dev-only). No forced upgrade applied; documented as a dedicated future tooling-upgrade checkpoint's job. |
| Accessibility contrast/keyboard walkthrough | `UNKNOWN` | Checkpoint 35 added `:focus-visible` and design tokens but no contrast-ratio measurement or full keyboard walkthrough was performed then or now. Explicitly not validated this checkpoint — reported as unknown rather than assumed fine. |
| Failure/recovery matrix (Part 16) | `DESIGNED_ONLY` | Not authored this checkpoint under time constraints. |
| Reporting depth (Part 20) | `PARTIALLY_IMPLEMENTED` | `REPORTING_ARCHITECTURE.md` (Checkpoint 32) exists; no new report types added this checkpoint — none were justified by new data this checkpoint produced beyond the signal-lineage fields already covered by `PaperOrderRecord.signal_id`. |

## P3

| Gap | Status | Evidence |
|---|---|---|
| Second strategy wired to paper trading | `BLOCKED` (deliberately) | See `STRATEGY_TO_PAPER_SELECTION.md` — withheld pending the same evidence bar `ema_crossover` cleared (independent reference validation), not a technical blocker. |
| Dhan Sandbox adapter-conformance harness | `EXTERNAL_DEPENDENCY` | Classified `USE_LATER`; correct trigger is the start of real `BrokerGateway` adapter work, not this checkpoint. |

## What changed since Checkpoint 34/35's registers

- **Closed this checkpoint**: nothing was fully closed to `IMPLEMENTED_AND_TESTED`
  at the "operates automatically in production" bar — the new bridge is
  real and tested but explicitly not wired to a live trigger (see P0).
  Overstating this as "done" would be exactly the dishonesty this
  checkpoint's principles forbid.
- **Newly identified this checkpoint**: the market-data-classification
  enforcement gap (P1) — did not exist as a distinct line item before,
  because no automated signal-to-order pathway existed for it to matter
  yet.
- **Explicitly not re-audited this checkpoint** (carried forward
  unchanged, flagged so silence isn't mistaken for resolution): instrument
  master coverage, session/holiday calendar correctness, clock-drift
  monitoring, accessibility validation, failure/recovery matrix.
