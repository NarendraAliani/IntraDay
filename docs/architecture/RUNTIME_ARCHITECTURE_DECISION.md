# Runtime Architecture Decision — Persistent Market-Data Process

Checkpoint 32 Parts 2-3. **A design/decision document only — nothing in
this document is implemented this checkpoint.** Resolves the
persistent-process hosting gap identified at Checkpoint 23 and
re-confirmed blocking at Checkpoint 31 (`docs/research/
TRADING_GRADE_BAR_VALIDATION.md` §5): this Django/WSGI application has
no already-running long-lived process able to safely host a WebSocket
client, and Docker remains permanently deferred per this project's own
invariant rules.

This checkpoint explicitly re-examined whether "Docker remains
deferred" is still the right call (per Checkpoint 32's own
instruction: "Docker remains deferred unless the architecture
documents explicitly reconsider whether that old decision still
remains valid") — **conclusion: still valid, unchanged.** Nothing
about the WebSocket-hosting problem requires containerization
specifically; it requires a long-lived process, which every option
below can provide without Docker.

## Options Compared

### Option A — Dedicated ASGI process (Django Channels)

`asgi.py` already exists as an unused Checkpoint-1 stub with an empty
`ProtocolTypeRouter`. Channels is already an installed dependency
(`docs/architecture/TECHNOLOGY_MAPPING.md` §2 names it as the intended
staging/production entrypoint). This option runs `daphne`/`uvicorn`
serving `intraday.asgi:application` as a second, separate process
alongside the existing WSGI process — the ASGI process would host a
long-lived background task (e.g. an `asyncio` task started from an
`AppConfig.ready()` hook or a dedicated management command) that owns
the WebSocket connection to Dhan.

### Option B — Dedicated Celery worker/process

`celery.py` already exists as Checkpoint-4 infrastructure-only
scaffolding (one smoke task, `CELERY_BROKER_URL` wired to Redis). A
Celery worker is a long-lived process by design. However, Celery's own
execution model is task-dispatch (short-lived units of work pulled
from a queue), not a naturally long-lived, single, stateful connection
holder — running a WebSocket client "inside" a Celery task means
either (a) one task that never returns (works, but fights Celery's own
worker-concurrency/prefetch/timeout assumptions, and Celery's own
documentation discourages tasks that never complete), or (b) a
Celery-adjacent process that merely reuses Celery's broker/settings
plumbing without actually being a Celery task.

### Option C — Dedicated standalone Python worker process (same repo, separately supervised)

A new, small, single-purpose entrypoint (e.g. `manage.py
run_market_data_worker`, a Django management command) that owns the
WebSocket connection directly — no ASGI, no Celery, just a plain
long-running Python process started independently (by a process
supervisor: `systemd`, Windows Task Scheduler/NSSM, `supervisord`, or a
platform's own "worker dyno" concept — deliberately not prescribed
here, since that is an operational/deployment decision, not an
architecture one). This is the smallest possible increment: it reuses
this project's existing `manage.py`/Django settings bootstrap (same
pattern already proven at Checkpoint 4's `celery_smoke_task` and every
`manage.py shell`-driven verification this project has used), without
adopting either Channels' or Celery's own execution model for a
capability neither was designed around (a single persistent outbound
connection, not request/response or task dispatch).

### Option D — No other technically valid non-Docker option was identified

The existing `TECHNOLOGY_MAPPING.md` names exactly two long-lived-
process technologies already adopted by this project (Channels/ASGI,
Celery) plus the plain-Python-process option every Django project can
always fall back to. No additional framework (e.g. a separate
`asyncio`-native micro-framework) is justified by anything in this
project's existing technology mapping — introducing one would be a new
architectural commitment this checkpoint has no mandate to make.

## Decision Matrix

| Dimension | A: ASGI/Channels | B: Celery worker | C: Standalone worker process |
|---|---|---|---|
| Persistence | Yes — long-lived by design | Partial — fights task-dispatch assumptions | Yes — long-lived by design |
| Restart behaviour | Depends on process supervisor (not built-in) | Celery's own worker restart/autoreload applies, but not designed for a never-completing task | Depends on process supervisor (not built-in) |
| Windows/local dev support | Works (`daphne`/`uvicorn` run on Windows) | Works, but Celery's prefork pool has known Windows limitations (commonly run with `--pool=solo` on Windows) | Works identically everywhere `manage.py` already works (proven every checkpoint so far) |
| Production deployment | Requires a second deployable process/port | Requires a Celery worker + broker (Redis) already partially provisioned | Requires a second deployable process, no new infra beyond what already exists |
| Process isolation | Good — separate process from WSGI | Good — separate process, but shares Celery's worker pool with any other future task | Best — a single, dedicated, single-purpose process, nothing else can compete with it for its own event loop |
| Fault isolation | A crash restarts the ASGI process without touching WSGI | A crash restarts the whole worker (and any other tasks queued to it) | A crash restarts only this one process, nothing else depends on it |
| Reconnect handling | Application-level (must be written either way) | Application-level (must be written either way) | Application-level (must be written either way) |
| Observability | Needs custom health surface (Channels has no built-in "my background task is alive" concept) | Celery has built-in task/worker introspection, but not shaped for "is my one long-lived connection alive" | Needs custom health surface (same as A) |
| Graceful shutdown | Needs explicit signal handling in the background task | Celery has built-in graceful worker shutdown, but again shaped for tasks, not connections | Needs explicit signal handling (same as A) |
| Scaling | Not meaningfully "scaled" — one WebSocket connection per Dhan account, so more processes would not help | Same — scaling workers does not parallelize a single account's WebSocket feed | Same |
| Architecture boundaries | Clean — a new process, reusing existing `domain`/`application` layers, no new bounded context | Clean — same reuse | Clean — same reuse |
| Security | Same credential-handling requirements regardless of host process | Same | Same |
| Operational complexity | Medium — a second server process/port to run and monitor | Medium-high — Celery + broker already exist but weren't designed for this shape of work | Low — smallest number of new moving parts |
| Testability | Good — the WebSocket client logic itself is testable in isolation regardless of host process | Good — same | Good — same |
| Future cloud deployment | Natural fit if the platform later adopts Channels broadly (e.g. real-time frontend push) | Natural fit if the platform already runs Celery workers at scale for other reasons | Natural fit for a single-purpose "worker dyno"/systemd-unit deployment model common on most PaaS/VPS targets |

## Recommendation

**Option C — a dedicated, standalone Python worker process, started via
a Django management command, supervised independently of both the WSGI
and (currently idle) ASGI/Celery infrastructure.**

Rationale:

1. It is the smallest genuine increment: no new framework commitment
   (Channels' ASGI routing was designed for request/response and
   channel-groups, not "own one persistent outbound connection and
   nothing else"; Celery was designed for task dispatch, not a
   never-completing task).
2. It has the cleanest fault-isolation story: a crash in the
   market-data worker cannot affect the WSGI request/response path,
   the (currently unused) ASGI router, or any future Celery task.
3. It reuses this project's own most-proven pattern
   (`manage.py <command>`) rather than introducing Channels or Celery
   to production responsibility for the first time under a checkpoint
   explicitly scoped to design, not implementation.
4. Nothing about it requires Docker — it runs identically under a
   process supervisor on a bare VM, a Windows service, or a "worker"
   process type on most PaaS platforms.

**This recommendation is not implemented this checkpoint.** The next
checkpoint that implements live WebSocket ingestion should build
against this decision, starting from the persistent-process contract
in §"Persistent Process Contract" below — and should re-verify this
recommendation still holds before writing code, per this project's own
"do not build on a stale assumption" discipline.

## Persistent Process Contract (defined, not implemented)

The following is the contract a future `run_market_data_worker`
process (or equivalent) must satisfy — documented now so the eventual
implementation has a concrete target, not an open-ended design
question.

**Startup**
- Reads Dhan credentials via the existing, already-approved
  `DjangoDhanCredentialRepository` mechanism — never a new credential
  path.
- Fails fast and loudly (non-zero exit, logged reason) if no
  credential is configured — never starts a connection with a missing
  or invalid credential silently.

**Authentication**
- Same access token used by the existing REST client
  (`infrastructure/market_data_providers/dhan/client.py`) — per
  Checkpoint 25.1's Medium-confidence finding that the WebSocket
  `token` query parameter is the same value as the REST
  `access-token` header (still not explicitly confirmed by Dhan's
  documentation — the eventual implementation must treat this as an
  assumption to verify empirically at connect time, not a given).
- Token expiry (24 hours, documented) requires this process to detect
  an authentication failure mid-connection and stop cleanly rather
  than retry indefinitely against a token that will never become
  valid again without operator action.

**Subscription**
- Subscribes only to the project's existing, small, explicitly
  configured observation universe
  (`MARKET_DATA_OBSERVATION_SYMBOLS`) — never a dynamically-discovered
  or unbounded instrument set.

**Heartbeat**
- Responds to Dhan's documented 10-second ping within the documented
  40-second timeout window - standard WebSocket ping/pong, expected to
  be handled by any conformant client library, but must be verified
  working, not assumed.

**Reconnect / backoff**
- Exponential backoff with a capped maximum interval on any
  disconnect - never a tight retry loop.
- Every reconnect is logged with a timestamp and increments a
  `reconnect_count` (the same field `MarketDataHealthContract` already
  reserves for this purpose - Checkpoint 23, currently always `0` for
  REST polling).

**Shutdown**
- Responds to a standard process-termination signal (SIGTERM on
  POSIX, the equivalent supervisor-issued stop on Windows) by closing
  the WebSocket connection cleanly and exiting - never killed
  ungracefully as the default path.

**Process health**
- Exposes, via the existing persistence layer (not a new ad hoc
  mechanism): last tick timestamp, last bar produced, gap count,
  reconnect count, and a stale-feed flag (no tick received within a
  documented threshold while the market is open).

**Fatal error handling**
- A genuinely unrecoverable error (e.g. persistent authentication
  failure) stops the process and records the failure via the existing
  `MarketDataHealthStatus` model - never silently retries forever
  presenting a false "still trying" state.

**Communication boundaries**
- Writes to the canonical market-data layer
  (`domain/market_data`, via the same `AggregatedBarObservation`
  upsert pattern Checkpoint 24A already established) and to
  `control_plane/market_data_health` - the same two surfaces the
  existing REST-polling path already writes to, so the frontend and
  API layers require no new read path, only a new writer.
- **Must NOT import or call** `trading_engine.order_management`,
  `trading_engine.execution_management`, `trading_engine.risk_engine`,
  or any `domain.broker` type - this worker is an observational
  market-data producer only, exactly like the existing REST-polling
  path (Checkpoint 23 §"Scope boundary"), and this constraint would be
  enforced the same way (a dedicated `test_market_data_worker_boundaries.py`
  architecture test, following the precedent of
  `test_live_market_data_boundaries.py`) once implemented.
