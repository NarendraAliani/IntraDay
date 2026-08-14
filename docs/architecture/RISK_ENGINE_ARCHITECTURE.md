# Risk Engine Architecture

Checkpoint 34 Part 10/11/13. The first real risk-gating engine and kill
switch this platform has ever had — Checkpoint 33's audit found every
prior "kill switch" reference was documentation/prose only, and
`trading_engine/risk_engine/` was 8 lines of scaffolding.

## Scope, stated honestly

This is the **minimal genuine** risk engine required for the paper
trading lifecycle (Part 10's own scoping) — not the full risk-engine
gap list `docs/architecture/PRODUCT_READINESS_GAP_ANALYSIS.md` Part 10
named (no per-symbol/sector exposure limits, no volatility halt, no
spread/liquidity checks, no repeated-loss circuit breaker beyond the
daily-loss limit). Every control implemented is real and enforced —
nothing here is a placeholder pretending to gate risk.

## What is implemented

`trading_engine/risk_engine/evaluator.py::evaluate_order_risk()` — a
pure function (no I/O, mirrors `domain/market_data/aggregation.py`'s
own discipline), evaluated in this **fixed, documented order** (the
first failing check's reason is returned; nothing "warns" or partially
approves):

1. **Kill switch** — checked first, unconditionally overrides
   everything else.
2. **Market session requirement** — rejects if the session is not open.
3. **Strategy activation requirement**.
4. **Stale-data rejection**.
5. **Duplicate-order protection** (idempotency key already submitted).
6. **Duplicate-order protection** (instrument already has a
   pending/open order).
7. **Maximum daily loss** (`RiskLimits.max_intraday_loss`, reused
   verbatim from Checkpoint 5's domain contract).
8. **Maximum position size** (`RiskLimits.max_position_size`).
9. **Maximum total exposure**.
10. **Maximum concurrent positions**.

Every decision is an explicit `OrderRiskDecision` — `outcome`
(`RiskDecisionOutcome.APPROVED`/`REJECTED`, reused verbatim from
Checkpoint 5), `reason_code` (`RiskRejectionReason`, required when
rejected, forbidden when approved — enforced by the dataclass's own
`__post_init__`), `explanation`, `evaluated_at`, and
`risk_configuration_version` — fully auditable, never a bare boolean.

**Reused, not reinvented**: `RiskLimits`, `RiskDecisionOutcome`,
`TradingHaltStatus`/`TradingHaltState` all come from
`domain/risk/contracts.py` (Checkpoint 5) — that file's own docstring
explicitly deferred implementation to "`trading_engine/risk_engine` in
a later checkpoint." This is that checkpoint.

## Kill switch

`control_plane`'s "binary, supervisory authority" (Checkpoint 2 §10) is
now real:

- **Persistent state**: `KillSwitchState` (Django model, singleton,
  `get_or_create(pk=1)`) — `enabled`, `reason`, `actor_username`,
  `changed_at`.
- **Audit**: every engage AND reset writes a new `AuditLogEntry`
  (Checkpoint 12's existing append-only trail) — history is never
  deleted or overwritten, only added to.
- **Explicit reset action**: `reset()` is a distinct operation from
  `engage()`, both requiring the same RBAC capability.
- **Role/capability protection**: reuses the existing
  `configuration.activate` capability (`IsConfigurationOperator`) —
  no new capability token was introduced (Part 11's requirement is
  satisfied by reuse, per this project's non-redundancy discipline).
  Reading status requires only `configuration.read`.
- **Prevents new order submission**: `evaluate_order_risk()`'s check
  #1 rejects every order with `KILL_SWITCH_ENGAGED` while halted —
  mechanically proven, not merely documented
  (`test_kill_switch_engaged_never_reaches_the_broker`).
- **API**: `GET/POST /api/v1/config/kill-switch/{,engage/,reset/}`.
- **LIVE behavior (designed, NOT enabled)**: the same
  `TradingHaltState`/kill-switch mechanism is the intended authority
  for a future live-trading path too — `evaluate_order_risk()` is
  broker-neutral (never imports `PaperBroker` or any Dhan type), so
  wiring a future `DhanBroker` through the same
  `PaperTradingService`-shaped orchestration would inherit kill-switch
  protection automatically. **No live execution capability exists
  anywhere in this codebase — this is a design note, not an
  implementation.**

## Reconciliation

`control_plane/reconciliation/` — pure, broker-neutral comparison
functions (`reconcile_orders`/`reconcile_trades`/`reconcile_positions`/
`reconcile_funds`), never mutating anything (Part 13's explicit
"detect, classify, report, audit — no automatic corrective action").

Seven divergence types (`DivergenceType`): `MISSING_LOCALLY`,
`MISSING_AT_BROKER`, `QUANTITY_MISMATCH`, `STATUS_MISMATCH`,
`PRICE_MISMATCH`, `POSITION_MISMATCH`, `FUNDS_MISMATCH`. This
checkpoint's concrete broker source is `PaperBroker` — the exact same
reconciliation contract is intended to be reused, unchanged, once a
real Dhan adapter exists (it depends only on the domain-neutral
`BrokerOrderStatusReport`/`Trade`/`Position`/`Funds` shapes, never on
`PaperBroker` itself).

## Orchestration order (non-bypassable, mechanically proven)

```
kill switch check
      -> risk engine evaluation (evaluate_order_risk)
            -> BrokerGateway.submit_order()
```

`application/services/paper_trading.py::PaperTradingService.submit_order()`
is the ONE place this ordering happens. `tests/unit/architecture/
test_paper_trading_architecture_fitness.py` proves this structurally
(source-order inspection, not just runtime behavior) — a future edit
that silently reorders the two calls fails immediately.

## What remains missing (honest, per `PRODUCT_READINESS_GAP_ANALYSIS.md`)

Per-symbol/sector exposure limits, price-band/liquidity/spread checks,
volatility halt, a repeated-loss circuit breaker distinct from the flat
daily-loss limit, maximum order/modification frequency, end-of-day
forced exit (this checkpoint's `PaperBroker.force_expire_end_of_session()`
handles PENDING orders, but nothing calls it on a schedule yet), and
emergency square-off (closing OPEN positions, not just rejecting new
orders) are all still unimplemented.
