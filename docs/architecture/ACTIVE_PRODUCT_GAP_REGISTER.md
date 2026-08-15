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
| SEBI algo-trading framework compliance (Algo-ID, broker strategy registration) | `MISSING` — `EXTERNAL_DEPENDENCY` | `VERIFIED_SECONDARY / PRIMARY_CONFIRMATION_PENDING` (upgraded from Checkpoint 37's plain `VERIFIED_SECONDARY` — Checkpoint 38 confirmed the exact primary circular identity directly on `sebi.gov.in`: Circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013, "Safer participation of retail investors in Algorithmic trading," dated 2025-02-04, with confirmed timeline-extension circulars — but the full text still did not render via fetch, so the specific technical provisions remain secondary-sourced. See `SEBI_ALGO_TRADING_PRIMARY_VERIFICATION.md`.) Still no Algo-ID/registration concept anywhere in this project — does not block PAPER trading. |
| **NEW (Checkpoint 38): `RiskLimits.max_per_trade_risk` is configured but NEVER enforced** | `MISSING` | Code-level audit of `trading_engine/risk_engine/evaluator.py::evaluate_order_risk()` found 10 real checks (kill switch, session, strategy activation, stale data, 2 duplicate-order checks, max daily loss, max position size, max total exposure, max concurrent positions) — but `max_per_trade_risk` (a real `RiskLimits` field with its own positivity validation) is never read or compared against anywhere in the function. A configured "max per-trade risk" limit currently has NO effect on any order. This is exactly the "configuration schema vs enforcement" confusion Checkpoint 38 Part 12 warned against — found by reading the function body, not trusting the field's existence. Not fixed this checkpoint: correctly enforcing it requires a per-trade risk definition (entry vs. stop-loss distance × quantity) that not every strategy can supply (Checkpoint 36 already established `ema_crossover` computes no stop-loss) — implementing it hastily risks either rejecting every `ema_crossover` order or silently exempting stop-loss-less strategies from a "maximum" that was supposed to apply universally. |
| **NEW (Checkpoint 38): no daily trade-count limit and no instrument allow/deny list exist AT ALL** | `MISSING` | Neither a configured field nor an enforcement check exists for either control — distinct from `max_per_trade_risk` (configured-but-unenforced), these are not even schema-present. Named because Part 12 explicitly asked for both to be audited. |

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
| ~~Communication-ledger automatic retry~~ | `IMPLEMENTED_AND_TESTED` (closed Checkpoint 38) | `NotificationRouter` now retries a TRANSIENT failure up to `max_attempts` (default 3) with exponential backoff, classified per-provider (`is_retryable`); a PERMANENT failure (bad token/webhook) is never retried. Proven: `test_transient_failure_is_retried_and_eventually_succeeds`, `test_retry_is_bounded_and_gives_up_after_max_attempts`, `test_permanent_failure_is_never_retried`. |
| Communication engine — no automatic trigger for live signals | `DESIGNED_ONLY` (mirrors the paper-signal bridge's own P0 row) | Still not wired to any scheduler/live feed this checkpoint either — see the P0 "no automated trigger" row above; the same market-data-quality-enforcement prerequisite blocks both. |
| ~~Provider message-ID capture (Telegram/Discord)~~ | `IMPLEMENTED_AND_TESTED` (closed Checkpoint 38) | `send_telegram_message_with_id()` parses Telegram's real JSON response (`result.message_id`); `send_discord_message_with_id()` uses Discord's documented `?wait=true` query parameter to get the real message object back (Discord's default webhook POST returns 204 with no body). Both are `VERIFIED_PRIMARY` against each provider's own public API docs (unchanged from Checkpoint 22's original sourcing). Not yet exercised against REAL Telegram/Discord credentials in this session — proven only against the in-memory fake providers and JSON-shape assertions; see Part 22 honesty note in the final report. |
| **NEW (Checkpoint 38): paper-mode reconciliation now runs against REAL `PaperBroker` + ledger** | `IMPLEMENTED_AND_TESTED` | `infrastructure/api/paper_reconciliation_runtime.py::reconcile_paper_state()` composes the EXISTING broker-neutral `control_plane.reconciliation` engine (Checkpoint 34, previously only proven against synthetic fixtures) against a real `PaperBroker` + `DjangoPaperLedgerRepository`. 4 new tests, including one that directly corrupts a ledger row and proves the mismatch is detected (`test_ledger_drift_from_broker_is_detected`). Detection/classification only — no automatic correction, per Decision 152's unchanged principle. |
| **NEW (Checkpoint 38): signal identity model now includes timeframe + full strategy version** | `IMPLEMENTED_AND_TESTED` | `derive_signal_id()` extended from (strategy_id, configuration_version, instrument_id, timestamp) to also include timeframe, specification_version, code_version — closing the theoretical multi-timeframe collision gap Part 6 asked to justify. `direction` deliberately excluded (an output, not an input — see the function's own docstring for the full justification). |

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
