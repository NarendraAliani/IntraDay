# Active Product Operating Model (Checkpoint 36 Part 22)

Defines the intended lifecycle stages for operating IntraDay as a PAPER
trading product. This describes the **target operating model** — the
sequence an operator would follow — and is explicit about which stages
already have real, tested implementation behind them versus which are
still manual or undesigned. It is not a claim that all stages are
automated; see the `Automation status` column.

| Stage | What happens | Automation status |
|---|---|---|
| **STARTUP** | Backend process starts; Django app boots; `PaperTradingService`/`PaperBroker` composition root (`infrastructure/api/paper_trading_runtime.py`) constructs a fresh in-process `PaperBroker` bound to `DjangoPaperLedgerRepository`. | `IMPLEMENTED_AND_TESTED` — proven by restart-recovery tests (Checkpoint 35: a fresh repository instance reads back previously-persisted ledger state). |
| **PRE-MARKET** | Operator would confirm: kill switch is `ACTIVE` (not accidentally `HALTED` from a prior session), funds/positions reconcile with the last persisted snapshot, instrument master is current. | `PARTIALLY_IMPLEMENTED` — the read APIs exist (Checkpoint 35: orders/trades/positions/funds GET endpoints); nothing automatically runs a pre-market checklist or blocks MARKET OPEN if checks fail. Manual today. |
| **MARKET OPEN** | Orders may be submitted through `PaperTradingService.submit_order()`, either manually (order-entry form, Checkpoint 35) or, if a strategy is active, via `PaperSignalExecutionService.evaluate_and_submit()` (this checkpoint) given a caller-supplied bar series. Every submission passes risk-engine gating (kill switch, duplicate-order check, exposure limits) before reaching the broker. | `IMPLEMENTED_BUT_NOT_VALIDATED` for the strategy path (see `ACTIVE_PRODUCT_GAP_REGISTER.md` P0 — no automatic bar feed exists yet, so this stage's strategy-driven half only runs when a caller supplies bars, which today means tests only). Manual order entry is `IMPLEMENTED_AND_TESTED`. |
| **INTRADAY MONITORING** | Operator watches open orders/positions/funds via the frontend monitor tables; ledger stays synced after every mutation (`sync_snapshot()`, atomic). | `IMPLEMENTED_AND_TESTED` for state correctness; `PARTIALLY_IMPLEMENTED` for at-a-glance operational visibility (no dedicated dashboard beyond raw tables — see gap register P1). |
| **RISK EVENT HANDLING** | Kill switch activation must block *new* order submission immediately. | `IMPLEMENTED_AND_TESTED` — proven for both manually-submitted and strategy-generated orders (this checkpoint's `test_kill_switch_blocks_strategy_generated_orders_too`). Force-closing *already open* positions on kill-switch activation is `BLOCKED` (see gap register P0) — deliberately not implemented without a reviewed design. |
| **END OF SESSION** | Open DAY orders should expire; ledger should reflect final state for the day. | `PARTIALLY_IMPLEMENTED` — `PaperBroker.force_expire_end_of_session()` works and is reachable via a manual API call (Checkpoint 35); nothing triggers it automatically at session close. Operator must remember to call it. |
| **SHUTDOWN / RECOVERY** | Process may stop and restart at any point; the durable ledger (not in-memory broker state) is the source of truth on restart. | `IMPLEMENTED_AND_TESTED` — this is the one lifecycle property with the strongest evidence in the whole system (explicit restart-recovery test, Checkpoint 35), because `PaperBroker` itself is intentionally stateless-on-restart by design and the ledger is the durable projection. |

## What this model deliberately does not claim

- It does not claim MARKET OPEN's strategy-driven half runs unattended —
  it does not, and this document says so plainly rather than implying
  automation that doesn't exist.
- It does not define a LIVE-trading version of any stage. `TRADING_MODE`
  remains PAPER-only system-wide; a LIVE operating model is out of scope
  until LIVE trading itself is authorized, which it is not.
- It does not introduce Docker or any new deployment/orchestration
  tooling — Docker remains permanently deferred per every prior
  checkpoint's invariant.

## Relationship to existing documents

This document sits above `PAPER_TRADING_ARCHITECTURE.md` (the
component-level design) and `RUNTIME_ARCHITECTURE_DECISION.md`
(Checkpoint 32's process-composition decision) — it describes the
*sequence of operator actions and system states* those documents already
implement, not new architecture. Where a stage above is
`PARTIALLY_IMPLEMENTED` or `BLOCKED`, the corresponding row in
`ACTIVE_PRODUCT_GAP_REGISTER.md` is the authoritative detail; this
document intentionally does not duplicate that evidence.
