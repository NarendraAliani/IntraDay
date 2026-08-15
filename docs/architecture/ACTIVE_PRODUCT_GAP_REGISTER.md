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
| Strategy-generated orders never reach paper trading automatically | `IMPLEMENTED_BUT_NOT_VALIDATED` | `PaperSignalExecutionService` exists and is unit-tested (12/12 passing across Checkpoints 36-37) against synthetic bars supplied directly by the test. It has never been exercised against a real bar feed, a scheduler, or an operator-triggered API call — "validated" here means "proven correct on inputs the caller controls," not "proven correct in the actual runtime it would run in." |
| No automated trigger connects live/aggregated bars to `PaperSignalExecutionService` | `DESIGNED_ONLY` | Deliberately not built this checkpoint (see `STRATEGY_TO_PAPER_SELECTION.md`, "What is explicitly NOT done"). Blocks any claim that strategy-driven paper trading is operational end-to-end without a human manually constructing bars. |
| Kill switch / emergency square-off for open positions | `BLOCKED` | `TradingHaltStatus` gates new order submission (proven, this checkpoint's own kill-switch test included). There is no code path that force-closes an *already open* paper position when the kill switch activates. Remains blocked pending an explicit, reviewed design for what "emergency square-off" means for a paper (not real) broker — building it hastily risks a false sense of safety that wouldn't transfer to live trading. |
| **NEW (Checkpoint 37): SEBI algo-trading framework compliance (Algo-ID, broker strategy registration)** | `MISSING` — `EXTERNAL_DEPENDENCY` | `VERIFIED_SECONDARY` research (`SIGNAL_COMMUNICATION_AND_COMPLIANCE_RESEARCH.md`) found SEBI's retail algo-trading framework became mandatory 2026-04-01 (already past as of this checkpoint's date, 2026-08-15) — every algo order must carry an exchange-assigned Algo-ID, and the strategy must be registered through the broker (Dhan). **Nothing in this project's domain/order/broker layers has any concept of Algo-ID or registration status.** This is a hard, previously-untracked blocker for ANY future real order placement — not a paper-trading concern (paper never reaches an exchange), but must be resolved before a LIVE-trading checkpoint is even attempted. Primary SEBI circular text not yet directly verified — flagged for direct verification before acting on it. |

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
| **NEW (Checkpoint 37): most report catalogue types remain NOT_YET_IMPLEMENTED/PARTIAL** | `PARTIALLY_IMPLEMENTED` | 3 of 11 catalogued report types are `AVAILABLE` with real data (`BACKTEST_REPORT`, `MARKET_DATA_QUALITY_REPORT`, and the new `COMMUNICATION_DELIVERY_REPORT`); the rest — Signal Report, Portfolio Report, Risk Report, Production Report, Audit Report, System Health Report, Strategy Research Report — remain `PARTIAL`/`NOT_YET_IMPLEMENTED`/`PLANNED`. Checkpoint 37 Part 8 named 16 report types; this project's actual catalogue (`ReportType`, Checkpoint 32) only tracks 11, and only one of the ~14 report types Part 8 named that didn't already exist was implemented this checkpoint (Communication Delivery). Live Signal Report, Execution Report, Order Report, Trade Report, Daily P&L Report, Strategy-wise Win/Loss, Risk Rejection Report, Missed/Blocked Signal Report, and Broker Rejection Report were NOT built this checkpoint — real underlying data exists for several of them (paper orders/trades/positions since Checkpoint 35, risk decisions since Checkpoint 34) but no report assembler reads it yet. |
| **NEW (Checkpoint 37): frontend/CSS — no code changed this checkpoint** | `PARTIALLY_IMPLEMENTED` (unchanged from Checkpoint 35/36) | Part 9 asked for a full frontend audit (accessibility, responsive tables, status indicators beyond color). Not attempted this checkpoint — time was prioritized on the Signal Communication Engine (this checkpoint's core objective) and its tests. No frontend file was modified; Checkpoint 35's design-token/responsive work is the last frontend change on record. |

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
| Communication-ledger automatic retry | `MISSING` | `DeliveryAttempt.retry_count` is a real, persisted field, but nothing increments it — no retry loop exists. A single failed delivery attempt is recorded once and never retried. |
| Communication engine — no automatic trigger for live signals | `DESIGNED_ONLY` (mirrors the paper-signal bridge's own P0 row) | `get_signal_communication_service()` (`infrastructure/api/paper_trading_runtime.py`) is fully composable and wired to real credentials, but nothing calls it outside tests — same deliberate deferral rationale as `PaperSignalExecutionService`'s own automatic-trigger gap. |
| Provider message-ID capture (Telegram/Discord) | `MISSING` | `DeliveryAttempt.provider_message_id` exists in the contract but is always `None` in practice — the thin HTTP clients (Checkpoint 22) don't parse the provider's response body for a message ID. Not fabricated; genuinely not captured. |

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
