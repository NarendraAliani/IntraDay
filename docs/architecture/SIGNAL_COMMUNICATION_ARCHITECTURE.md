# Signal Communication Architecture (Checkpoint 37)

## Governing principle

**SIGNAL TRUTH != EXECUTION TRUTH.** A strategically audited signal is a
valid product event whether or not an order is ever placed. This is
enforced structurally, not by convention: `SignalCommunicationService.
communicate()` never requires an order, a risk decision, or a broker
fact as an argument.

## Lifecycle

```
Market Data -> Strategy -> Signal Generated -> Signal Validation
                                                      |
                                                      v
                                      SIGNAL COMMUNICATION EVENT
                                       (VALIDATED_SIGNAL, always sent)
                                                      |
                                                      v
                                      Risk / Execution Decision
                                        /                    \
                                 APPROVED                  BLOCKED
                                    |                          |
                                    v                          v
                           Order Submitted          VALIDATED_SIGNAL_
                                    |                EXECUTION_BLOCKED
                                    v                (block_reason set)
                           Execution Outcome
                          (FILLED/PARTIAL/REJECTED)
                                    |
                                    v
                         Outcome Communication Event
```

## Components (Part 3's required vocabulary, and where each lives)

| Concept | Module | Notes |
|---|---|---|
| `SignalCommunicationEvent` | `communication/contracts/signal_communication.py` | One point-in-time lifecycle fact. `event_id` is the dedup unit. |
| `SignalCommunicationContext` | same | Every field a template may render; optional fields are genuinely optional, never fabricated. |
| `CommunicationChannel` | same | `TELEGRAM`, `DISCORD` today. |
| `CommunicationProvider` | `application/services/signal_communication.py` (Protocol) | Implemented by `infrastructure/communication/providers.py`'s `TelegramCommunicationProvider`/`DiscordCommunicationProvider`. |
| `NotificationRouter` | `application/services/signal_communication.py` | Fans one event out to every configured/enabled provider; records every attempt via `CommunicationLedger`. |
| `MessageTemplate` (rendering) | `communication/contracts/templates.py` | 18 pure-function renderers, versioned (`TEMPLATE_VERSION = "v1"`). |
| `DeliveryAttempt` / `DeliveryStatus` | `communication/contracts/signal_communication.py` | One row per provider per event. |
| `CommunicationLedger` | `application/services/signal_communication.py` (Protocol), implemented by `infrastructure/persistence/communication_ledger_repository.py` | Durable "was this signal communicated?" answer. |

## Why `communication` (not `domain`) hosts the contracts

`communication` is already an established top-level bounded context
(`.importlinter`'s own documented layout, Checkpoint 3), a sibling of
`trading_engine`/`signal_intelligence`/`control_plane` — not a
sub-package of `domain`. The new contracts live under
`communication/contracts/`, following the exact placement the existing
`connectivity.py` contract already established (Checkpoint 22), never
a new `domain.communication` package that would misrepresent the
codebase's own layering.

## Signal vs. execution status (Part 4)

- **Signal status**: `domain.signal.SignalStatus` (Checkpoint 5) —
  unchanged, unmodified. `PENDING`/`VALIDATED`/`REJECTED`/`EXPIRED`/
  `CONSUMED`.
- **Execution status**: `ExecutionStatus` (this checkpoint) — a value
  DERIVED by `derive_execution_status()` from the existing
  `RiskDecisionOutcome` (Checkpoint 5) and `OrderStatus` (Checkpoint
  34), never a third, independently-stored enum that could drift out
  of sync with either. `NOT_EVALUATED` when no risk decision exists
  yet; `BLOCKED` on risk rejection (regardless of any order status);
  otherwise mapped from the broker-neutral `OrderStatus`.

## Deduplication vs. legitimate lifecycle update (Part 6/7)

The idempotency key is `(signal_id, event_id, channel)`. A caller
re-dispatching the EXACT SAME `SignalCommunicationEvent` object (a
retry of the same lifecycle fact) is deduplicated —
`DeliveryStatus.SKIPPED_DUPLICATE`, no second visible message. A
DIFFERENT event for the same `signal_id` (e.g. `VALIDATED_SIGNAL` then,
later, `ORDER_FILLED`) is never deduplicated — it is a genuinely new
fact about the signal's life, and both messages are expected to be
visible. Proven by
`tests/unit/communication/test_signal_communication_engine.py::test_scenario_j_same_signal_same_event_is_not_double_communicated`.

## Integration with the paper-trading bridge (Checkpoint 36)

`PaperSignalExecutionService` (Checkpoint 36) optionally accepts a
`communication: SignalCommunicationService | None` constructor
argument. When present:

1. Immediately after a real `StrategySignal` is derived (before risk
   evaluation), a `VALIDATED_SIGNAL` event fires unconditionally.
2. After `PaperTradingService.submit_order()` returns, a follow-up
   event fires based on the ACTUAL outcome — `
   VALIDATED_SIGNAL_EXECUTION_BLOCKED` (risk rejected, e.g. kill
   switch), `ORDER_SUBMITTED`/`ORDER_FILLED`/`PARTIAL_FILL`/
   `ORDER_REJECTED` (order reached the broker).

This is the concrete demonstration required by Part 6's scenarios — see
`tests/unit/application/services/test_paper_signal_execution_communication.py`:
`test_scenario_d_kill_switch_still_communicates_the_signal_and_the_block_reason`
proves the kill switch stops the order, never the communication;
`test_scenario_g_filled_signal_communicates_validated_then_filled`
proves the full two-message lifecycle on a successful fill.

Communication is OPTIONAL and additive — omitting it entirely
(`communication=None`, the Checkpoint 36 default) reproduces
Checkpoint 36's exact original behavior, proven by
`test_no_communication_service_configured_does_not_break_the_bridge`.

## What is composed but NOT wired to anything live (honest limitation)

`get_signal_communication_service()`
(`infrastructure/api/paper_trading_runtime.py`) builds a real,
fully-composed `SignalCommunicationService` from actual Telegram/
Discord settings (reusing `TelegramSettingsService`/
`DiscordSettingsService`'s existing `effective_credentials()`/
`effective_webhook_url()`, Checkpoint 22) and the durable
`DjangoCommunicationLedgerRepository`. **Nothing in the current API
surface calls this factory.** This mirrors Checkpoint 36's own
deliberate deferral of `PaperSignalExecutionService`'s automatic
trigger — wiring either into a live/scheduled pathway is a separate,
reviewed decision (staleness handling, market-data-quality enforcement
per Part 8's own warning against silently promoting `SAMPLE_BAR` data),
not a consequence of the composition existing. See
`ACTIVE_PRODUCT_GAP_REGISTER.md`.

## What is NOT implemented (named honestly, not hidden)

- **No automatic retry** for a `FAILED` delivery attempt — `retry_count`
  is a real, persisted field, but nothing increments it.
- **No provider `provider_message_id` capture** — Telegram/Discord's
  actual response bodies (which contain a real message ID) are not
  parsed by the existing thin HTTP clients; the field exists in the
  contract but is always `None` in practice.
- **No target-hit/trailing-stop/position-closed AUTOMATIC triggers** —
  the `TARGET_1_HIT`/`TARGET_2_HIT`/`TARGET_3_HIT`/`STOP_LOSS_HIT`/
  `TRAILING_STOP_UPDATED`/`POSITION_CLOSED` templates exist and are
  rendering-tested, but nothing in this codebase currently monitors an
  open paper position against its (non-existent, for `ema_crossover`)
  target/stop-loss levels to fire them. This is consistent with
  `ema_crossover` genuinely not computing those levels (see
  `docs/research/STRATEGY_TO_PAPER_SELECTION.md`) — a strategy that
  did compute them would still need a NEW position-monitoring
  capability this checkpoint did not build.
- **No WhatsApp adapter** — explicitly out of scope per Checkpoint 37
  Part 7's own instruction ("should remain a future adapter").
