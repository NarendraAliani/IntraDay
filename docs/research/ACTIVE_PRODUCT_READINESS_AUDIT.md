# Active Product Readiness Audit (Checkpoint 39)

## 1. What the product can actually do today

Given caller-supplied bars: evaluate `ema_crossover` deterministically, derive a
signal, communicate it (Telegram/Discord, real retry/message-ID logic,
fake providers in tests), risk-gate it (13 real checks now, up from
10), submit/fill a paper order, sync the durable ledger, reconcile
ledger vs. broker, and produce two real reports (Signal Pipeline,
Communication Delivery). All proven by passing tests, including one
genuine end-to-end scenario (Checkpoint 38) and a restart-safe dedup
proof (this checkpoint).

## 2. What still requires a human/caller trigger

Everything. There is still no scheduler, no live bar feed, and no
process that calls any of the above without a caller (today: only
tests) supplying bars and invoking `evaluate_and_submit()`.

## 3. What now runs "automatically" in a meaningful sense

Nothing new runs unattended this checkpoint. What changed is that the
building blocks a future scheduler would call are now more correct:
session-aware (holiday/weekend/closing), dedup-safe across a restart
(via the ledger, not memory), and risk-complete (per-trade-risk,
daily-trade-limit, instrument-list all real and testable, though the
per-trade-risk check remains opt-in - see Decision below).

## 4. What requires Dhan credentials

Everything broker-real: no `DhanBroker` adapter exists (Phase 1
read-only was not attempted this checkpoint - a genuine, disclosed
scope cut given the time available after session/risk/dedup work).

## 5. What requires exchange/broker approval

Real order placement, per the SEBI framework findings (Checkpoint
37-39): broker-side per-algorithm registration and an Algo-ID.

## 6. Regulatory uncertainties

SEBI's exact technical provisions (Algo-ID format, static-IP
enforcement mechanics, 2FA specifics) remain `VERIFIED_SECONDARY /
PRIMARY_CONFIRMATION_PENDING` - the primary circular's full text has
not been fetched successfully in three consecutive checkpoints'
attempts (Checkpoint 37, 38, and no new attempt this checkpoint given
time constraints).

## 7. Market-data limitations

Unchanged: SAMPLE_BAR only, no live WebSocket ingestion, no automatic
promotion gate implementation (the bar-state-machine described in Part
C was NOT implemented this checkpoint - see gap register).

## 8. Execution limitations

Only `PaperBroker`, only MARKET orders proven filled, no realistic
LIMIT/SL/SL-M fill simulation, no position monitoring (target/SL/
trailing) automation.

## 9. Risk limitations

`max_per_trade_risk` enforcement is real but OPT-IN
(`enforce_per_trade_risk_limit=False` by default) - no current call
site has turned it on, because doing so would block every
`ema_crossover` order (no stop-loss) without a reviewed decision about
what that should mean. Daily-trade-limit and instrument-list checks
are real and enabled whenever a caller configures them (default:
unlimited/unrestricted).

## 10. Communication limitations

Unchanged from Checkpoint 38: no automatic trigger, retry/message-ID
are real but never exercised against real Telegram/Discord credentials
this session.

## 11. Reporting limitations

4/11 catalogue types real (Backtest, Market Data Quality, Communication
Delivery, Signal Pipeline). The remaining 7 (Execution/Order/Trade/
Position/Risk-Block/Reconciliation/EOD reports Part M asks for) were
NOT built this checkpoint - correctly named as a P3 priority per the
user's own stated priority order, deferred in favor of P0/P1 work.

## 12. Frontend limitations

Zero frontend files touched this checkpoint (third consecutive
checkpoint with no frontend work) - explicitly deferred per the user's
own P3 priority ranking.

## 13. Observability limitations

No metrics/counters infrastructure was built this checkpoint (Part L)
- correctly named P1 in the user's priority order but not reached
given the P0 session/risk/dedup work took priority within this
session's time.

## 14. Security concerns

No new credential handling was introduced. Repo-wide secret grep clean
(see final report).

## 15. Exact next blockers

1. No scheduler exists - the single highest-value next step (unchanged
   conclusion from Checkpoint 38, still true).
2. No live market-data ingestion exists - blocks any claim of
   "automatic" beyond what a human-triggered test proves.
3. No Dhan adapter exists at all, even read-only.

## Decision record for this checkpoint (see ARCHITECTURE_DECISIONS.md for the full entries)

- `SessionStatus` extended to 5 states (added `CLOSING`, `HOLIDAY`) -
  `is_trading_day()` closes Checkpoint 23's own documented "no holiday
  calendar" limitation for calendar year 2026 specifically
  (`VERIFIED_SECONDARY`, not primary-confirmed against nseindia.com,
  which timed out on fetch this session).
- Risk engine gained 3 new checks (instrument allow/deny,
  daily-trade-limit, per-trade-risk) - the first two are unconditionally
  active (default = unrestricted); per-trade-risk is opt-in
  (`enforce_per_trade_risk_limit`, default `False`) to avoid silently
  breaking the entire tested active loop built across Checkpoints
  36-38, which is built on `ema_crossover` (no stop loss).
- `DjangoPaperLedgerRepository.load_processed_signal_ids()` gives any
  future scheduler a restart-safe dedup set from real persisted state,
  proven end-to-end.
