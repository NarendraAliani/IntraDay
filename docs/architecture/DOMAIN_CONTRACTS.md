# DOMAIN_CONTRACTS.md

Authoritative documentation for the 14 canonical shared-kernel domain
contracts, implemented at **Checkpoint 5** as real, typed, tested Python
code under `src/intraday/domain/`. Companion to
[DOMAIN_BOUNDARIES.md](DOMAIN_BOUNDARIES.md) (which contracts exist and
why) and [TECHNOLOGY_MAPPING.md](TECHNOLOGY_MAPPING.md) (how they'll
eventually be persisted/exposed) — this document is the contract-level
detail neither of those two covers.

**Scope discipline (Checkpoint 5):** these are technology-independent
value objects and interfaces only. No strategy, indicator, signal
algorithm, risk calculation, order placement, broker call, market-data
ingestion, backtest, database model, or frontend code exists anywhere in
this checkpoint. Every contract is testable without Django, PostgreSQL,
Redis, or network access — verified by `tests/unit/domain/*`.

---

## Design Principles Applied

- **Immutable**: every contract is `@dataclass(frozen=True, slots=True)`.
- **Decimal, never float**: all money/price/quantity fields are `Decimal`,
  type-checked in `__post_init__` (rejects `float`/`int` explicitly).
- **UTC-enforced**: every timestamp field is validated by
  `shared_kernel.contracts.ensure_utc`, which rejects naive datetimes and
  non-UTC offsets outright.
- **No Django/DRF/Celery/Redis/PostgreSQL/broker-SDK/HTTP imports**
  anywhere in `src/intraday/domain/` — verified by grep audit (Checkpoint
  5 validation) and mechanically enforced by `.importlinter` contracts #1
  and #2.
- **Broker-neutral**: no Dhan (or any broker) terminology, token, or
  enum value appears in any contract.
- **Intraday-only, cash-equity-only**: `InstrumentType` contains exactly
  `EQUITY` and `INDEX` (reference-only, never tradable) — no
  `FUTURE`/`OPTION` member exists, verified by a dedicated test
  (`test_instrument_type_enum_has_no_derivative_members`).

---

## Domain Contract Review Matrix

| Contract | Purpose | Owner (bounded context that primarily writes it) | Dependencies | Persistence? | API? | Frontend? | Implemented? |
|---|---|---|---|---|---|---|---|
| `shared_kernel` | Identifiers, `Version`, `Exchange`, `Side`, `Timeframe`, `Price`, `Quantity`, `ensure_utc` | Shared — no single owner | None (stdlib only) | Not yet (Checkpoint 6+) | Not yet | Not yet | ✅ |
| `instrument` | Canonical tradable/reference instrument identity | `infrastructure/market_data_providers` (registers), all contexts (read) | `shared_kernel` | Not yet | Not yet | Not yet | ✅ |
| `universe` | Versioned tradable-universe membership | `research` (defines), `trading_engine` (checks) | `shared_kernel`, `instrument` | Not yet | Not yet | Not yet | ✅ |
| `market_data` | `Bar`, `Quote` — canonical OHLCV/tick shape | `infrastructure/market_data_providers` | `shared_kernel`, `instrument` | Not yet | Not yet | Not yet | ✅ |
| `feature` | Computed feature output shape | `signal_intelligence/feature_engine` | `shared_kernel`, `instrument` | Not yet | Not yet | Not yet | ✅ |
| `strategy` | Strategy identity, version, maturity state | `research` (spec), `trading_engine` (registry) | `shared_kernel` | Not yet | Not yet | Not yet | ✅ |
| `signal` | Candidate trading decision | `signal_intelligence/signal_generation` | `shared_kernel`, `instrument` | Not yet | Not yet | Not yet | ✅ |
| `risk` | Risk limits, risk decisions, halt state | `trading_engine/risk_engine`, `control_plane/kill_switch` | `shared_kernel` | Not yet | Not yet | Not yet | ✅ |
| `portfolio` | Aggregate intraday exposure snapshot | `trading_engine/portfolio_management` | `shared_kernel`, `instrument` | Not yet | Not yet | Not yet | ✅ |
| `order` | Risk-approved execution request | `trading_engine/order_management` | `shared_kernel`, `instrument` | Not yet | Not yet | Not yet | ✅ |
| `position` | Point-in-time exposure snapshot | `trading_engine/position_lifecycle` | `shared_kernel`, `instrument` | Not yet | Not yet | Not yet | ✅ |
| `trade` | Completed, closed round-trip outcome | `trading_engine/execution_management` | `shared_kernel`, `instrument` | Not yet | Not yet | Not yet | ✅ |
| `broker` | Broker-neutral capability `Protocol` | `trading_engine/broker_abstraction` | `shared_kernel`, `order`, `position` | N/A (interface) | Not yet | Not yet | ✅ (structural only) |
| `session` | One exchange's trading session shape | `trading_engine/session_management` | `shared_kernel` | Not yet | Not yet | Not yet | ✅ |

All 14 are implemented at Checkpoint 5. No contract was deferred, and none
was added beyond the approved 14 — the shared kernel remains exactly the
size approved at Checkpoint 2/3.

---

## Contract-by-Contract Detail

### 1. `shared_kernel` — `src/intraday/domain/shared_kernel/contracts.py`

- **Purpose**: primitives referenced by 2+ bounded contexts.
- **Contents**: `InstrumentId`/`StrategyId`/`SignalId`/`OrderId`/`PositionId`/`TradeId` (str `NewType`s), `Version`, `Exchange` (NSE/BSE), `Side` (BUY/SELL), `Timeframe` (TICK..1d), `Price`, `Quantity`, `ensure_utc()`.
- **Invariants**: `Version.value` non-empty; `Price`/`Quantity.amount` must be `Decimal` and positive (non-negative for `Price`); `ensure_utc` rejects naive/non-UTC datetimes.
- **Must NOT know**: anything about a specific bounded context, persistence, or transport.
- **Future consumers**: every other domain contract; eventually `application/config_schema` (for `Version` fields) and `infrastructure/persistence` (repository interfaces).
- **Versioning**: `Version` itself is the versioning primitive — no meta-versioning needed.

### 2. `instrument` — `src/intraday/domain/instrument/contracts.py`

- **Purpose**: canonical, broker-neutral identity of a tradable or reference instrument.
- **Identity**: `instrument_id` (derived via `make_instrument_id(exchange, symbol)` — deterministic, not a broker token).
- **Required fields**: `instrument_id`, `symbol`, `exchange`, `instrument_type`, `trading_status`, `price_tick_size`.
- **Optional fields**: `lot_size` (defaults to 1).
- **Invariants**: non-empty symbol; positive `price_tick_size`/`lot_size`; `is_tradable` is `True` only for `EQUITY` + `ACTIVE`.
- **Must NOT know**: Dhan's or any broker's token/scrip-code scheme.
- **Future consumers**: `market_data`, `signal`, `order`, `position`, `trade`, `universe`, and eventually `infrastructure/market_data_providers`'s normalization layer.
- **Frontend-configurable (future)**: instrument master browsing is a read surface, not user-editable — no fields flagged for future frontend forms here.

### 3. `universe` — `src/intraday/domain/universe/contracts.py`

- **Purpose**: an already-decided, versioned tradable-universe membership list. No screening algorithm.
- **Identity**: `universe_id` + `version`.
- **Required fields**: `universe_id`, `version`, `exchange`; `members` defaults to empty.
- **Invariants**: non-empty `universe_id`; no duplicate `instrument_id` across members.
- **Must NOT know**: how membership was decided (that's a research algorithm, later checkpoint).
- **Future consumers**: `research/backtesting` (universe-at-a-point-in-time), `trading_engine/risk_engine` (live eligibility check).
- **Frontend-configurable (future)**: universe composition will likely become an operator-editable config surface (`config/universe`) — flagged for future `application/config_schema` binding.

### 4. `market_data` — `src/intraday/domain/market_data/contracts.py`

- **Purpose**: canonical `Bar` (OHLCV) and `Quote` (tick) shapes, identical across backtest/paper/live.
- **Identity**: no independent identity — a `Bar`/`Quote` is identified by `(instrument_id, timeframe, timestamp)` as a compound key, not a surrogate ID.
- **Required fields (Bar)**: `instrument_id`, `timeframe`, `timestamp`, `open`, `high`, `low`, `close`, `volume`. **Optional**: `quality` (defaults `OK`).
- **Required fields (Quote)**: `instrument_id`, `timestamp`, `last_price`. **Optional**: `bid`/`ask`/`bid_quantity`/`ask_quantity`/`source`/`quality`.
- **Invariants**: UTC timestamp; positive OHLC; `low <= open,close <= high`; non-negative volume; `bid <= ask` when both present.
- **Must NOT know**: which provider/vendor supplied the data (that's `infrastructure/market_data_providers`'s normalization job).
- **Future consumers**: `signal_intelligence/feature_engine`, `research/backtesting`, `control_plane/market_data_health`.

### 5. `feature` — `src/intraday/domain/feature/contracts.py`

- **Purpose**: the OUTPUT shape of a computed feature — no indicator math.
- **Identity**: `(feature_name, feature_version, instrument_id, timeframe, timestamp)`.
- **Required fields**: all of the above plus `value`.
- **Invariants**: non-empty `feature_name`; UTC timestamp; `value` must be `Decimal`.
- **Must NOT know**: HOW the feature was computed (EMA/RSI/MACD/etc. — none implemented).
- **Future consumers**: `signal_intelligence/signal_generation`, `research/eda`.

### 6. `strategy` — `src/intraday/domain/strategy/contracts.py`

- **Purpose**: strategy identity, versioned specification metadata, and the approved 11-state maturity lifecycle enum.
- **Identity**: `StrategyIdentity.strategy_id`; a specific reproducible version is `StrategyVersion` (strategy_id + 4 version fields + timeframe + maturity_state).
- **Required fields**: see dataclass definitions above.
- **Invariants**: non-empty `strategy_id`/`name`.
- **Must NOT know**: the executable implementation — deliberately NOT represented as a dataclass (Checkpoint 2 §4: implementation is real code in `trading_engine/strategy_execution`, a later checkpoint).
- **Future consumers**: `research/strategy_specifications`, `trading_engine/strategy_registry`, `research/experiments` (lineage).
- **Frontend-configurable (future)**: strategy parameters (not modeled yet — this checkpoint only has identity/version/lifecycle, not a parameter schema) will bind to `application/config_schema` in a later checkpoint.

### 7. `signal` — `src/intraday/domain/signal/contracts.py`

- **Purpose**: a candidate trading decision — never an order or position.
- **Identity**: `signal_id`.
- **Required fields**: `signal_id`, `strategy_id`, `strategy_version`, `instrument_id`, `generated_at`, `timeframe`, `direction`, `theoretical_entry`, `theoretical_stop_loss`, `theoretical_targets`, `feature_snapshot_version`. **Optional**: `status` (defaults `PENDING`), `confidence`, `expires_at`.
- **Invariants**: UTC timestamps; `expires_at` after `generated_at`; positive entry/stop; confidence within [0,1]; stop-loss must be on the correct side of entry for the given direction; all targets positive.
- **Must NOT know**: order IDs, position IDs, fill prices — structurally verified by `test_signal_has_no_order_or_position_fields`.
- **Future consumers**: `signal_intelligence/signal_verification`, `trading_engine/risk_engine`, `domain.order` (via risk approval, later checkpoint).

### 8. `risk` — `src/intraday/domain/risk/contracts.py`

- **Purpose**: risk-policy configuration shape, risk-decision record shape, kill-switch state shape — no evaluation logic.
- **Identity**: `RiskDecision` is identified by `(signal_id, decided_at)`; `RiskLimits`/`TradingHaltState` are configuration/state, not events.
- **Required fields**: see dataclasses above.
- **Invariants**: all `RiskLimits` values positive; `RiskDecision.reasons` mandatory when `REJECTED`; `TradingHaltState.reason` mandatory when `HALTED`.
- **Must NOT know**: HOW risk is evaluated (`trading_engine/risk_engine`, later checkpoint) or WHAT triggers a halt (`control_plane/kill_switch`, later checkpoint).
- **Future consumers**: `trading_engine/risk_engine`, `control_plane/kill_switch`, `control_plane/audit`.
- **Frontend-configurable (future)**: `RiskLimits` fields are explicitly named as future `config/risk` + `application/config_schema` targets (Checkpoint 3 §13).

### 9. `portfolio` — `src/intraday/domain/portfolio/contracts.py`

- **Purpose**: aggregate intraday exposure snapshot — broker-neutral, no account sync.
- **Identity**: a `PortfolioSnapshot` is identified by `as_of` (point-in-time); `ExposureEntry` by `instrument_id` within a snapshot.
- **Required fields**: `as_of`; `exposures` defaults to empty tuple.
- **Invariants**: UTC `as_of`; no duplicate `instrument_id` within one snapshot; positive quantity/average_price per entry.
- **Must NOT know**: broker account IDs, margin details, or how the snapshot was assembled.
- **Future consumers**: `trading_engine/portfolio_management`, `trading_engine/risk_engine` (position-size limit checks).

### 10. `order` — `src/intraday/domain/order/contracts.py`

- **Purpose**: `OrderIntent` — a risk-approved execution request, broker-neutral.
- **Identity**: `order_id`.
- **Required fields**: `order_id`, `instrument_id`, `side`, `quantity`, `order_type`, `time_in_force`, `strategy_id`, `created_at`, `idempotency_key`. **Optional**: `status` (defaults `PENDING`), `signal_id`, `limit_price`, `trigger_price`.
- **Invariants**: UTC `created_at`; positive quantity; `limit_price` required for `LIMIT`; `trigger_price` required for `SL`/`SL-M`; `idempotency_key` mandatory and non-empty (duplicate-submission prevention).
- **Must NOT know**: Dhan's (or any broker's) order-type/status vocabulary.
- **Future consumers**: `trading_engine/order_management`, `trading_engine/broker_abstraction`, `domain.broker.BrokerGateway.submit_order`.

### 11. `position` — `src/intraday/domain/position/contracts.py`

- **Purpose**: point-in-time exposure snapshot for one instrument — a value, not a calculator.
- **Identity**: `position_id`.
- **Required fields**: `position_id`, `instrument_id`, `direction`, `quantity`, `average_entry_price`, `realized_pnl`, `unrealized_pnl`, `opened_at`, `status`. **Optional**: `closed_at`.
- **Invariants**: UTC timestamps; `closed_at >= opened_at`; positive quantity/average_entry_price; `closed_at` required iff `status is CLOSED`.
- **Must NOT know**: HOW P&L is computed (no arithmetic in this dataclass) or square-off timing logic.
- **Future consumers**: `trading_engine/position_lifecycle`, `trading_engine/square_off`, `control_plane/reconciliation`.

### 12. `trade` — `src/intraday/domain/trade/contracts.py`

- **Purpose**: a completed, closed round-trip — the settled fact separating "was the strategy wrong?" from "was execution poor?" (Checkpoint 2 §5).
- **Identity**: `trade_id`.
- **Required fields**: `trade_id`, `strategy_id`, `instrument_id`, `direction`, `order_ids`, `entry_price`, `exit_price`, `quantity`, `realized_pnl`, `opened_at`, `closed_at`. **Optional**: `signal_id`, `position_id`.
- **Invariants**: UTC timestamps; `closed_at >= opened_at`; at least one `order_id`; positive entry/exit price and quantity.
- **Must NOT know**: trade-calculation logic (P&L arithmetic happens in `trading_engine/execution_management`, later checkpoint).
- **Future consumers**: `signal_intelligence/signal_verification` (indirectly, via comparison), `reports/*`, `control_plane/reconciliation`.

### 13. `broker` — `src/intraday/domain/broker/contracts.py`

- **Purpose**: the broker-neutral `Protocol` interface (`BrokerGateway`) infrastructure adapters implement; plus `BrokerOrderStatusReport`.
- **Identity**: N/A — this is an interface, not an entity.
- **Required members**: `connection_state`, `submit_order`, `cancel_order`, `modify_order`, `get_order_status`, `get_positions` — all stub bodies (`...`), verified by `test_broker_gateway_is_structural_only`.
- **Invariants** (on `BrokerOrderStatusReport`): UTC `reported_at`; non-negative `filled_quantity`; positive `average_fill_price` when provided.
- **Must NOT know**: Dhan (or any broker) specifics, HTTP, WebSockets, credentials — verified by the Checkpoint 5 forbidden-import grep audit.
- **Future consumers**: `infrastructure/brokers/dhan` (implements), `trading_engine/broker_abstraction` (consumes).

### 14. `session` — `src/intraday/domain/session/contracts.py`

- **Purpose**: one exchange's trading-session shape for one calendar date — no calendar service.
- **Identity**: `(session_date, exchange)`.
- **Required fields**: `session_date`, `exchange`, `market_open`, `market_close`, `square_off_deadline`, `status`.
- **Invariants**: UTC instants; `market_close > market_open`; `square_off_deadline` within `[market_open, market_close]` (Rule 5.4 enforcement).
- **Must NOT know**: the NSE/BSE holiday calendar or how open/close times are determined (later checkpoint).
- **Future consumers**: `trading_engine/session_management`, `trading_engine/square_off`, `research/backtesting` (session-aware simulation).

---

## Signal / Order / Position / Trade Relationship (implemented)

```
Signal (candidate)          — domain.signal.Signal
    ↓ risk-approved
Order (request)              — domain.order.OrderIntent
    ↓ submitted via BrokerGateway, filled
Position (exposure)          — domain.position.Position
    ↓ closed
Trade (settled outcome)      — domain.trade.Trade, links order_ids + optional signal_id/position_id
```

No shared fields leak between Signal and Order/Position — verified by
`test_signal_has_no_order_or_position_fields`. `Trade.order_ids` is the
only cross-contract linkage field, by design (Checkpoint 2 §5).

## Strategy Contract vs. Strategy Runtime (implemented)

`StrategyIdentity` + `StrategyVersion` are the only strategy-related
dataclasses. There is no `StrategyRuntime` or `StrategyImplementation`
dataclass — deliberately, per Checkpoint 2 §4: the executable
implementation is real Python code in `trading_engine/strategy_execution`,
not representable as an immutable value object. `StrategyMaturityState`
is the shared vocabulary; no transition-rule logic exists in this
checkpoint.

## Broker-Neutral Contract (implemented)

`BrokerGateway` is a `typing.Protocol` with six members, all stub bodies.
No import of any broker SDK, `requests`, or `httpx` exists in
`domain/broker/contracts.py` or anywhere in `src/intraday/domain/` —
verified by grep audit during Checkpoint 5 validation.

## Intraday-Only / F&O-Exclusion Validation (implemented)

`InstrumentType` contains exactly `EQUITY` and `INDEX` (non-tradable
reference only). A dedicated test
(`test_instrument_type_enum_has_no_derivative_members`) asserts the enum's
member set equals `{"EQUITY", "INDEX"}` and is disjoint from a forbidden
set including `FUTURE`, `OPTION`, `EXPIRY`, `STRIKE`. No `session`,
`instrument`, or any other contract contains overnight/carry-forward/
delivery-settlement fields.

---

## What Was Deliberately NOT Implemented at Checkpoint 5

- Strategy runtime/implementation code
- Indicator/feature computation logic (EMA, RSI, MACD, etc.)
- Risk evaluation logic
- Order placement / broker HTTP calls
- Market-data ingestion / WebSocket clients
- Backtesting engine
- Database models / migrations
- API endpoints exposing these contracts
- Frontend screens or generated TypeScript types for these contracts

These are all explicitly deferred to later checkpoints per the roadmap.
