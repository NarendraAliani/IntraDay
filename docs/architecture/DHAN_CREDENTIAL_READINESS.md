# Dhan Credential Readiness (Checkpoint 64.12)

> No pre-existing "Dynamic Digital Tutorial Guide" was found anywhere in
> this repository (a full-text search for "tutorial" across the project
> returned nothing) — this document is a new, plain-language addition,
> not an update to a file that turned out not to exist. Disclosed
> honestly rather than silently substituting a different file.

## Dependency Map

```
Credential Source (.env DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN,
    or the encrypted DhanCredential DB row - env is the fallback,
    DB takes precedence, see provider_settings.py)
        ↓
Validation (token_lifecycle.evaluate_dhan_token_lifecycle() -
    Checkpoint 64 Part 1 - decodes the JWT's own `exp` claim locally,
    NO network call)
        ↓
Live Paper Readiness Gate (live_paper_readiness.evaluate_live_paper_readiness() -
    Checkpoint 64.12, NEW this checkpoint - composes credential state +
    worker watchdog_state + kill-switch engagement into ONE can_start decision)
        ↓
Worker Start Protection (run_market_data_worker.py - Checkpoint 64,
    ALREADY existed - refuses to open a live connection whenever
    token_state is not VALID/EXPIRING_SOON, before any WebSocket
    handshake is attempted)
        ↓
Runtime Status (WorkerRuntimeStatus.token_state - persisted every
    aggregation cycle by the worker itself, Checkpoint 64.3)
        ↓
UI (WorkerStatusCard shows the raw token_state; the NEW
    LivePaperReadinessCard, Checkpoint 64.12, shows the composed
    can_start decision with a human remediation hint)
        ↓
Live Paper Gate (GET /api/v1/config/market-data/live-paper-readiness/ -
    the single canonical answer to "is it safe to press START")
```

**What already existed before this checkpoint** (verified by reading
the code, not assumed): the credential validation, worker-start
protection, and runtime-status persistence layers were all real and
correctly wired since Checkpoints 64/64.1/64.3. **What this checkpoint
added**: the one missing layer that combined all of those signals into
a single, explicit "can we start a Live Paper Session" decision, plus
an API endpoint and a UI card for it.

## What is the Dhan access token?

Dhan issues a JSON Web Token (JWT) — a signed string of text — when an
operator authenticates with Dhan's own systems (via their web portal or
their documented Generate Token flow). This application stores that
token (encrypted at rest, or via an environment variable in
development) and presents it to Dhan's REST/WebSocket APIs on every
request to prove "this application is acting on behalf of this Dhan
account."

## Why does it expire?

Dhan's own documentation states the access token is valid for
**24 hours** from issuance. This is Dhan's policy, not a limitation
this application introduced — after 24 hours, Dhan's own servers will
reject the token regardless of what this application does.

## What does EXPIRED mean here, concretely?

The token itself carries its own expiry timestamp (the `exp` claim,
part of the JWT standard). This application reads that timestamp
**locally, with no network call** — it does not need to ask Dhan
"is this still valid?" to know the token has passed its own stated
expiry. `EXPIRED` means: the current time is past the token's own
claimed expiry instant.

## How does the system behave when the credential is expired?

- The live market-data worker (`manage.py run_market_data_worker`)
  **refuses to open a connection** — this has been true since
  Checkpoint 64, re-verified this checkpoint by reading the worker
  command's own guard clause.
- The Live Paper Readiness gate reports `CREDENTIAL_EXPIRED` and
  `can_start: false` — a human operator sees this immediately on the
  Market Data screen, without needing to inspect logs.
- **Historical/research capability is unaffected.** Backtesting,
  database-replay, the Signal Operations Center over historical data,
  and every report built in Checkpoint 64.10 read only the local
  database — none of them touch the Dhan credential at all. This
  separation is verified by dedicated tests this checkpoint (see
  taskReport.md, "Historical/Research Isolation").

## Why is LIVE PAPER blocked, specifically?

A Live Paper Session means: connect to Dhan's real, live market-data
feed and evaluate real strategies against it (still only ever placing
**paper** orders — no real broker order path exists anywhere in this
codebase). That connection cannot be opened with an expired credential
— Dhan's own servers would reject it. The system detects this in
advance, locally, and refuses to even attempt the connection, rather
than trying and failing against Dhan's live systems.

## What does the operator need to do?

Obtain a fresh access token from Dhan (via their web portal, or their
documented Generate Token flow using TOTP) and configure it on the
Settings page or via the `DHAN_ACCESS_TOKEN` environment variable. The
readiness gate re-evaluates on every request — there is no restart or
cache-clear step required; the very next check will show `VALID` or
`EXPIRING_SOON` once a genuinely fresh token is in place.

## Why does real trading remain disabled even when everything is READY?

Because there is no code anywhere in this project capable of placing a
real broker order. `PaperBroker` is the only concrete broker
implementation in the entire codebase (verified directly, Checkpoint
64.11 and re-confirmed this checkpoint). The Live Paper Readiness
gate's `real_trading_state` field is not a computed value — it is a
literal constant, `"DISABLED"`, on every single response, regardless of
credential state. There is no state this application can be in that
enables real order placement.
