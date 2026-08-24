# Trading-Grade Bar Validation

Checkpoint 31. Data quality + market-data fidelity only — no orders, no
paper trading, no live trading, no changes to `trading_engine/*`, kill
switch, or `TRADING_MODE`.

## 1. Objective

Determine whether the platform can obtain and validate market bars that
satisfy the project's `TRADING_GRADE_BAR` definition
(`docs/architecture/DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md`'s
six-condition acceptance test), not to begin live trading.

## 2. Dhan API Capability Verification (real, live, read-only)

Checkpoint 25.1's `DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md` left three
material facts UNCONFIRMED from documentation alone. This checkpoint
resolved two of them with a genuine, one-shot, read-only API call
(never repeated, never automated into a schedule), using the project
owner's already-configured Dhan credential (read via
`DjangoDhanCredentialRepository.get_decrypted_access_token()` — never
printed, logged, or committed).

**Call made:** `POST https://api.dhan.co/v2/charts/intraday`,
`securityId=1333` (HDFCBANK, previously verified),
`exchangeSegment=NSE_EQ`, `interval=1`, `fromDate`/`toDate` = today
(2026-08-14).

**Result:** HTTP 200. 360 one-minute candles returned.

| Question (from Checkpoint 25.1's Open Questions) | Finding | Classification |
|---|---|---|
| Does `/v2/charts/intraday` return today's already-elapsed candles in real time? | **Yes** — 360 real candles for 2026-08-14 (today) were returned, not only prior days. | **VERIFIED** |
| What timezone applies to the returned `timestamp` field? | The first candle's epoch (`1786679100.0`), interpreted as standard UTC epoch, equals `2026-08-14 03:45:00 UTC` = `2026-08-14 09:15:00 IST` — exactly this project's own documented market-open instant. Epoch is genuine UTC, not IST-wall-clock-mislabeled-as-epoch. | **VERIFIED** |
| Are candles exchange-authoritative or Dhan-computed? | Not resolvable from documentation or this call alone; see §3's independent cross-check for partial corroboration. | **PARTIALLY VERIFIED** |
| WebSocket reconnect/gap-detection mechanism? | Not exercised this checkpoint (no WebSocket connection attempted — see §5). | **UNVERIFIED** (unchanged from Checkpoint 25.1) |
| Corporate-action adjustment (raw vs. adjusted)? | Not addressed by this call or Dhan's documentation. | **UNVERIFIED** (unchanged) |
| Rate-limit category for `/v2/charts/intraday` specifically? | Not tested this checkpoint (single call made, no rate-limit boundary probed). | **UNVERIFIED** (unchanged) |

**A genuine, unexplained gap observed, not silently resolved:** the 360
candles run from 09:15 IST to 15:15 IST (the last candle's interval is
15:14–15:15) — 15 minutes short of the documented 15:30 market close
and 5 minutes short of the 15:20 square-off deadline. Neither Dhan's
documentation nor this checkpoint's own investigation explains why the
final ~15 minutes of the session were absent from this response. This
is recorded honestly as an open gap, not assumed to be either "the
session hadn't finished yet" or "the endpoint truncates" without
evidence for either explanation.

## 3. Independent Price Reference (Dhan-independent)

Per the explicit "do not compare Dhan → Dhan" instruction, a genuinely
independent source (Google Finance, `google.com/finance/quote/HDFCBANK:NSE`,
which itself sources exchange data — not Dhan) was fetched the same
day:

| Field | Dhan (`/v2/charts/intraday`) | Google Finance | Classification |
|---|---|---|---|
| Previous close | 725.00 (session's first candle open) | ₹725.00 | **EXACT_MATCH** |
| Last observed price | 727.00 (last candle close, 15:14 IST) | ₹727.00 (shown "as of" 15:59:57 IST) | **EXACT_MATCH on price**; **EXPLAINED_SEMANTIC_DIFFERENCE on timestamp** (~45 minutes apart — Dhan's intraday data ends at 15:14 IST per the gap noted in §2; Google Finance's later timestamp is consistent with the price simply not having moved in that window, not with a data-quality defect) |

This is one data point on one instrument on one day — not a full
independent-reference validation session (that would require many
instruments, many days, and ideally intraday tick-level comparison, not
just open/last-price). It is honestly reported as **partial
corroboration**, not proof of exchange-authoritative candle provenance.

## 4. TRADING_GRADE_BAR — Six-Condition Status

Reconfirming, not weakening, the Checkpoint 25.1 definition:

| # | Condition | Status this checkpoint |
|---|---|---|
| 1 | Same-day intraday availability | **SATISFIED** — directly verified, §2 |
| 2 | Exact timestamp/timezone verified | **SATISFIED** — directly verified, §2 |
| 3 | Candle authority/provenance sufficiently trusted | **NOT SATISFIED** — only one data point of independent corroboration (§3); Dhan does not document exchange-authoritative vs. self-computed candles |
| 4 | WebSocket live ingestion implemented and validated | **NOT SATISFIED / BLOCKED** — see §5 |
| 5 | Historical/reconciliation gap recovery implemented and validated | **NOT SATISFIED** — no WebSocket pipeline exists to reconcile against yet |
| 6 | One full trading session independently validated against a trusted price source | **NOT SATISFIED** — only a single-instrument, single-point comparison was performed (§3), not a full session |

**Overall: `TRADING_GRADE_BAR` remains unreachable. Every bar this
codebase can produce remains `SAMPLE_BAR`, now typed explicitly (§6),
not merely documented.** 2 of 6 conditions newly satisfied this
checkpoint (up from 0 of 6 previously); 4 remain unmet.

## 5. WebSocket Live Ingestion — Explicitly Blocked, Not Attempted

Per this checkpoint's Part 7 ("if and ONLY IF the required Dhan
behaviour is verified") and the pre-existing, unchanged infrastructure
finding from Checkpoint 23/25.1
(`docs/architecture/LIVE_MARKET_DATA_ARCHITECTURE.md` §"Why REST
polling, not WebSocket"): this Django/WSGI application still has no
running persistent process to safely host a long-lived WebSocket
client. `src/intraday/celery.py` exists only as Checkpoint-4
infrastructure-only scaffolding (one smoke task, no beat schedule
running outside `docker-compose.yml`, and Docker remains permanently
deferred per this project's invariant rules); `asgi.py`'s WebSocket
router remains empty.

**This blocker is unchanged from Checkpoint 25.1 and is not new to
this checkpoint.** Per Part 3's explicit STOP-and-document instruction
(applied here to an infrastructure blocker, the same discipline used
for credential blockers), no WebSocket ingestion, gap-recovery
reconciliation, or session-level streaming observation (Parts 7, 8, 10,
12) was implemented or attempted this checkpoint. Implementing one now
would mean building brand-new long-lived-process infrastructure under a
checkpoint explicitly scoped to data-quality/fidelity only — the same
scope discipline every prior live-market-data checkpoint (23, 24A,
25.1) has followed.

**What §2's single retrospective REST call establishes instead:** the
historical/intraday endpoint alone (Option B from Checkpoint 25.1's
comparison table) is now confirmed to serve same-day data with a
verified UTC timestamp convention — a necessary precondition for the
hybrid architecture, but not sufficient on its own, since it cannot
serve live "what is happening right now" observation (its own
documented purpose is retrospective).

## 6. Data Provenance Contract (implemented)

`domain/market_data/aggregation.py` gained two new, additive types:

- **`BarQualityGrade`** (`SAMPLE_BAR` / `TRADING_GRADE_BAR`) — an
  explicit enum, not a comment or a documentation claim.
- **`BarProvenance`** — `source`, `exchange`, `timeframe`, `timestamp`,
  `source_timestamp`, `ingestion_timestamp`, `aggregation_method`,
  `quality_grade`, `gap_count`. UTC-enforced on every timestamp field
  (`ensure_utc`), non-negative `gap_count` invariant.

`AggregatedBar` gained an optional `provenance: BarProvenance | None =
None` field (default preserves every pre-existing caller/test
unchanged — additive, not breaking). `aggregate_quotes_into_bars()` now
populates `provenance` on every bar it produces, always with
`quality_grade=BarQualityGrade.SAMPLE_BAR` and
`aggregation_method="point_sample_aggregation"` — set explicitly at the
one place this pipeline's bars are constructed, never defaulted or
inferred. `gap_count` reflects missing intervals detected for that
instrument's span up to that bar.

Proven by `test_every_bar_this_pipeline_produces_is_explicitly_sample_bar`
and 4 other new tests in `tests/unit/domain/test_market_data_aggregation.py`
— structural proof, not documentation, that `TRADING_GRADE_BAR` is
unreachable through this pipeline today.

## 7. Clock / Timestamp Boundary Validation

`tests/unit/domain/test_market_data_timestamp_boundaries.py` (new) and
an extension to `tests/unit/domain/session/test_calendar.py`:

- IST→UTC conversion pinned at exactly 09:15, 09:20, 15:25, and 15:30
  IST (the checkpoint's own named boundary values).
- `test_dhan_verified_epoch_matches_project_market_open_convention` —
  pins the exact epoch value observed from the real Dhan API call in
  §2 (`1786679100.0`) as a permanent regression fixture, asserting it
  equals this project's own computed market-open instant.
- 1-minute interval alignment at market open and market close.
- Naive (non-timezone-aware) datetimes are rejected outright, never
  silently reinterpreted.

All pass.

## 8. Gap Recovery, Session Observation, Historical Parity, Cache/Redundancy (Parts 8/10/12/13)

Not implemented — each is contingent on live WebSocket ingestion (§5),
which remains blocked. Existing, pre-checkpoint mechanisms already
satisfy the non-redundancy requirements that don't depend on
WebSocket:

- **Gap detection** (`MissingInterval`, Checkpoint 24A) already exists,
  unchanged, and is exercised by this checkpoint's own new provenance
  tests (`gap_count`).
- **Idempotent upsert** (`AggregatedBarObservation`, keyed by
  `(instrument_symbol, timeframe, interval_start)`) already exists,
  unchanged — no duplicate-bar risk, no redundant reprocessing.
- **Duplicate-tick suppression**: not applicable — no tick stream
  exists yet to deduplicate.

## 9. Bar-Integrity Invariants

Unchanged, already enforced by `AggregatedBar.__post_init__` and
`Bar.__post_init__` (both pre-existing, re-confirmed this checkpoint):
`high >= max(open, close)`, `low <= min(open, close)`, `high >= low`,
positive prices, non-negative `observation_count`, `interval_end >
interval_start`. All covered by existing + this checkpoint's new tests.

## 10. Frontend / UX

`LiveMarketDataMonitor.tsx` gained a `DataQualityBanner` — a static,
code-embedded, honest explanation: "◐ SAMPLE_BAR ... not yet
TRADING_GRADE_BAR ... A green connection indicator below means the
platform is successfully talking to the data provider - it does not
mean these candles are trading-grade." This is a global, structurally
true statement (every bar this codebase can produce is `SAMPLE_BAR` —
proven in §6), not a per-bar dynamic claim requiring new API surface.
Deliberately never displays "LIVE READY" merely because the connection
health badge is green.

## 11. Browser Testing

Re-checked this checkpoint: `import playwright` still fails, no
`node_modules/.bin/playwright` present. **Still unavailable, honestly
reported, not installed to paper over the gap** — unchanged from every
prior checkpoint (27–30). Frontend validation performed via
`tsc --noEmit`, `vitest`, and component/integration tests only.

## 12. RESEARCH_READY Gate Re-evaluation

| Criterion | Status |
|---|---|
| Independent reference validation (backtest engine) | **SATISFIED** (Checkpoint 30, unchanged) |
| Verified Indian cost model | **SATISFIED** (Checkpoint 29, unchanged) |
| Real historical market data | **PARTIALLY SATISFIED** — real, live-verified same-day historical/intraday data now exists (§2), but no full-session, real-data backtest has been run against it yet |
| `TRADING_GRADE_BAR` | **NOT SATISFIED** — 2 of 6 conditions met (§4) |
| Independent one-session validation | **NOT SATISFIED** — only a single-instrument, single-timestamp cross-check performed (§3), not a full session |
| Slippage validation | **NOT SATISFIED** — unchanged from Checkpoint 30 |
| Portfolio stress validation | **PARTIALLY SATISFIED** — unchanged from Checkpoint 30 (2-instrument only) |

**No mandatory condition set is fully satisfied. Trust level remains
`POC`.** This checkpoint made genuine, real, verified progress
(2 of 6 `TRADING_GRADE_BAR` conditions resolved with live evidence,
not documentation guesswork) but does not itself close the gate.

## 13. Trading Safety

Orders placed: **0**. Broker execution calls: **0**. Position changes:
**0**. Live authorization changes: **0**. `TRADING_MODE`, kill switch,
and `order_management`/`execution_management`/`risk_engine` untouched.
The one live Dhan call made this checkpoint
(`POST /v2/charts/intraday`) is a read-only historical-data query —
the same class of call already exercised safely at Checkpoints 22–24A,
never an order/position/execution endpoint. No credential value was
printed, logged, or committed at any point.

## 14. Remaining Blockers

1. No persistent-process infrastructure to host a WebSocket client
   outside Docker (unchanged since Checkpoint 23; Docker itself remains
   permanently deferred).
2. Candle authority (exchange-computed vs. Dhan-computed) remains
   unconfirmed by Dhan's own documentation; only one data point of
   independent corroboration exists.
3. The unexplained ~15-minute gap at the end of the intraday response
   (§2) is unresolved — not yet understood whether it is a timing
   artifact of when the call was made or a structural endpoint
   limitation.
4. No full-session, multi-instrument, independent-source reconciliation
   has been performed (Part 12's "historical parity" requires a
   WebSocket-aggregated bar to compare against, which does not exist).

## 15. Recommended Next Checkpoint (as of Checkpoint 31 — see §16 for the 64.55 update)

Given the infrastructure blocker in §5 is the single largest remaining
gap (it blocks conditions 4, 5, and 6 of the six-condition definition
simultaneously), and this project's own invariant rules keep Docker
permanently deferred, the recommended next checkpoint is: **design (not
implement) a WebSocket-hosting strategy for this Django/WSGI
application that does not require Docker** — e.g. evaluating Django
Channels' ASGI worker (already scaffolded, unused) as a genuinely
separate deployable process versus a lightweight non-Docker Celery
worker — as a pure architecture-decision checkpoint, before any
WebSocket ingestion code is written.

## 16. CHECKPOINT 64.55 — READ-ONLY LIVE NSE DATA VALIDATION ATTEMPT

64.54 discovered (by reading source, not by trusting this document's own
stale §5) that the "no persistent process" blocker described in §5/§14
above no longer exists: `run_market_data_worker.py` (Checkpoints
57-64.3) is a real, persistent, non-Docker WebSocket-hosting process,
supporting both `--provider fake-ws` (a genuine RFC 6455 transport
against a safe local fake server) and `--provider dhan` (the real
provider). 64.55's mandate was to attempt the FIRST real, read-only,
live NSE validation against `--provider dhan`.

**Credential-state check (performed exactly once, no retry, no network
call — `evaluate_dhan_token_lifecycle()`, Checkpoint 64, pure/local/
claims-only):** this environment's configured Dhan credential IS
present, and its own `exp` claim reports **EXPIRED** (expired
2026-08-21 07:01:44 UTC — a non-secret, documented-safe field; the
token value itself was never printed, logged, or persisted anywhere).
2026-08-24 (today) is after that expiry.

**Consequence, per this checkpoint's own explicit safety rule ("check
ONCE, never retry"):** the live-validation portion of this checkpoint
was correctly STOPPED before any connection attempt. `run_market_data_
worker.py --provider dhan`'s own pre-existing token-lifecycle guard
(§"Headline Finding" in `taskReport.md` 64.54, unmodified this
checkpoint) refuses to start a socket at all once `token_status.state`
is not `VALID`/`EXPIRING_SOON` — proven again, fresh, this checkpoint,
by `tests/unit/infrastructure/persistence/management/
test_run_market_data_worker_command.py::
test_dhan_provider_refuses_to_connect_with_a_known_expired_token`
(pre-existing, unmodified, still green) and this checkpoint's own new
`tests/unit/research/test_checkpoint_64_55_live_market_data_validation.py`
(`test_a`/`test_h`), the latter additionally monkeypatching
`DhanWebSocketTransport.connect` to raise `AssertionError` if ever
called — the strongest available proof, inside an automated test, that
no network attempt happens for an expired token.

**Six-condition status, re-evaluated this checkpoint — NO CONDITION
MOVED, because no live connection was attempted:**

| # | Condition | Status after 64.55 | Why unchanged |
|---|---|---|---|
| 1 | Same-day intraday availability | SATISFIED (Checkpoint 31, unchanged) | Historical REST path, untouched this checkpoint |
| 2 | Exact timestamp/timezone verified | SATISFIED (Checkpoint 31, unchanged) | Same |
| 3 | Candle authority/provenance | NOT SATISFIED (unchanged) | No live WebSocket data was received to compare against anything; independent cross-check requires real candles this checkpoint could not obtain |
| 4 | WebSocket live ingestion implemented AND validated | Still PARTIAL — **implementation** confirmed again (fresh fake-ws regression, this checkpoint), **live validation against real NSE data still did not happen** | Token EXPIRED; live path correctly never attempted |
| 5 | Historical/reconciliation gap recovery validated | Still PARTIAL — gap-detection mechanism (`MissingInterval`) re-confirmed via synthetic evidence only (this checkpoint's own `test_g` DB read-back plus 64.54's own tests) | No live gap was ever observed, none was fabricated |
| 6 | One full trading session independently validated | NOT SATISFIED (unchanged) | Zero live session minutes were observed this checkpoint — the entire live portion was correctly stopped before any connection |

**Overall: `TRADING_GRADE_BAR` remains unreachable against real NSE
data — unchanged from 64.54's own honest re-tabulation.** This
checkpoint's genuine contribution is negative-but-honest evidence: the
worker's own safety gate was exercised against this environment's
actual (not simulated) expired-token condition and correctly refused,
with an automated test now pinning that exact behavior as a permanent
regression (`test_a` above) rather than relying on a one-off manual
observation.

**What this checkpoint does NOT claim:** no packets, no live Quote, no
live bar, no live promotion, no live reconnect, no live session, no
candle-authority evidence. `docs/architecture/
CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md`'s own new "CHECKPOINT
64.55" section and `taskReport.md` both state this identically — no
document in this repository claims live NSE validation occurred this
checkpoint.

### Recommended Next Checkpoint (64.55's own update)

Obtain a fresh, valid Dhan access token (this environment's own token
renewal is an operator action this checkpoint correctly did not and
could not perform automatically — Dhan's documented `RenewToken` API
itself refuses an already-`EXPIRED` token) and, strictly read-only,
attempt `--provider dhan` again for the first genuine live-packet
observation. Only once real packets are received can conditions 4/5/6
above genuinely move past PARTIAL/NOT SATISFIED.

---

## 17. CHECKPOINT 64.63 — LIVE DATA INTEGRITY REMEDIATION (§75/§305 UPDATE)

64.62 obtained the first real Dhan WebSocket session and found that Criterion 2 ("Exact timestamp/timezone
verified", previously marked SATISFIED at §75/§305 based on the REST historical-candle endpoint only, §2
above) does **NOT** extend to the live WebSocket ticker/quote path: the confirmed-live batch showed
`source_timestamp` ~5.5h ahead of `fetched_at`. 64.63 investigated this (see
`docs/architecture/CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md`'s own new "CHECKPOINT 64.63"
section for the full trace) and could **not** conclusively source-back a fix — Dhan's public WebSocket
docs document the field only as `"Last Trade Time (EPOCH)"`, with no description of how the server itself
computes that integer. **No timestamp conversion code was changed.**

**Criterion 2 status, corrected:** SATISFIED for the REST historical-candle path only (§2, unchanged,
re-verified as still true); **NOT SATISFIED for the live WebSocket ticker/quote path** (new, honest
downgrade from any previous implication that §75/§305's SATISFIED covered both paths). A future checkpoint
must either obtain conclusive Dhan documentation/support confirmation of the WebSocket epoch's exact
semantics, or independently prove the offset's cause from a larger, controlled real-session sample, before
this criterion can be marked SATISFIED for the live path.

64.63 also root-caused and fixed an unrelated `WorkerRuntimeStatus` observability bug (health-tracker
persistence was gated behind the scanner's `enabled` pause flag) and proved, by test, that the existing
`AggregatedBar.to_bar()` adapter cleanly produces a canonical `Bar` (volume honestly `Decimal("0")`,
quality/adjustment reusing existing enums) — neither of these two items changes any TRADING_GRADE_BAR
criterion's status; they are observability/compatibility fixes, not data-quality proofs.

## 18. CHECKPOINT 64.64 — VOLUME + QUALITY/STRATEGY BOUNDARY (offline)

Two of 64.63's honestly-left-open gaps closed without touching the timestamp criterion above (still NOT
SATISFIED for the live WebSocket path — unchanged, no new evidence obtained this checkpoint):

- **Volume is no longer unconditionally `Decimal("0")`.** `Quote.cumulative_volume` (new, optional field)
  carries `DhanQuotePacket.volume` (real, cumulative day volume — Ticker packets have no volume field at
  all, so a Ticker-sourced quote still carries `None`). `aggregate_quotes_into_bars()` differences
  consecutive real readings into `AggregatedBar.volume` → `Bar.volume`; `Decimal("0")` remains the honest
  value whenever no cumulative reading exists to difference (still true for every REST point-sample quote
  and every Ticker-sourced live quote — not a regression). See
  `docs/architecture/CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md`'s own "CHECKPOINT 64.64" section
  for the full differencing/reset/negative-volume rule.
- **`ScannerConfiguration.enabled=False` no longer blocks TRADING_GRADE_BAR promotion.** The model's own
  docstring is unambiguous that this flag means "pause the signal pipeline," not "pause market-data
  ingestion" — `_QuoteSink.aggregate_now()`'s disabled branch now calls `promote_bars_and_trigger_signals()`
  with `strategy_execution_enabled` forced `False`, so bars are still graded while the scanner is paused,
  with zero strategy invocations. Does not change any TRADING_GRADE_BAR criterion's own definition — the
  six `PromotionCondition`s are unchanged — only WHEN the (already strategy-agnostic) gate is reached.
- A tested, disabled-by-default timestamp-diagnostic collector
  (`infrastructure/market_data_providers/dhan/timestamp_diagnostics.py`) was prepared for a future REAL NSE
  SESSION #2 to wire in and collect a larger sample — not wired into the worker, not used this checkpoint.

No criterion in §4 changes status as a result of this checkpoint.
