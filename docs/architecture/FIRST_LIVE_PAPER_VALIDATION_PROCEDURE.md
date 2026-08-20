# First Live Paper Validation Procedure

Checkpoint 64.19. This document is a PROCEDURE for the next real market
session with a fresh Dhan credential — it is not executed by this
checkpoint. The market was closed and the configured credential was
expired throughout 64.19's work; no live Dhan connectivity was
attempted, per that checkpoint's explicit directive.

## 1. Next-Market-Open Readiness Checklist

The existing 10-item Pre-Session Readiness Workbench (Checkpoint 64.14,
`live_paper_readiness_checklist.py`, exposed on the Live Paper
Operations Console since Checkpoint 64.15) already covers every item
this checkpoint's own §8 lists, verified by re-reading the checklist
order test (`test_workbench_returns_all_ten_checklist_items_in_order`):

| # | Checklist item (existing, unmodified) | States |
|---|---|---|
| 1 | Dhan Credential | READY / WARNING / BLOCKED |
| 2 | Provider Connectivity | READY / WARNING / BLOCKED / UNKNOWN |
| 3 | Token Validity | READY / WARNING / BLOCKED / UNKNOWN |
| 4 | Watchdog | READY / WARNING / BLOCKED |
| 5 | Market State | READY / WARNING / BLOCKED |
| 6 | Universe | READY / WARNING / BLOCKED |
| 7 | Timeframe | READY / BLOCKED |
| 8 | Strategy Selection | READY / BLOCKED |
| 9 | Paper Execution | READY (structurally always) |
| 10 | Real Trading Safety | READY (structurally always DISABLED) |

**No new readiness engine was built this checkpoint** (per §8's own
explicit instruction) — this table exists to confirm, by direct
cross-reference against the real test, that the existing checklist
already satisfies the checkpoint's own list one-to-one. The aggregate
`LivePaperReadiness.can_start` (Checkpoint 64.12) remains the sole
authoritative "can we start" decision; the checklist only explains it.

## 2. Next-Market-Open Expected Flow

The exact sequence this product is built to support, end to end,
matching the flow this checkpoint's directive itself lays out:

1. Operator configures a fresh Dhan credential (Settings → Dhan).
2. Token validation runs automatically (`evaluate_dhan_token_lifecycle`)
   — Token Validity check reads `VALID`.
3. Operator starts `manage.py run_market_data_worker --provider dhan`
   (a separate OS process — this remains a real, documented,
   unautomated step, unchanged since Checkpoint 64.4).
4. Provider Connectivity / Watchdog checks read `READY` once the worker
   reports a `HEALTHY` watchdog state.
5. Market State reads `READY` once the exchange session is genuinely
   `OPEN` (`session_for_instant()`, real calendar logic, never
   simulated).
6. Operator confirms Universe (see §3 below for the recommended FIRST
   session's universe — deliberately small).
7. Operator confirms Timeframe (recommended: `5m` for the first
   session — enough bars accumulate to warm up EMA/SMA/ATR lookbacks
   within a single session without excessive noise).
8. Operator confirms Strategies (recommended: all three enabled, so the
   validation exercises every evidence-formatter path).
9. Paper Execution / Real Trading Safety checklist items read `READY`
   (structurally, unconditionally).
10. Operator presses **START LIVE PAPER SESSION** on the Live Paper
    Operations Console — the backend independently re-verifies
    `can_start` itself (Checkpoint 64.13 §8, never trusts a
    frontend-cached value).
11. Session state reads `STARTING` (desired.enabled=True, not yet
    reconciled).
12. Session state reads `RUNNING` once
    `effective_configuration_version == desired.configuration_version`
    (real reconciliation evidence, Checkpoint 64.13 §9).
13. Scanner Progress becomes visible (Checkpoint 64.18) — status
    transitions STARTING → SCANNING, `current_instrument`/
    `current_strategy` update live, `universe_processed` advances.
14. Signals become visible on the Active Signal Monitor / Live Paper
    Operations Console signal table (Checkpoint 62.x/64.9) — IF the
    strategies produce any; absence of a signal is not itself a
    failure (see §5, Success Criteria).
15. Signal Evidence becomes visible via "Why This Signal?" (Checkpoint
    64.18/64.19) for any produced signal.
16. Risk decision (APPROVED/REJECTED) is visible on the signal row and
    in the Daily Session Report's risk_accepted/risk_rejected counts.
17. Paper execution status is visible — order/fill state per signal,
    Open/Closed Positions counts on the console (Checkpoint 64.17).
18. Telegram/Discord delivery status is visible per signal, and the
    per-channel Sent/Failed/Pending counts are visible on the console
    (Checkpoint 64.16), now including compact Key Evidence in the
    message body itself (Checkpoint 64.19).
19. Realized/Unrealized P&L become visible on the console (Checkpoint
    64.17/64.18's N+1 fix applies here).
20. Operator presses **STOP LIVE PAPER SESSION** — backend-enforced,
    idempotent (Checkpoint 64.13).
21. The Daily Session Report (`GET /reports/daily-session/`) is
    generated/queried for the session date, showing every field listed
    in §5 below.

## 3. Recommended First Session Configuration

A deliberately SMALL, conservative starting configuration — this is a
validation exercise, not a production scan:

- **Universe**: 3-5 large-cap, highly liquid NSE instruments (e.g.
  RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK) — `universe_mode=
  "SELECTED"`, never `"ALL_CONFIGURED"` for the first session.
- **Timeframe**: `5m`.
- **Strategies**: all three (`ema_crossover`, `sma_trend_filter`,
  `atr_volatility_breakout`), using their Checkpoint 64.17 conservative
  baseline defaults (12/26 EMA, 30/0.75 SMA, 14/2.0/... ATR) — never a
  custom, unvalidated parameter set for the first session.
- **Paper mode**: the only mode that exists in this codebase —
  `PaperBroker` is the sole concrete broker implementation, re-verified
  every checkpoint since 64.11.
- **Real trading guard**: `real_trading_state` is a structural constant
  `"DISABLED"` on every code path — there is no configuration flag that
  could enable it; this is architectural, not a setting to check.
- **Maximum acceptable runtime**: one full NSE cash-equity session
  (09:15-15:30 IST) for the first validation — operator may STOP
  earlier once Success Criteria (§5) are met, there is no requirement
  to run the full session.
- **Stop conditions**: operator-initiated STOP at any time (always
  safe, idempotent); OR the existing kill-switch (Checkpoint 34) if any
  unexpected behavior is observed — engaging it blocks new paper orders
  while leaving the signal/communication/observability layers running,
  exactly as already tested (Checkpoint 38's kill-switch scenario).

## 4. Expected Evidence, Logs, and Reports

What the operator should be able to point to after the first session,
each backed by a real, already-tested source (never fabricated):

- **Evidence**: `SignalEvidenceRecord` rows for every real signal
  (Checkpoint 64.18), visible via the Signal API's `evidence` field.
- **Logs**: the worker process's own stdout (unchanged, real, since
  Checkpoint 57/58) plus `WorkerRuntimeStatus.last_error_safe` for any
  safe-to-display failure text.
- **Reports**: the Daily Session Report for the session's calendar date
  (`GET /reports/daily-session/?date=YYYY-MM-DD`), showing real
  `configuration_version` for that date (Checkpoint 64.18's audit-trail
  fix), real session duration (Checkpoint 64.17's session timestamps),
  and real Telegram/Discord per-channel counts (Checkpoint 64.16).

## 5. First Session Success Criteria

Measurable, evidence-backed acceptance conditions. Per this checkpoint's
own explicit instruction, **system health is a SEPARATE question from
whether a strategy produced a signal** — a session with zero signals is
still a fully successful validation if every item below is real and
correct:

| Criterion | Real source that proves it |
|---|---|
| Dhan CONNECTED | `WorkerRuntimeStatus.watchdog_state == "HEALTHY"` |
| Token VALID | Readiness checklist "Token Validity" = READY |
| Market OPEN | Readiness checklist "Market State" = READY |
| Scanner RUNNING | `session_state == "RUNNING"` (real reconciliation) |
| Effective config matches requested | `effective_session_configuration.drift == false` |
| Scanner progress advances | `scanner_progress.universe_processed` increases across polls |
| At least one complete scan cycle | `scanner_progress.status` reaches `COMPLETED` at least once |
| No stale progress | `scanner_progress.stale == false` throughout |
| Signals, if generated, have evidence | Every `SignalRecord` this session has a matching `SignalEvidenceRecord` (for the 3 registered strategies) |
| Risk decisions persisted | `SignalRecord.risk_status` is `APPROVED` or `REJECTED` for every signal, never blank |
| Paper orders, if approved, persisted | `PaperOrderRecord` exists for every risk-APPROVED signal |
| Fills, if produced, persisted | `PaperOrderRecord.status` reflects a real broker report |
| Telegram status visible | Per-signal `telegram` status + console per-channel counts, non-`null` |
| Discord status visible | Same, `discord` |
| P&L/report generated | Daily Session Report returns 200 with real (not fabricated) totals |
| No real order API call | Mechanically unverifiable-to-violate: `PaperBroker` is the only broker implementation in the codebase (re-audited every checkpoint since 64.11) |
| real_trading_state remains DISABLED | Structural constant, re-verified by `test_real_trading_state_is_always_disabled`-class tests every checkpoint |

## 6. Validation Evidence to Capture (Never Credentials)

For the record of the first real session, capture:

- Session start/stop timestamps (`ScannerConfiguration.session_
  started_at`/`session_stopped_at`, real, UTC).
- `configuration_version` active for that session.
- Universe (the real selected instrument list), timeframe.
- Strategy `specification_version`/`code_version`/`configuration_
  version` for each active strategy.
- Worker state transitions (`WorkerRuntimeStatus.worker_state` history,
  if logged; at minimum the final state).
- Scanner progress snapshots (status transitions, final
  `universe_processed`/`signals_found`).
- Every `signal_id` produced, with its evidence fields, risk decision,
  execution state, and communication status.
- The Daily Session Report's `report_id`/`generated_at` (from
  `ReportMetadata`) for the session date.

**Never captured**: the Dhan access token, Telegram bot token, Discord
webhook URL, or any other credential — none of these are ever returned
by any endpoint in this system (re-verified by dedicated tests every
checkpoint since 64.12), and this procedure does not ask an operator to
manually copy one out for validation purposes either.
