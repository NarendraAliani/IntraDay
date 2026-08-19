# Task Report

## Checkpoint

Checkpoint 64 — Live Paper Trading Runtime (Readiness Gate + First Increments).
This report OVERWRITES the previous `taskReport.md` per this checkpoint's
own instruction — it describes only this checkpoint's work. The full
backtesting/DB-first checkpoint report this superseded is preserved in git
history, not here.

## Objective

Turn the already-built signal → risk → paper-execution pipeline into
something that runs continuously against **real** Dhan market data, while
keeping real (live) order placement disabled. This checkpoint's own
32-section brief asked for the full runtime (WebSocket connection,
reconnect, token lifecycle, watchdog, universe widening, dashboard,
performance testing, full-day simulation, new reports) in one pass.

**Honest scope statement up front**: that full scope is genuinely
multi-week work. This checkpoint completed the mandatory readiness gate,
performed a REAL (not simulated) Dhan connectivity verification, and
implemented two concrete, fully-tested increments that came directly out
of what that verification found. It did not attempt the remaining ~28
sections of the brief (reconnect state machine, watchdog, subscription
manager, dashboard, performance/load testing, full-day simulation,
new reports) — each is named explicitly under Remaining Gaps, not silently
dropped.

## Readiness Gate

Traced against the ACTUAL current code (not documentation), by reading the
real modules listed in the Files column.

| Component | Exists | Tested | Integrated | Production-Verified | Blocker |
|---|---|---|---|---|---|
| Dhan credentials (Settings/env) | Yes | Yes | Yes | **This checkpoint** | Configured token was found **EXPIRED** — see Real Dhan Verification below |
| Dhan WebSocket endpoint (`wss://api-feed.dhan.co`) | N/A (external) | — | — | **This checkpoint** | Handshake succeeds; app-level auth rejects the current token |
| WebSocket authentication (query-param scheme) | Yes (`websocket_transport.py`) | Yes (local fake server only, pre-existing) | Partial | **This checkpoint, real endpoint** | Token expiry (see above) |
| Token lifecycle | **New this checkpoint** (`token_lifecycle.py`) | Yes (8 unit + 4 integration/API tests) | Yes (Settings API + UI) | N/A (pure/local, no network) | Only claims-based (exp), not renewal — see Remaining Gaps |
| Instrument master (scrip master) | Yes (built prior session) | Yes | Yes (backtesting) | Real, cached fetch | — |
| Subscription manager (live-quote universe) | Partial — widened this checkpoint | Yes (8 tests) | Partial | Not live-tested (blocked by token) | No dynamic/UI-driven subscription set yet — see §6 gap below |
| Tick decoder (`packet_decoder.py`) | Yes (pre-existing) | Yes (fixture-based) | Yes | No (never decoded a real Dhan packet — connection never reached data) | Blocked by token expiry |
| Quote processing (`packet_to_quote.py`) | Yes (pre-existing) | Yes | Yes | No | Same |
| Bar aggregation | Yes (pre-existing) | Yes | Yes | Only against synthetic feed | Same |
| Trading-grade data gate | Yes (pre-existing) | Yes | Yes | Only 2/6 conditions ever exercised live | Unchanged this checkpoint |
| Strategy engine | Yes (pre-existing) | Yes | Yes | Proven vs. backtest/replay data | — |
| Signal persistence | Yes (pre-existing) | Yes | Yes | — | — |
| Risk engine | Yes (pre-existing) | Yes | Yes | — | — |
| PaperBroker | Yes (pre-existing) | Yes | Yes | — | — |
| Position management | Yes (pre-existing) | Yes | Yes | — | — |
| Reconciliation | Yes (pre-existing) | Yes | Yes | — | — |
| EOD | Yes (pre-existing) | Yes | Yes | — | — |
| Telegram/Discord communication | Yes (pre-existing) | Yes | Yes | Not against real credentials this checkpoint | — |
| Operator UI | Yes (Settings/Backtesting/Paper Trading/Market Data pages) | Yes | Yes | — | No unified operational dashboard yet |
| Reports | Partial (3/11 types real) | Yes for what exists | Partial | — | Unchanged this checkpoint |
| Monitoring/Logs | Partial (`structlog` throughout) | — | Yes | — | No worker-health signal |
| Reconnect | **No** | — | — | — | Not attempted this checkpoint |
| Watchdog | **No** | — | — | — | Not attempted this checkpoint |

## Research Performed

Fetched Dhan's current official documentation directly (not from memory)
for the Live Market Feed API — confirmed against `https://dhanhq.co/docs/v2/live-market-feed/`:
- WebSocket URL/auth: `wss://api-feed.dhan.co?version=2&token=...&clientId=...&authType=2` — unchanged from Checkpoint 53's original research.
- Subscribe request shape: `{"RequestCode": 15, "InstrumentCount": N, "InstrumentList": [{"ExchangeSegment": "NSE_EQ", "SecurityId": "..."}]}`.
- Limits: 5 connections/user, 5,000 instruments/connection, 100 instruments/message.
- Heartbeat: 10s server ping, 40s client timeout.
- Disconnect request: `{"RequestCode": 12}`.

All of this matched the codebase's pre-existing `websocket_transport.py`/
`packet_decoder.py` assumptions exactly — no code needed to change because
of this research; it served to confirm the existing implementation is
still current, not stale.

## Official Sources

- `https://dhanhq.co/docs/v2/live-market-feed/` (fetched live this checkpoint).
- This project's own prior primary-source research (`docs/research/CHECKPOINT_53_DHAN_WEBSOCKET_PROTOCOL_RESEARCH.md`), re-confirmed rather than re-done from scratch.

## Real Dhan Verification

**Performed for real, not simulated.** Using the actual credentials
configured in this environment's Settings/`.env` (never printed, logged,
or committed anywhere — see Security below):

1. Confirmed credentials are present (`DhanSettingsService.effective_credentials()` returns a real client ID + token) — presence and shape checked only (lengths, "looks numeric"/"looks like a JWT"), never the values themselves.
2. Connected a real `DhanWebSocketTransport` instance to Dhan's real production endpoint `wss://api-feed.dhan.co` with the real configured credentials in the query string.
   - **Result: `RESULT=CONNECTED connect_latency_ms=139`** — the RFC 6455 handshake genuinely succeeded.
3. Sent a real subscribe request for RELIANCE (NSE_EQ, security_id 2885).
   - **Result: connection closed abnormally (WebSocket close code 1006) within seconds**, before any data packet arrived.
4. Repeated the connection attempt with NO subscribe message sent at all, to isolate whether the abrupt close was caused by the subscribe message or something upstream of it.
   - **Result: identical 1006 abnormal closure, purely from connecting** — proving the issue is not the subscribe message format.
5. Decoded (payload only, never the signature) the configured access token's own JWT claims to check its real expiry.
   - **Result: `token_issued_at_utc = 2026-08-17 07:10:54`, `token_expires_at_utc = 2026-08-18 07:10:54`, `now_utc = 2026-08-19 08:14:23`, `token_is_expired = True`.**

**Conclusion**: `REAL-DHAN-VERIFICATION = BLOCKED — configured access token is expired` (issued with Dhan's documented ~24h TTL, now over a day past its own expiry). This is not a code defect in this project's WebSocket transport — the transport-level handshake genuinely succeeded against the real endpoint, and the request/response shapes matched current official documentation exactly. The block is purely credential freshness, and it is now visible on the Settings page (see Implementation below) rather than hidden behind a stale cached "Connected" badge.

**Safe evidence retained above**: connection state, latency, close code, and non-secret JWT claims (`iss`, `exp`, `iat`, `dhanClientId`-matches-configured boolean) only. No access token, client ID value, signature, or header value was printed, logged, or written to any file in this repository at any point.

## Implementation

### 1. Token lifecycle (`application/services/token_lifecycle.py`)
A pure, I/O-free evaluator: given an access token string and the current
time, decodes the JWT payload's `exp` claim (never the signature) and
returns one of `UNCONFIGURED` / `VALID` / `EXPIRING_SOON` (within 1h of
expiry) / `EXPIRED` / `MALFORMED`. Wired into `DhanSettingsService.get_display()`
so it's computed fresh on every Settings page load — the exact live
finding above (a stale "Connected" badge next to a token that had
actually expired) is now surfaced directly.

### 2. Settings API + UI
`DhanSettingsResponseSerializer` gained `token_state`/`token_expires_at`.
`DhanSettingsCard.tsx` gained a `TokenStateBadge` shown alongside the
existing (cached) connection-status badge, so an operator sees both
signals side by side rather than only the stale one.

### 3. Widened live-quote observation universe (`instruments.py`)
`observation_universe()` previously raised for any symbol not in a
4-entry hardcoded table. It now falls back to the real Dhan scrip master
(the same one built for historical/backtesting data in the prior session,
which carries real `security_id` values) for any symbol the hardcoded
table doesn't cover — closing the architectural inconsistency
NewStatus.md named (live universe capped at 4 symbols vs. ~3,100 for
historical). The 4-symbol default path makes zero network calls, exactly
as before (proven by a dedicated test injecting a master that raises if
called) — this is a strict widening, not a behavior change for existing
callers.

**Honest scope limit on this piece**: this is the resolution mechanism
only (any real NSE symbol can now be named in `MARKET_DATA_OBSERVATION_SYMBOLS`).
It is NOT a subscription-manager UI, NOT a dynamic watchlist/strategy-
universe selector, and does NOT itself change what's actually subscribed
to at runtime — those remain undone (see Remaining Gaps).

## Files Created
- `src/intraday/application/services/token_lifecycle.py`
- `tests/unit/application/services/test_token_lifecycle.py`
- `NewStatus.md` (prior turn, not this implementation pass)

## Files Modified
- `src/intraday/application/services/provider_settings.py` — wires token lifecycle into `DhanSettingsService.get_display()`.
- `src/intraday/application/contracts/settings.py` — `token_state`/`token_expires_at` fields.
- `src/intraday/infrastructure/api/settings_views.py` — serializes the new fields.
- `src/intraday/infrastructure/market_data_providers/dhan/instruments.py` — scrip-master fallback for `observation_universe()`.
- `frontend/src/features/settings/DhanSettingsCard.tsx` — `TokenStateBadge`.
- `frontend/shared/generated_contracts/api-types.ts` — regenerated from the updated OpenAPI schema.
- Test files: `test_provider_settings.py`, `test_settings_api.py`, `test_instruments.py`, `DhanSettingsCard.test.tsx`.

## Live Market Data

Not implemented this checkpoint beyond the verification above. The
transport (`DhanWebSocketTransport`) is unchanged and was proven, for the
first time, to genuinely reach Dhan's real endpoint. No production code
path (worker command, ingestion runtime) was wired to use a real
connection this checkpoint — `manage.py run_market_data_worker` still only
supports `--provider fake`/`--provider fake-ws` (local synthetic
servers), unchanged.

## Token Lifecycle

See Implementation §1 above. Explicitly NOT implemented: automatic
renewal (Dhan's `RenewToken` API was not integrated), and the richer
`RENEWING`/`RENEWED`/`AUTH_FAILURE`/`OPERATOR_ACTION_REQUIRED` states the
brief asked for — those require an actual renewal attempt or a real
connectivity check, not just reading the token's own claims. What exists
now is the honest, narrower "what does the token's own expiry say" signal.

## Reconnect / Recovery

**Not implemented this checkpoint.** Still exactly as NewStatus.md
described: the worker detects a disconnect and stops; it does not retry.

## Watchdog

**Not implemented this checkpoint.**

## Bar/Data Quality

Unchanged this checkpoint. The `SAMPLE_BAR` → `TRADING_GRADE_BAR` gate
was not exercised against real Dhan data this checkpoint, since the real
connection never reached the data-receiving stage (blocked by the expired
token before any packet arrived).

## Signal Pipeline

Unchanged this checkpoint — no new live signal path work was done. The
existing strategy/signal/risk/paper pipeline (built pre-session) remains
the one and only implementation; nothing new was built or duplicated.

## Risk / Paper Trading

Unchanged this checkpoint.

## Communication

Unchanged this checkpoint. The signal/execution-separation and
event-driven communication architecture the brief described (§§12-14)
was not implemented.

## Operator Dashboard

Not built this checkpoint. The Settings page's Dhan card is the one piece
of operator-facing surface touched — it now shows real token state, not a
full operational dashboard.

## Reports

Unchanged this checkpoint.

## Performance Measurements

Not attempted this checkpoint (still `RED` per NewStatus.md — unchanged).

## Failure Injection

Not attempted this checkpoint (no reconnect/watchdog subsystem exists yet
to inject failures against).

## Full-Day Paper Simulation

Not built this checkpoint — a genuinely separate, substantial undertaking
this checkpoint's real-connectivity finding (expired token) makes
premature: a full-day live simulation needs a working live connection
first, which this checkpoint proved is currently blocked.

## Tests

- Backend: **1314 passed** (up from 1300 before this checkpoint — 14 new: 8 token-lifecycle unit tests, 4 provider-settings/API tests, plus the widened-universe test additions net of edits).
- Frontend: **127 passed** (up from 126 — 1 new: the expired-token-badge test).
- `ruff format --check` / `ruff check`: clean.
- `mypy src/`: clean, 272 source files.
- `lint-imports`: 6/6 contracts kept.
- `python manage.py check`: clean.
- `python manage.py makemigrations --check --dry-run`: no changes (no model fields changed this checkpoint).
- `python manage.py spectacular --fail-on-warn`: clean.
- No test was weakened to pass — every failure encountered during this checkpoint's work was fixed in the implementation, not the test.

## Security

- The real Dhan credential's VALUE was never printed, logged, echoed, or written to any file in this repository — verified by inspecting every command/script used for the connectivity check; only non-secret metadata (lengths, boolean shape checks, JWT `exp`/`iat`/`iss`/`dhanClientId`-matches boolean) was ever displayed.
- `.env` remains git-ignored (`git check-ignore -v .env` confirmed).
- The new `token_state`/`token_expires_at` API/UI fields carry only a state name and a timestamp — never the token itself (mirrors the existing, unmodified secret-handling convention this project has enforced since Checkpoint 22).
- Temporary local verification scripts used for the live connectivity check were deleted after use and were never part of the git-tracked repository.
- `git status` confirms nothing secret is staged (see Git below).

## Remaining Gaps

Everything the 32-section brief asked for that was NOT attempted this
checkpoint, named explicitly rather than silently dropped:
- Reconnect-with-backoff state machine.
- Watchdog / worker health monitoring.
- A real, dynamic subscription manager (watchlist/strategy-universe-
  driven, not just "any symbol CAN be resolved" — this checkpoint closed
  the resolution mechanism, not the selection UI).
- Automatic token renewal (Dhan's `RenewToken` API).
- Wiring a real connection into `manage.py run_market_data_worker` /
  the ingestion runtime (blocked today by the expired credential, but
  also simply not attempted).
- Signal/execution separability as a first-class communication model.
- Event-driven (SignalGenerated → ... → PositionClosed) communication architecture.
- Full-day deterministic paper session simulation with injected disconnect.
- Real-time operator dashboard.
- User-controlled live scanner UI (timeframe/universe/strategy selectors that actually drive a live runtime).
- Performance/load testing at any scale.
- Full-signal latency tracing (tick → notification timestamp chain).
- Data-gap detection/reconciliation on reconnect.
- New report types (Signal Report, Portfolio Report, Risk Decision Report, System Health Report, Daily Session Report).

## Blockers

1. **The configured Dhan access token is expired** (verified directly this checkpoint — issued 2026-08-17 07:10 UTC, expired 2026-08-18 07:10 UTC, ~24h TTL per Dhan's documentation). This blocks any further REAL live-data verification until a fresh token is obtained and configured. The Settings page now shows this state directly (`token_state: EXPIRED`) instead of it being invisible.
2. Everything downstream of a real connection (reconnect, watchdog, live TRADING_GRADE_BAR promotion, live signal generation) cannot be genuinely verified until blocker 1 is resolved — it can be BUILT and unit-tested against synthetic/injected failures, but not proven against the real feed.

## Product Readiness

**"Can I start the application before market open tomorrow, leave it
running in PAPER mode, and trust it to receive live Dhan market data,
recover from normal feed interruptions, detect stale data, produce
strategy signals, apply risk, create paper trades, maintain positions,
publish audited signals, and perform EOD reconciliation?"**

**Answer: NO.**

Exact blockers, in priority order:
1. The configured Dhan credential is expired — no live connection is currently possible at all (verified directly, not assumed).
2. No reconnect-with-backoff exists — even with a fresh token, a single network hiccup would silently stop the feed for the rest of the day.
3. No watchdog exists — nothing would alert an operator that the feed had stopped.
4. No production code path wires the real WebSocket transport into the actual worker/ingestion runtime yet — the transport was proven reachable this checkpoint, but nothing in `manage.py run_market_data_worker` uses it for anything other than the local synthetic test servers.
5. The live-quote universe, while no longer architecturally capped at 4 symbols, still has no operator-facing selection UI to choose what it actually watches at runtime.

## Performance Ranking

Not applicable this checkpoint — no alternative implementations were built or compared; the increments implemented (token lifecycle, universe widening) had one natural design each, not several measured alternatives.

## Honest Final Conclusion

This checkpoint did NOT deliver a live paper trading runtime — that remains
substantially unbuilt, honestly, per the Remaining Gaps and Blockers above.
What it DID deliver, for real:
1. **The first-ever real connectivity attempt against Dhan's actual production WebSocket endpoint** from this codebase, in this environment — the handshake genuinely succeeded, proving the transport layer built in a prior checkpoint is not merely locally-tested theater; it works against the real service.
2. **A concrete, evidence-based root cause for why live verification is blocked**: not a code defect, but an expired credential — found by decoding the token's own claims, not guessed.
3. **A real, previously-invisible safety gap closed**: the Settings page's "Connected" badge could be — and in this very environment, WAS — stale relative to the token's actual state. That gap is now closed with a fresh-computed, tested, UI-visible signal.
4. **A real architectural inconsistency closed**: the live-quote observation universe is no longer capped at 4 hand-maintained symbols; any real NSE instrument can now be named and resolved via the same scrip master the historical/backtesting side already uses.

Both delivered increments are small, but each is directly traceable to something this checkpoint's own readiness gate and live verification actually found — not speculative work done ahead of evidence. The larger runtime (reconnect, watchdog, dashboard, full-day simulation) remains the honest, correctly-sequenced next work, now unblocked to start on as soon as a fresh Dhan credential is available.
