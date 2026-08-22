# Task Report

## Checkpoint

64.42 — "PAPERBROKER -> CANONICAL FILL PRODUCER". Wires the 64.41 canonical `Fill` domain
contract into `PaperBroker`'s actual execution path so every REAL fill produces one canonical
`Fill` event, additively, alongside the pre-existing `_PaperOrder`/`Position`/`Trade` mechanics
which remain unchanged. Backtest, Dhan, and frontend are deliberately untouched.

## Objective

Per the verbatim directive: identify every actual `PaperBroker` fill point, construct exactly one
`Fill` per actual execution event (never per `OrderIntent`), never replace existing order/position/
accounting structures, add a minimal retention seam, write mandatory tests, run full regression +
quality gates, document in the architecture file, and overwrite `taskReport.md`.

## Market State

2026-08-22. Market closed (Saturday). No Dhan connection attempted, no live/network activity of
any kind this checkpoint.

## Dhan State

Untouched. No Dhan file read or modified.

## Previous Checkpoint Status

64.41 (accepted): introduced `intraday.domain.execution.contracts.Fill` + `FillSource` as a
contract-only domain type — immutable, validated, 49 tests, zero producer wiring. Re-verified this
checkpoint by reading `contracts.py` fresh (reproduced above in full) before writing any producer
code, per the directive's own "do not trust taskReport.md blindly" instruction.

## PaperBroker Fill Points

Re-read `src/intraday/infrastructure/brokers/paper/broker.py` in full this checkpoint (not
assumed). Every actual fill, for every order type, funnels through the SAME single method,
`_attempt_fill()`, called from exactly 5 sites:

1. `submit_order()` — MARKET, immediate fill on submission.
2. `_maybe_fill_resting_order()` LIMIT branch — `limit_boundary=intent.limit_price` (64.40 F2).
3. `_maybe_fill_resting_order()` STOP_LOSS_MARKET branch — no boundary clamp.
4. `_maybe_fill_resting_order()` STOP_LOSS branch — `limit_boundary=intent.limit_price`.
5. `_maybe_fill_resting_order()` MARKET branch — F1 completion of a prior partial fill.

No sixth path exists. For each, `_attempt_fill` already computes `fill_quantity`, `slipped_price`
(post-slippage, post-F2-clamp), `cost` (via injected `compute_cost`), and `target_state`
(`OrderStatus.FILLED`/`PARTIALLY_FILLED`) BEFORE mutating `record`/calling
`_apply_to_position()` — these are the exact same values the new `Fill` construction reuses.

## Fill Producer Design

Exactly one `Fill(...)` construction, placed inside `_attempt_fill()`, immediately AFTER the
existing `self._transition(record, target_state, event_type)` and
`self._apply_to_position(intent, fill_quantity, slipped_price, cost)` calls. If `_attempt_fill`
returns early (insufficient funds -> REJECTED, checked before this point), no `Fill` is
constructed — proven by `test_no_fill_for_rejected_market_order_insufficient_funds`. The flow is
now exactly:

```
OrderIntent -> RiskDecision (unchanged, upstream) -> PaperBroker._attempt_fill()
    -> existing order/position mutation (unchanged)
    -> Fill(...) constructed from the SAME already-computed values
    -> appended to self._fills (additive observability)
```

## Fill ID Strategy

`fill_id=str(uuid.uuid4())` — one fresh UUID4 per actual fill event, using the SAME `uuid` import
this file already uses for `Position.position_id`/`Trade.trade_id`/`OrderEvent.event_id`. Chosen
over a deterministic composite because the directive explicitly prioritizes uniqueness over
reproducibility for Paper runtime, and UUID4 requires no new ID-generation subsystem.
`test_fill_ids_unique_across_many_fills` generates >=100 fills (a 100-quantity MARKET order split
across many `partial_fill_ratio=0.1` ticks, plus 100 separate single-share orders on a second
instrument) and asserts `len(fill_ids) == len(set(fill_ids))` — all unique, verified, not assumed.

## Order ID Relationship

`Fill.order_id = intent.order_id` — the exact `OrderIntent.order_id` from the same `record.intent`
`_attempt_fill` is already operating on. `test_fill_order_id_equals_intent_order_id` submits an
order with `order_id="ord-xyz-999"` and asserts `fill.order_id == order.order_id == "ord-xyz-999"`.

## Fill Quantity

`Fill.quantity = fill_quantity` — the exact local variable `_attempt_fill` already computed
(clamped to `min(remaining, requested-by-ratio)` or forced to the full remainder for F1
completion) and already passed into `_apply_to_position()`. Never independently recomputed.
`test_fill_quantity_and_price_equal_actual_position_update_values` proves `Fill.quantity ==
Position.quantity` for a position opened by exactly one fill.

## Fill Price

`Fill.price = slipped_price` — the exact post-slippage, post-F2-clamp `Decimal` already assigned
to `record.average_fill_price`. `test_fill_price_equals_order_report_average_fill_price` proves
`fill.price == report.average_fill_price` (the value returned via `BrokerOrderStatusReport`, the
pre-existing external observation surface).

## Fill Timestamp

`Fill.timestamp = self._clock()` — one FRESH, additional call to the same `self._clock()` this
class already uses for `OrderEvent.timestamp_utc`/`Position.opened_at`/`Trade.closed_at`.
Deliberately NOT `intent.created_at` — `test_fill_timestamp_is_utc_aware_and_not_order_created_at`
asserts `fill.timestamp != order.created_at` and `fill.timestamp.tzinfo is not None`. This is one
ADDITIONAL clock call per fill beyond what `_attempt_fill` already made — purely additive; it does
not replace, remove, or reorder any pre-existing `self._clock()` call, so no existing timestamp
value produced elsewhere in this class changes.

## Fill Source

`source=FillSource.PAPER` — explicitly assigned as a literal at the one construction site, never
inferred. `test_market_full_fill_produces_exactly_one_fill` and every other new test assert
`fill.source is FillSource.PAPER`.

## Fill Status

`status_at_fill=target_state` — the identical `OrderStatus.FILLED`/`OrderStatus.PARTIALLY_FILLED`
object `_attempt_fill` already computed and passed to `self._transition(...)` on the line
immediately above. No possible drift, because it is the same reference, not a separately derived
value. Proven directly: `test_partial_then_completion_produces_two_fills_summing_to_requested_quantity`
asserts Fill #1's `status_at_fill is OrderStatus.PARTIALLY_FILLED` and Fill #2's `is
OrderStatus.FILLED`.

## Slippage Capture

`Fill.slippage_applied = slipped_price - price`, where `price` is `_attempt_fill`'s own `price`
parameter (the pre-slippage, pre-clamp reference: the observed market price for MARKET/
STOP_LOSS_MARKET, or the stated `limit_price` for LIMIT/STOP_LOSS's limit leg). This is the exact
signed delta the execution path actually applied — never recomputed from an ambiguous later
reference. Worked and tested (`test_slippage_applied_is_signed_actual_adjustment` /
`test_slippage_applied_negative_for_sell`, BUY/SELL, 1% flat slippage on raw=100): BUY ->
`price=101.00`, `slippage_applied=+1.00`; SELL -> `price=99.00`, `slippage_applied=-1.00`. No
ambiguity or missing seam was found — `_attempt_fill`'s own `price` parameter was always the
correct, already-available pre-slippage reference, so no STOP was required.

## Transaction Cost Capture

`Fill.transaction_cost = cost` — the exact `Decimal` `_attempt_fill` already computed via the
injected `compute_cost` closure and already charged to/credited from `_available_balance`, for
THIS fill only. `test_multi_fill_order_attributes_cost_per_fill_not_per_order` injects a stateful
cost closure returning `1.00` then `2.00` on successive calls and asserts Fill #1's
`transaction_cost == 1.00`, Fill #2's `== 2.00` — proving per-fill attribution, not an order-level
total.

## Multi-Fill Behavior

`test_partial_then_completion_produces_two_fills_summing_to_requested_quantity`: qty=10,
`partial_fill_ratio=0.5` -> Fill #1 `quantity=5`, `status_at_fill=PARTIALLY_FILLED`; after the next
`record_price()` observation (F1 completion path) -> Fill #2 `quantity=5`,
`status_at_fill=FILLED`. Both share `order_id`; `fill_1.fill_id != fill_2.fill_id`;
`fill_1.quantity + fill_2.quantity == order.quantity == 10`; `fill_1.timestamp < fill_2.timestamp`
(execution order preserved, never re-sorted). `test_no_overfill_across_multiple_fills` (ratio=0.3)
independently confirms the SUM across however many fills occur always equals the requested
quantity, never more.

## Fill Retention / Observation

Chosen mechanism: a new `self._fills: list[Fill] = []` instance attribute on `PaperBroker`,
appended to in execution order inside `_attempt_fill`, exposed via a new `get_fills() -> tuple[Fill,
...]` accessor returning `tuple(self._fills)`. This is the EXACT pre-existing pattern this same
class already uses for `Trade` (`self._trades: list[Trade] = []` / `get_trades()`), chosen because
it is the smallest possible addition (one field, one accessor, zero changes to any existing method
signature), supports multiple fills per order natively (no change to `_PaperOrder`'s shape
required), and introduces no new architectural idiom. Not part of `BrokerGateway` (mirrors
`get_order_events()`'s own already-established "not part of BrokerGateway" pattern).

## Position Compatibility

`domain/position/contracts.py` and `_apply_to_position()` were NOT modified (0 diff this
checkpoint, confirmed via `git diff --stat -- src/intraday/domain/position/contracts.py` showing
no change beyond the carried-forward 64.34-era diff). `Fill` construction happens strictly AFTER
`_apply_to_position()` runs, from the same local variables — `test_fill_quantity_and_price_equal_
actual_position_update_values` is the direct proof: `fill.quantity == position.quantity` and
`fill.price == position.average_entry_price` for a position opened by exactly one fill.

## Accounting Compatibility

`domain/trade/net_pnl.py` (`compute_realized_net_pnl`, 64.37) and `domain/position/
mark_to_market.py` (`mark_position`/`position_market_value`, 64.38) were NOT touched this
checkpoint. Neither reads `self._fills`, and `Fill` has no reference to either module.

## Realized Net P&L Compatibility

Unchanged formula, unchanged call sites. `test_realized_net_pnl_unrealized_pnl_equity_unaffected_
by_fill_producer`: a BUY 10 @ 100 then SELL 10 @ 110 round trip (Decimal("2.00") flat cost per
fill) produces `trade.realized_pnl == 100.00` and `trade.realized_net_pnl == 96.00` (gross 100 -
4.00 total attributed cost) — the exact numbers this formula would have produced with no Fill
producer at all, cross-checked against the known-correct arithmetic independently of the code.

## Unrealized P&L Compatibility

Same test: `broker.get_total_unrealized_pnl() == Decimal("0")` after the position fully closes —
unaffected by the two Fill events (BUY, SELL) also produced in this same scenario.

## Equity Compatibility

Same test: `broker.get_equity() == Decimal("1000000") + Decimal("96.00") == Decimal("1000096.00")`
— `get_equity()`'s own pre-existing formula (`available_cash + open-position market value`) was
not touched and produces the identical figure whether or not `Fill`s are being observed.

## Backtest Compatibility

`src/intraday/research/backtesting/engine.py`, `execution.py`, `portfolio.py`, `cost_model.py`,
`tradeplan_execution.py`, `position_lifecycle.py` — zero new diff this checkpoint. Verified via
`git diff --stat -- src/intraday/research/backtesting/`: exactly the same 3-file (`cost_model.py`,
`portfolio.py`, `risk_gate_adapter.py`), 162-line-total diff already carried forward from BEFORE
this checkpoint (unchanged from 64.41's own reported state) — `engine.py` does not appear in the
diff at all, confirming it was never touched. No Backtest Fill producer, no unified execution
engine, no `FillBook`/`FillManager`/`ExecutionLedger`/event store was created — mechanically
confirmed by `TestScopeDiscipline.test_no_fillbook_fillmanager_executionledger_introduced`.

## Tests Added

`tests/unit/research/test_checkpoint_64_42_paper_fill_producer.py` — **23 new tests**, all passing
standalone: `poetry run pytest tests/unit/research/test_checkpoint_64_42_paper_fill_producer.py -q`
-> **23 passed**, 1 warning, 0.46s-0.47s across repeated runs. Covers directive checklist items
A-Z, AA-AD: MARKET full/partial fill, multi-fill order (shared order_id/distinct fill_id/order
preserved), Fill quantity/price matching the actual position update, LIMIT F2 boundary (BUY and
SELL), STOP_LOSS_MARKET and STOP_LOSS fills, transaction-cost-per-fill and slippage-sign capture,
UTC-aware timestamp distinct from `created_at`, `Fill.order_id == OrderIntent.order_id`, realized/
unrealized/equity unaffected, no Fill on rejection (both no-reference-price and insufficient-funds
paths), no duplicate Fill after terminal FILLED state, Fill schema unchanged from 64.41, no
FillBook/FillManager/ExecutionLedger/EventStore introduced, fill_id uniqueness across >=100 fills,
and a 2000-fill performance smoke test.

One PRE-EXISTING 64.40 test, `test_no_fill_class_exists_in_broker_module`
(`tests/unit/research/test_checkpoint_64_40_execution_correctness.py`), asserted
`not hasattr(broker_module, "Fill")` — correct at 64.40 time, but now obsolete because 64.42 is
explicitly directed to import `Fill` into `broker.py`. Updated (not deleted) to assert
`broker_module.Fill is` the canonical `intraday.domain.execution.contracts.Fill` (i.e. an IMPORT
of the existing contract, not a new locally-defined class) while still asserting no `FillEvent`/
`ExecutionReport` class exists — the meaningful invariant that test protects is preserved, only the
now-incorrect premise was corrected, with an inline comment explaining why.

## Regression Comparison

All numbers from fresh command runs this session (never copied from 64.41's report).

**Pre-implementation baseline** (re-run fresh, before writing broker.py changes):
- `test_checkpoint_64_41_fill_contract.py` + `test_checkpoint_64_40_execution_correctness.py` +
  `test_checkpoint_64_39_execution_fill_audit.py` + `test_checkpoint_64_38_paper_mark_to_market.py`
  + `test_checkpoint_64_37_net_pnl_risk_contract.py` together: FIRST run showed **1 failed, 133
  passed** — the pre-existing `test_no_fill_class_exists_in_broker_module` failure described
  above, caused by the new `from intraday.domain.execution.contracts import Fill, FillSource`
  import already added to `broker.py` at that point. After correcting that one test's now-outdated
  premise: **134 passed**, 1 warning, 4.57s.

**After implementing the Fill producer and the new test file**:
- `test_checkpoint_64_42_paper_fill_producer.py -q` -> **23 passed**, 1 warning, 0.46s-0.47s.
- `tests/unit/research/ -q` -> **400 passed**, 1 warning, 7.23s (377 pre-64.42 baseline + 23 new =
  400, exactly accounted for).
- `tests/unit/architecture/ -q` -> **52 passed**, 1 warning, 0.68s (unchanged from 64.41).
- `tests/unit/application/services/test_paper_trading.py test_paper_signal_execution.py -q` ->
  **17 passed**, 1 warning, 0.35s (unchanged from 64.41 — proves the Fill producer addition did
  not alter any Paper application-service-observable behavior).
- Full suite `poetry run pytest -q` -> **1896 passed**, 2 warnings, 408.43s (0:06:48 wall time)
  (1873 pre-64.42 baseline + 23 new = 1896, exactly accounted for). Same pre-existing, unrelated
  `PytestWarning` about test-database teardown race
  (`tests/validation/test_reference_engine_isolation.py`) as every prior checkpoint's run — a
  Postgres concurrency artifact of the local test setup, not caused by this checkpoint.

No count discrepancy, no unexplained failure, no skipped test, no pre-existing test's asserted
VALUE changed (only the one now-outdated `broker_module` `hasattr` premise, corrected as described
above, which is a test-scope correction explicitly foreseeable from the directive's own mandate to
wire `Fill` into `broker.py`, not a production-behavior regression).

## Performance

`test_two_thousand_fills_construct_quickly`: 2000 real `PaperBroker.submit_order()` calls (each
producing exactly one `Fill`) completed well under a generous 10-second smoke-test threshold — a
smoke test against pathological behavior, not a tight microbenchmark, matching the directive's own
"do not fabricate a broad benchmark" instruction. `Fill` construction inside `_attempt_fill` reuses
already-computed local variables plus one UUID4 generation and one `self._clock()` call — no
database access, no network I/O, no scan over `self._positions`/`self._orders`/`self._fills`, O(1)
per fill by direct inspection of the added code.

## Scalability

Not broadly evaluated (matches 64.41's own scope). `self._fills` is an unbounded in-memory list —
identical growth characteristic to the pre-existing `self._trades` list this pattern mirrors; no
new scalability concern introduced beyond what already existed for `Trade` accumulation.

## Security

No Dhan file read or modified. No credentials touched. No live network call made (market closed).
No frontend file touched. No new external dependency introduced (`pyproject.toml`/`poetry.lock`
untouched — only `uuid`, already imported in `broker.py`, is used). No secret, token, or credential
appears in any file created or modified this checkpoint.

## Quality Gates

All run fresh this session, exact results:
- `poetry run mypy src/` -> `Success: no issues found in 321 source files`.
- `poetry run ruff format --check .` -> initially `1 file would be reformatted` (the new test
  file's own trailing-format issue); `poetry run ruff format` applied to that one file, then
  `poetry run ruff format --check .` re-run clean -> `577 files already formatted`.
- `poetry run ruff check .` -> initially 1 finding (`B007` unused loop variable `i` in the new test
  file's fill_id-uniqueness test — renamed to `_i`, a pure style fix, no behavioral change); after
  the fix and format pass -> `All checks passed!`.
- `poetry run lint-imports` -> `Contracts: 6 kept, 0 broken.` (analyzed 386 files, 1788
  dependencies — one more dependency than 64.41's own count, from `broker.py`'s new `Fill`/
  `FillSource` import, still fully within the allowed layering — `infrastructure` importing
  `domain` is explicitly permitted).
- `poetry run python manage.py check` -> `System check identified no issues (0 silenced).`
- `poetry run python manage.py makemigrations --check --dry-run` -> `No changes detected`.
- `poetry run python manage.py spectacular --fail-on-warn` -> exit code 0 (no warnings/errors).

All seven gates clean.

## Remaining Gaps

(1) No Backtest Fill producer exists — deliberately, this checkpoint's own directive forbids it.
(2) No formal Backtest/Paper parity test suite exists comparing actual produced Fills between the
two engines (only one producer exists at all). (3) Backtest partial-exit capability remains
entirely absent. (4) `Fill` is still not consumed by any accounting/position-update logic — it
remains a pure OBSERVATION alongside the existing mechanics, exactly as directed; a future
checkpoint could make Position/Trade DERIVE from Fill, but that is explicitly out of scope here.
(5) `BacktestTrustLevel.POC` remains hardcoded — Research Readiness is still NO. (6) `Fill` has no
serialization mechanism (unchanged from 64.41, deliberately). (7) `get_fills()` is unbounded
in-memory growth with no eviction/persistence — acceptable for a Paper runtime session, not
evaluated for long-running-session memory characteristics.

## Blockers

None encountered. The slippage-adjustment value (`slipped_price - price`, using `_attempt_fill`'s
own `price` parameter as the pre-slippage reference) was cleanly available at the exact fill point
— no STOP was required. The transaction-cost value (`cost`, already computed and already charged)
was likewise unambiguous. Every field had a clear, directly-observable source at the fill point.

## Production Readiness

Still NOT production-ready (unchanged headline). This checkpoint wires a real, tested Fill
producer into ONE of two execution engines — a genuine step, but Backtest remains unwired, no
consumer reads `Fill` for accounting yet, and Live trading readiness is untouched.

## Next Checkpoint Recommendation

The symmetric next step: a Backtest -> `Fill` producer adapter (mirroring this checkpoint's exact
discipline — additive, no change to `engine.py`'s existing numerical results, one `Fill` per
actual simulated execution event), gated behind full regression parity. NOT the unified execution
engine, NOT a Fill-driven accounting rewrite of either engine — both remain later, larger-scoped
checkpoints.

## Performance Ranking

Conservative 1-10, 64.41 -> 64.42. Only scores directly evidenced by this checkpoint's actual code
change move.

| Dimension | Previous (64.41) | Current (64.42) | Change | Evidence | Missing Capability |
|---|---|---|---|---|---|
| Architecture | 8 | 8 | 0 | Producer wiring is additive integration, not a new architectural seam — the seam itself (`domain/execution/contracts.py`) already existed | Backtest producer, eventual consumer wiring |
| Risk Integration | 7 | 7 | 0 | Unchanged | — |
| Risk Policy Correctness | 7 | 7 | 0 | Unchanged | — |
| Risk Decision Ownership | 7 | 7 | 0 | Unchanged | — |
| Order Model | 6 | 6 | 0 | `OrderIntent`/`OrderStatus`/`OrderEvent` unchanged | — |
| Position Model | 8 | 8 | 0 | `Position` contract and `_apply_to_position()` unchanged | — |
| Position Lifecycle | 7 | 7 | 0 | Unchanged | — |
| Mark-to-Market | 8 | 8 | 0 | Untouched | — |
| Unrealized P&L | 8 | 8 | 0 | Untouched, proven unaffected by new test | — |
| Equity | 8 | 8 | 0 | Untouched, proven unaffected by new test | — |
| Fill Contract | 7 | 7 | 0 | Contract itself unmodified this checkpoint (correctly, per directive) | Backtest producer |
| Fill Producer | 0 | 7 | +7 | `PaperBroker` now constructs a real `Fill` at every one of its 5 fill call sites, 23 new tests, exact-value-reuse proven | Backtest producer, Live producer |
| Fill Lifecycle | 4 | 6 | +2 | Multi-fill (partial-then-complete) now genuinely observable end-to-end via `get_fills()`, not merely defined structurally | Full lifecycle including cancellation/expiry correlation to Fills |
| Order Lifecycle | 6 | 6 | 0 | Same transition table, same asymmetry | Backtest-side lifecycle representation |
| Exit Policy | 6 | 6 | 0 | Unchanged | Shared exit-reason vocabulary |
| Partial Fill | 7 (Paper)/0 (Backtest) | 8/0 | +1 (Paper) | Paper partial-fill now has an OBSERVABLE, tested Fill-level representation (`get_fills()`), not just internal order-state tracking | Backtest partial-fill representation |
| Partial Exit | 3/0 | 3/0 | 0 | Not touched (directive explicitly forbids) | Confirmed strategy-level partial-exit call site |
| Accounting | 8 | 8 | 0 | Untouched, proven byte-for-byte via regression test | — |
| P&L Semantics | 8 | 8 | 0 | Untouched | — |
| Backtesting | 7 | 7 | 0 | `engine.py` untouched this checkpoint | Trust-level upgrade path |
| Paper Trading | 7 | 8 | +1 | `PaperBroker` now exposes genuine per-execution-event observability (`get_fills()`) beyond order/position/trade snapshots, a real capability gain, without changing its numerical behavior | Fill consumed by accounting, Live parity |
| Backtest/Paper Parity | 5 | 5 | 0 | Still only ONE side has a producer — per directive, NOT inflated; parity requires BOTH sides converging | Backtest Fill producer |
| Strategy Extensibility | 7 | 7 | 0 | Unaffected | — |
| Testing | 8 | 8 | 0 | +23 new tests is real, but does not qualitatively exceed the already-strong 8/10 baseline | Property-based Fill-producer invariant tests |
| Performance | 6 | 6 | 0 | O(1) per-fill construction verified, no optimization needed | — |
| Scalability | 6 | 6 | 0 | Not broadly evaluated, unbounded in-memory list matches existing `Trade` pattern | — |
| Security | 8 | 8 | 0 | No Dhan/credentials/network touched | — |
| Research Readiness | 2 | 2 | 0 | `BacktestTrustLevel.POC` unchanged; Backtest Fill producer absent | POC->verified trust-level promotion, Backtest Fill producer |
| Live Paper Readiness | 6 | 6 | 0 | Existing Paper numerical behavior is byte-for-byte unchanged (regression-proven); observability improved but readiness gates (Dhan connectivity etc.) untouched | Everything Dhan-side |
| Live Trading Readiness | 1 | 1 | 0 | No live broker adapter exists or was touched | Everything |

ENGINEERING MATURITY: 7/10 (unchanged — same rigor, applied to producer integration this time).
ACCOUNTING MATURITY: 8/10 (unchanged — untouched this checkpoint, regression-proven).
EXECUTION MATURITY: 6/10 (+1 from 64.41's 5 — ONE real execution-event producer now genuinely
exists and is tested end-to-end, but only for Paper, and nothing yet consumes it for accounting).
BACKTESTING MATURITY: 7/10 (unchanged — `engine.py` untouched, per directive NOT inflated).
PAPER TRADING MATURITY: 7/10 (unchanged headline — numerical behavior is identical; the new
observability is real but the directive explicitly says not to claim execution convergence or
Research/Live readiness gains from it).
BACKTEST/PAPER PARITY: 5/10 (unchanged, per directive instruction — only one side has a producer).
ACTIVE PRODUCT MATURITY: 6/10 (unchanged — no active-path/strategy-execution code changed).
NEXT-MARKET-OPEN READINESS: 6/10 (unchanged — this checkpoint's change has zero runtime effect on
any live/paper NUMERICAL code path; market closed, no Dhan touched).
OVERALL PRODUCT SCORE: 7/10 (unchanged headline — a real, additive, well-evidenced producer-
integration checkpoint, but deliberately not inflated into "convergence," "Research Ready," or
"Live Trading Ready" claims it has not earned).

## Final Product Gate

A. **Does PaperBroker now create a canonical Fill for every actual fill?** YES — all 5 fill call
sites route through `_attempt_fill()`, which now constructs one `Fill` per successful fill.

B. **Does every Fill represent exactly one execution event?** YES — proven by the multi-fill test
(`quantity=5` then `quantity=5`, never a single `quantity=10` Fill for a two-event fill).

C. **Can one OrderIntent produce multiple Fills?** YES — proven, shared `order_id`, distinct
`fill_id`s.

D. **Are fill_ids unique?** YES — UUID4-generated, proven across >=100 fills in one runtime.

E. **Does Fill.order_id equal OrderIntent.order_id?** YES — direct field reuse, tested.

F. **Does Fill.quantity equal actual executed quantity?** YES — same local variable as the position
update, tested equal.

G. **Does Fill.price equal the actual final execution price?** YES — same `slipped_price` as
`record.average_fill_price`/`Position.average_entry_price`, tested equal.

H. **Does Fill.slippage_applied represent the actual signed adjustment?** YES — `slipped_price -
price` using `_attempt_fill`'s own pre-slippage reference parameter, tested for both BUY (positive)
and SELL (negative) signs.

I. **Does Fill.transaction_cost represent the actual cost for THIS fill?** YES — the exact `cost`
value already charged, tested per-fill-distinct via a stateful cost closure.

J. **Is Fill timestamp actual execution time?** YES — fresh `self._clock()` call, UTC-aware, tested
distinct from `OrderIntent.created_at`.

K. **Is FillSource.PAPER explicitly assigned?** YES — literal at the construction site, never
inferred.

L. **Does status_at_fill correctly represent PARTIALLY_FILLED/FILLED?** YES — same object reference
as the order's own `target_state`, tested for both values in the multi-fill scenario.

M. **Does Fill observation preserve execution order?** YES — append-only list, never re-sorted,
tested (`fill_1.timestamp < fill_2.timestamp`, list order matches call order).

N. **Does existing Position update use the same quantity/price as the Fill?** YES — proven directly
by `test_fill_quantity_and_price_equal_actual_position_update_values`.

O. **Did realized_net_pnl remain unchanged?** YES — regression-proven exact value (96.00) unchanged
from what the pre-existing formula alone would produce.

P. **Did unrealized_pnl remain unchanged?** YES — regression-proven (0 after close).

Q. **Did equity remain unchanged?** YES — regression-proven exact value (1000096.00).

R. **Did F1 remain fixed?** YES — `test_checkpoint_64_40_execution_correctness.py`'s F1 tests still
pass unmodified (134 passed together with 64.41's suite, only the one now-outdated `hasattr`
premise corrected).

S. **Did F2 remain fixed?** YES — same file's F2 tests still pass unmodified; the new
`TestLimitBoundaryReflectedInFill` tests independently re-confirm the clamp behavior at the Fill
level too.

T. **Did the shared slippage function remain unchanged?** YES — `domain/shared_kernel/slippage.py`
was not read for modification and shows zero new diff this checkpoint.

U. **Was Backtest untouched?** YES — `engine.py`/`execution.py`/`portfolio.py`/`cost_model.py`/
`tradeplan_execution.py`/`position_lifecycle.py` show zero new diff (verified via `git diff --stat`
isolation).

V. **Is a Backtest Fill producer implemented?** NO (expected NO, confirmed NO).

W. **Is a unified execution engine implemented?** NO (expected NO, confirmed NO).

X. **Is Backtest/Paper execution fully converged?** NO (expected NO, confirmed NO) — only one side
has a producer.

Y. **Is Research Ready?** NO (expected NO, confirmed NO) — `BacktestTrustLevel.POC` unchanged.

Z. **Is Live Paper Ready?** No material NEW readiness — Paper's existing numerical/order-lifecycle
behavior is byte-for-byte unchanged (regression-proven); the added capability is Fill-level
observability, not a Dhan-connectivity or live-readiness change.

AA. **Is Real Live Trading Ready?** NO (expected NO, confirmed NO) — no live broker adapter exists;
Dhan untouched (market closed).

## Git Status

`git status --short` at the START of this session (before any 64.42 change) showed the SAME
carried-forward, pre-existing uncommitted changes 64.41's own report documented, plus 64.41's own
new files:
```
 M docs/architecture/CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md
 M src/intraday/application/services/paper_trading.py
 M src/intraday/domain/position/contracts.py
 M src/intraday/domain/trade/contracts.py
 M src/intraday/infrastructure/brokers/paper/broker.py
 M src/intraday/research/backtesting/cost_model.py
 M src/intraday/research/backtesting/portfolio.py
 M src/intraday/research/backtesting/risk_gate_adapter.py
 M taskReport.md
?? src/intraday/domain/execution/
?? src/intraday/domain/position/mark_to_market.py
?? src/intraday/domain/shared_kernel/slippage.py
?? src/intraday/domain/trade/net_pnl.py
?? tests/unit/research/test_checkpoint_64_34_portfolio_risk_gate.py
?? tests/unit/research/test_checkpoint_64_35_risk_decision_convergence.py
?? tests/unit/research/test_checkpoint_64_36_pnl_accounting_convergence.py
?? tests/unit/research/test_checkpoint_64_37_net_pnl_risk_contract.py
?? tests/unit/research/test_checkpoint_64_38_paper_mark_to_market.py
?? tests/unit/research/test_checkpoint_64_39_execution_fill_audit.py
?? tests/unit/research/test_checkpoint_64_40_execution_correctness.py
?? tests/unit/research/test_checkpoint_64_41_fill_contract.py
```

`git status --short` at the END of this session, THIS checkpoint's own additions on top:
```
 M docs/architecture/CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md   (64.42: further appended)
 M src/intraday/application/services/paper_trading.py                    (carried-forward, untouched)
 M src/intraday/domain/position/contracts.py                             (carried-forward, untouched)
 M src/intraday/domain/trade/contracts.py                                (carried-forward, untouched)
 M src/intraday/infrastructure/brokers/paper/broker.py                   (64.42: Fill producer wired — THE core change)
 M src/intraday/research/backtesting/cost_model.py                       (carried-forward, untouched this checkpoint)
 M src/intraday/research/backtesting/portfolio.py                        (carried-forward, untouched)
 M src/intraday/research/backtesting/risk_gate_adapter.py                (carried-forward, untouched)
 M taskReport.md                                                          (64.42: full overwrite)
 M tests/unit/research/test_checkpoint_64_40_execution_correctness.py    (64.42: 1 outdated premise corrected)
?? src/intraday/domain/execution/                                        (carried-forward from 64.41, contract UNCHANGED this checkpoint)
?? src/intraday/domain/position/mark_to_market.py                        (carried-forward, untouched)
?? src/intraday/domain/shared_kernel/slippage.py                         (carried-forward, untouched)
?? src/intraday/domain/trade/net_pnl.py                                  (carried-forward, untouched)
?? tests/unit/research/test_checkpoint_64_34_portfolio_risk_gate.py      (carried-forward, untouched)
?? tests/unit/research/test_checkpoint_64_35_risk_decision_convergence.py (carried-forward, untouched)
?? tests/unit/research/test_checkpoint_64_36_pnl_accounting_convergence.py (carried-forward, untouched)
?? tests/unit/research/test_checkpoint_64_37_net_pnl_risk_contract.py    (carried-forward, untouched)
?? tests/unit/research/test_checkpoint_64_38_paper_mark_to_market.py     (carried-forward, untouched)
?? tests/unit/research/test_checkpoint_64_39_execution_fill_audit.py     (carried-forward, untouched)
?? tests/unit/research/test_checkpoint_64_40_execution_correctness.py    (carried-forward, this checkpoint's 1-test edit is IN THIS file, tracked as untracked-new since 64.40)
?? tests/unit/research/test_checkpoint_64_41_fill_contract.py            (carried-forward, untouched)
?? tests/unit/research/test_checkpoint_64_42_paper_fill_producer.py      (64.42: NEW)
```

`git diff --stat -- src/intraday/research/backtesting/` this checkpoint: identical 3-file
(`cost_model.py`, `portfolio.py`, `risk_gate_adapter.py`), 162-line-total diff to 64.41's own
reported figure — zero new lines this checkpoint, `engine.py` absent from the diff entirely
(never modified). `git diff --stat -- src/intraday/domain/execution/contracts.py` shows no tracked
diff (the file remains untracked/new-from-64.41, and its own content was not re-edited this
checkpoint — verified by re-reading it at the start of this session and confirming it is byte-
identical to what was captured in this same report's opening context read).

No commit was made. No push was made. No destructive git command (`checkout .`, `restore .`,
`reset --hard`, `clean`, `stash pop/drop`, `apply -R`) was run at any point this session — only
`git status --short` and `git diff --stat` (read-only).

## Honest Final Conclusion

This checkpoint did exactly what its directive asked and nothing more. It re-read `PaperBroker`
fresh (not trusting 64.41's report) and confirmed every fill in that class funnels through one
method, `_attempt_fill()`, called from 5 distinct sites covering MARKET, LIMIT, STOP_LOSS,
STOP_LOSS_MARKET, and the F1 partial-completion path. It added exactly one `Fill(...)`
construction at that single seam, placed strictly after the pre-existing order/position mutation,
built entirely from values that mutation had already computed — never a second, independently
derived number for quantity, price, cost, or status. It chose UUID4 for `fill_id` (uniqueness over
reproducibility, as directed), a plain `list[Fill]`/`get_fills()` retention mechanism mirroring the
class's own pre-existing `Trade` pattern exactly, and derived `slippage_applied` directly from
`_attempt_fill`'s own already-available pre-slippage reference price — no missing seam was found,
so no STOP was required anywhere in this checkpoint. It wrote 23 new, specific tests covering every
checklist item the directive named, ran a full fresh regression (1896 passed, exactly 1873 + 23,
zero unexplained failures, `engine.py`/`execution.py`/`portfolio.py`/`cost_model.py` genuinely
untouched — verified via `git diff --stat`), ran all seven quality gates clean, and appended (never
rewrote) the architecture document. One pre-existing 64.40 test's premise — "no Fill import exists
in broker.py" — was correctly identified as now-obsolete under this checkpoint's own explicit
mandate and was corrected with a documented rationale, not silently deleted or ignored. Nothing was
fabricated: every number in this report came from a command actually run this session. The
accurate, narrowly-scoped state this checkpoint delivers is a real, tested Paper-side Fill producer
— genuine new execution-event observability — with Backtest, accounting-as-a-Fill-consumer,
Research Readiness, and Live Trading Readiness all honestly left exactly where they were, per the
directive's own explicit instruction not to claim gains this checkpoint did not earn.
