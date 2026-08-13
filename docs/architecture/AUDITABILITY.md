# Auditability

Checkpoint 12. Establishes the durable, append-only control-plane audit
trail — the first real code in `control_plane/audit` (previously an
architecture placeholder since Checkpoint 1). Scope: **risk-configuration
activation only**. Universe/strategy-version activation are intentionally
NOT audited this checkpoint — see [Scope](#scope) below.

## Login-CSRF (closing Checkpoint 11's deferred gap)

Checkpoint 11 deliberately deferred login-CSRF protection: DRF's
`APIView.as_view()` wraps every view in Django's `csrf_exempt()` by
default, delegating CSRF enforcement to
`SessionAuthentication.enforce_csrf()` — which only runs once a session
user is already resolved. An anonymous `POST /api/v1/auth/login/` was
therefore never CSRF-checked, a real (if secondary) risk: a cross-site
`<form>` on an attacker's page can still fire a genuine POST to the login
endpoint (CORS restricts *reading* a cross-origin response via JS, not
*sending* a form submission), potentially logging a victim's browser into
an attacker-controlled account.

**Fixed this checkpoint**: `infrastructure/api/auth_views.py`'s
`login_view.csrf_exempt = False` re-enables Django's real
`CsrfViewMiddleware` for this one view — the same, real,
framework-provided mechanism protecting every other state-changing
endpoint, not a hand-rolled scheme and never `@csrf_exempt`. No frontend
change was required: the frontend already calls `GET
/api/v1/auth/session/` on load (which sets the `csrftoken` cookie) before
a user can submit the login form, and `client.ts` already attaches
`X-CSRFToken` to every `POST`, login included. Verified by test
(`test_login_is_rejected_without_a_csrf_token`,
`test_legitimate_login_succeeds_with_a_valid_csrf_token`).

## Audit ownership

`control_plane/audit` (bounded context, `.importlinter` contract #3:
"Application -> bounded contexts -> domain layering") owns the
technology-neutral vocabulary: `ActivationOutcome` (the enum of what
actually happened) and `AuditEvent` (the read-side value object).
`application/repositories.AuditRepository` is the read-only Protocol
interface; `infrastructure/persistence` provides the concrete
implementation — `AuditLogEntry` (the Django model),
`DjangoAuditRepository` (the read path), and the write path embedded
inside `DjangoRiskConfigurationRepository.activate()` (see
[Transactional Coupling](#transactional-coupling)). This mirrors the
existing risk/universe/strategy layering exactly — no new architectural
pattern was introduced.

## Scope

Only `POST /api/v1/config/risk/{id}/{version}/activate/` writes audit
events this checkpoint. Universe and strategy-version activation remain
unaudited, per the checkpoint brief's explicit instruction not to expand
scope. The domain vocabulary (`resource_type`/`resource_id`, not
`risk_configuration_id`-specific) and the model's `resource_type` field
are already generic enough to extend to them later without a redesign —
extending write-side coverage would mean repeating the same
`activate()`-method change made here for
`DjangoUniverseRepository`/`DjangoStrategyVersionRepository`.

## Audit data model

`infrastructure/persistence/models.py`'s `AuditLogEntry`:

| Field | Purpose | Immutable | Indexed | Sensitive |
|---|---|---|---|---|
| `occurred_at` | WHEN — UTC, set explicitly by the writer (never `auto_now_add`), matching the moment the state change was computed. | Yes | Yes (`db_index=True`, plus the composite index below) | No |
| `actor_username` | WHO — a plain string **snapshot** of `User.get_username()`, not a ForeignKey. | Yes | No | No (a username, not a credential) |
| `actor_user_id` | WHO (correlation) — the numeric pk at the time of the action, plain integer, not a ForeignKey. | Yes | No | No |
| `action` | WHAT — a stable token, `"configuration.activate"`, matching the `configuration.read`/`configuration.activate` capability vocabulary already established in `infrastructure/api/permissions.py` (Checkpoint 11). | Yes | No | No |
| `resource_type` | WHICH RESOURCE — `"risk_configuration"`. | Yes | Yes (composite) | No |
| `resource_id` | WHICH RESOURCE — the configuration id. | Yes | Yes (composite) | No |
| `version_identifier` | WHICH VERSION — the target of the activation request. | Yes | No | No |
| `previous_version` | CONTEXT — what was active immediately before (nullable: `None` when there was no prior active version). | Yes | No | No |
| `outcome` | RESULT — one of `activated`/`already_active`/`rejected` (see [Outcome Semantics](#outcome-semantics)), never free text. | Yes | No | No |
| `request_id` | Correlation — a UUID4 string, one per HTTP request (see [Request/Correlation Identity](#requestcorrelation-identity)). | Yes | No | No |

No field was added merely because it sounded useful — every row above
answers one of the WHO/WHAT/WHICH RESOURCE/WHEN/RESULT questions the
checkpoint brief specifies, or (`previous_version`) the minimum "why/
context" needed for a record to be meaningful standing alone.

## Actor identity: why plain strings, not ForeignKeys

`actor_username`/`actor_user_id` are plain columns, **not**
`ForeignKey(User)`. A ForeignKey would force one of two bad outcomes if
the user account is later deleted: cascade-deleting the audit rows
(destroying exactly the historical record an audit trail exists to
preserve) or `on_delete=PROTECT` (silently making user deletion
impossible forever — an operational trap nobody would discover until
they tried it). A plain string/integer snapshot survives both user
deletion and username reuse — the same trade-off `git blame` makes with
historical author names, and the standard, accepted pattern for
append-only logs. There is no code path that creates a row without a
real actor: `IsAuthenticated`/`IsConfigurationOperator` (Checkpoint 11)
already reject the request before the view (and therefore the service,
and therefore the repository) is ever reached, so `actor_user_id` is a
required, non-nullable field with no anonymous/placeholder default.

## Transactional coupling

The state change and its audit record commit together, or not at all.
`DjangoRiskConfigurationRepository.activate()` wraps the
`ActiveRiskConfiguration` write and the `AuditLogEntry.objects.create()`
call inside one `transaction.atomic()` block — if the audit insert fails
for any reason, Django rolls back the configuration-state change too.
This is the **only** place a risk configuration's active pointer is
written, so there is no code path that can change it without an
accompanying audit row landing in the same commit.

Verified by `test_activation_rolls_back_if_audit_write_fails`
(`tests/unit/infrastructure/api/test_audit_api.py`): forces the audit
`INSERT` to fail via `unittest.mock.patch` on
`AuditLogEntry.objects.create` (a real `DatabaseError`, not a mocked
service), then asserts **neither** the `ActiveRiskConfiguration` pointer
**nor** the audit row exist afterward. This exercises the real
`transaction.atomic()` boundary against a real PostgreSQL connection
(`@pytest.mark.django_db(transaction=True)`), not a fully-mocked
application service.

**Failed activation (unknown version) is the one deliberate exception**:
a `REJECTED` audit row is written in its own, independently-committed
statement, *before* the `ValueError` is raised — it must survive even
though the activation itself did not happen, per the checkpoint brief's
"the system must not claim success when activation failed," which cuts
both ways: a failed attempt is not silently unrecorded either.

## Outcome semantics

`ActivationOutcome` has exactly three values, chosen to reflect what
*actually happened*, never merely "the request was accepted":

- `activated` — the active pointer was created or changed to the
  requested version.
- `already_active` — the requested version was already active; nothing
  changed (Checkpoint 10's established idempotency). Recording this as
  `activated` would be a false state-transition claim; the audit trail
  must be able to answer "did this actually change anything?" honestly.
- `rejected` — the requested version does not exist for this
  configuration id; no state change occurred.

Verified by test: activating twice records `["activated",
"already_active"]` in that order
(`test_already_active_activation_records_already_active_not_activated`);
an unknown-version attempt records `rejected`, and no pointer is created
(`test_failed_activation_records_rejected_not_success`).

## Authorization / security events

**Authorization-denied attempts (HTTP 403 — an authenticated
non-operator, or an anonymous caller) are NOT written to the durable
audit table this checkpoint.** This is a deliberate, documented boundary
choice, not an oversight: `IsAuthenticated`/`IsConfigurationOperator`
reject the request in DRF's permission-checking phase, before the view
body (and therefore the service and repository, where the write path
lives) ever runs. Capturing these denials in the durable audit table
would require either duplicating write logic into the permission class
itself (mixing an authorization *check* with a persistence *side
effect*, and running write I/O on every single rejected request,
including anonymous scans) or a global exception-handler hook — judged
not worth the added complexity and I/O-on-every-403 cost for this
checkpoint, versus the value of the "meaningful" trail the brief asks
for. What *is* captured: every attempt that reached an authenticated,
authorized principal — including one that then turned out to target an
invalid version (`rejected`, above). Anonymous rejections are never
audited at all (would be pure noise from unauthenticated probes and bots,
per the brief's own "do not create an audit record for every anonymous
rejected HTTP request").

## Request / correlation identity

No request/correlation-ID infrastructure existed anywhere in this
codebase before this checkpoint (searched: no middleware, no
`structlog.contextvars` binding of a request id, despite
`structlog.contextvars.merge_contextvars` already being configured in
`settings/base.py` for a future such use). Building a full
request-tracing/observability system was judged out of scope for this
checkpoint. The smallest useful addition was made instead: a UUID4 is
minted inline, once per activation HTTP request, in
`infrastructure/api/risk_views.py`'s `activate` view
(`request_id = str(uuid.uuid4())`), threaded through the service and
repository, and stored on the audit row. This lets a single request be
correlated across audit events (relevant once other actions are audited
in a future checkpoint) without introducing new middleware or a
competing ID scheme.

## Audit repository / service architecture

```
API (infrastructure/api/risk_views.py: activate)
  -> Application Service (RiskConfigurationService.activate)
    -> Persistence (DjangoRiskConfigurationRepository.activate)
        - state change (ActiveRiskConfiguration)
        - audit append (AuditLogEntry)
      -> commit (one transaction.atomic() block)
```

The write path is intentionally **not** exposed through a Protocol —
`AuditRepository` (in `application/repositories`) has only
`list_for_resource()`, a read method. Exposing a generic
`AuditRepository.append()` write method would let a future caller invoke
it independently of a real state change, breaking the transactional
coupling guarantee above; the write only exists inside the one
repository method that also performs the state change it records. This
is deliberately not generalized into a reusable "event sourcing" or
"generic audit-any-action" framework — it is scoped tightly to
risk-configuration activation, extensible later by repeating the same
pattern, not by building an abstraction layer speculatively now.

## Audit API

**Implemented**, minimal: `GET /api/v1/audit/risk-configuration/{configuration_id}/`
returns every recorded event for that configuration id, newest first.
No `POST`/`PUT`/`PATCH`/`DELETE` audit operation exists anywhere in the
API surface.

Permission: `IsAuthenticated` + `IsConfigurationOperator` — the **same**
gate as activation itself, not a separate `audit.read` Group/capability.
Audit visibility is treated as an operator-level governance capability:
an ordinary `configuration.read` user can see the current configuration
state but not who changed it, when, or from what — a deliberate,
documented choice to keep "who did what" visibility scoped to the same
population already trusted to *do* the state-changing action, rather
than broadening it to every authenticated user by default.

## Audit frontend

**Deferred.** No Audit History screen was built this checkpoint — the
checkpoint brief explicitly permits deferring this ("Do NOT build a full
Audit History screen unless it is genuinely required to validate the
architecture... If deferred, document..."). The generated TypeScript
contract (`frontend/shared/generated_contracts/api-types.ts`) was still
regenerated to include `AuditEventResponse` and the new operation (the
brief requires this whenever a real audit API is implemented, regardless
of whether a UI consumes it yet) — these are real, generated types
matching a real, implemented endpoint, not speculative/hand-invented
frontend types.

- **Audit persistence: implemented.**
- **Audit API: implemented** (read-only, minimal).
- **Audit UI: deferred.**

## Sensitive data policy

Never stored on `AuditLogEntry`, and verified never to appear in the
audit API's response body (`test_audit_response_never_contains_sensitive_fields`):
passwords, session ids, CSRF tokens, cookies, access tokens, broker
credentials, database passwords, secret keys, or the raw request body/
headers. Only the explicit, whitelisted field list in the schema table
above is ever written — no generic "metadata" or "details" JSON blob
exists that could accidentally accumulate sensitive data over time.

## Append-only enforcement

**Application-level, verified by test — not database-level.**
`AuditLogEntry.save()` checks `self._state.adding` (Django's own marker
for "not yet persisted") and raises `RuntimeError` on any attempt to
save an already-persisted row (i.e. any `UPDATE`). `AuditLogEntry.delete()`
unconditionally raises `RuntimeError`. Both are verified by test
(`test_audit_record_cannot_be_updated_through_normal_api`,
`test_audit_record_cannot_be_deleted_through_normal_api`) — not merely
"the frontend has no edit button."

**Explicit limitation**: this is enforcement inside the Django model
layer, not a database-level guarantee (no `REVOKE UPDATE, DELETE` grant,
no rejecting trigger). A sufficiently privileged database credential, a
raw SQL statement, or Django code that bypassed the ORM (e.g.
`AuditLogEntry.objects.filter(...).update(...)`, which does **not** call
`.save()` and would not be caught by this guard) could still mutate a
row. True database-level immutability was judged out of scope for this
checkpoint — a documented gap, not a false claim of stronger guarantees
than exist. A future checkpoint could add a `REVOKE`/trigger-based
guarantee if the threat model (e.g. a compromised application credential)
justifies it.

## Retention policy

**Deferred, deliberately.** No automatic deletion, TTL, Celery cleanup
task, or cron purge was added — audit records are governance records,
and a retention policy must be established deliberately (regulatory/
compliance requirements, storage-growth analysis) before any cleanup
mechanism exists, not implied by a checkpoint that was building the
write path for the first time. Every `AuditLogEntry` row created is kept
indefinitely until a future, deliberate retention decision is made.

## Trading safety

No file under `trading_engine/`, `control_plane/kill_switch`,
`infrastructure/brokers/`, or any `TRADING_MODE`-resolution code was
touched. No broker API call, order placement, position-management code,
or strategy-execution code exists anywhere this checkpoint's changes
reach. Verified by diff review of every changed file (all are
`control_plane/audit`, `application/{repositories,services,contracts}`,
`infrastructure/{api,persistence}`, and test files) and by the unchanged
pytest pass count outside the new/updated tests.
