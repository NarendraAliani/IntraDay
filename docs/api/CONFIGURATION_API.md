# CONFIGURATION_API.md

Authoritative documentation for the first business API, implemented at
**Checkpoint 8**. Companion to
[PERSISTENCE_ARCHITECTURE.md](../architecture/PERSISTENCE_ARCHITECTURE.md)
(what is persisted) and
[CONFIGURATION_MANAGEMENT.md](../architecture/CONFIGURATION_MANAGEMENT.md)
(how configuration is validated).

## 1. Architecture

```
HTTP
  ↓
infrastructure/api (DRF views — request/response translation, error mapping,
                     and composition: wires a concrete Django repository into
                     an application service)
  ↓
application/contracts (DRF serializers — declare the OpenAPI shape only;
                        views return plain dicts, matching the pattern
                        established at Checkpoint 4's health.py)
  ↓
application/services (use-case orchestration; depends only on the
                       repository Protocol, never a concrete implementation)
  ↓
application/repositories (Protocol interfaces, Checkpoint 7)
  ↓
infrastructure/persistence (Django ORM implementations, Checkpoint 7)
  ↓
PostgreSQL
```

**Why views live under `infrastructure/api`, not `application/gateways`:**
an HTTP API is a delivery mechanism — a "driving adapter" in
ports-and-adapters terms, the same category as a broker adapter or
persistence adapter. It must compose a concrete repository
(`infrastructure.persistence.repositories.DjangoRiskConfigurationRepository`
etc.) with an application service, which requires importing
`infrastructure.persistence`. `.importlinter` contract #6 forbids
`intraday.application` from depending on `intraday.infrastructure` — so
this composition cannot happen inside `application/`. Placing it in
`infrastructure/api` instead keeps the rule intact: `infrastructure`
depending on `application` is the *allowed* direction (the same direction
`infrastructure/persistence` already used at Checkpoint 7). Verified by
`.importlinter` (still 6/6 kept) and a dedicated architecture test
(`tests/unit/architecture/test_api_boundaries.py`).

## 2. API Versioning

Single prefix: `/api/v1/config/`. No second API version exists or is
planned until a breaking change is actually needed (Checkpoint 8 §14).

## 3. Authentication / Authorization

**None implemented this checkpoint — deliberately.** All endpoints are
currently open (development/infrastructure scope only), consistent with
Checkpoint 3's decision to keep authentication out of scope until a
dedicated checkpoint addresses it. **This must not be mistaken for
"secure enough for production."** The future boundary (Checkpoint 3 §12,
Checkpoint 2 §11): read endpoints will likely stay broadly accessible to
authenticated users, while *activation* (a state-changing operation) must
be gated behind the same operator-role authorization already specified for
AI-proposal approval — not exposed to an anonymous or read-only role. No
fake security (e.g. a no-op permission class) was added to give a false
impression of protection.

## 4. Endpoints

Three resources, each with an identical shape: list, get-active,
get-specific-version, activate. Strategy's identity is a 3-tuple, so its
paths carry three version segments instead of one.

### Risk configuration

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/config/risk/{configuration_id}/` | List all versions |
| GET | `/api/v1/config/risk/{configuration_id}/active/` | Get the active version |
| GET | `/api/v1/config/risk/{configuration_id}/{version}/` | Get a specific version |
| POST | `/api/v1/config/risk/{configuration_id}/{version}/activate/` | Activate a version |

### Universe

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/config/universe/{universe_id}/` | List all versions |
| GET | `/api/v1/config/universe/{universe_id}/active/` | Get the active version |
| GET | `/api/v1/config/universe/{universe_id}/{version}/` | Get a specific version |
| POST | `/api/v1/config/universe/{universe_id}/{version}/activate/` | Activate a version |

### Strategy version

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/config/strategy/{strategy_id}/` | List all versions |
| GET | `/api/v1/config/strategy/{strategy_id}/active/` | Get the active version |
| GET | `/api/v1/config/strategy/{strategy_id}/{specification_version}/{code_version}/{configuration_version}/` | Get a specific version |
| POST | `/api/v1/config/strategy/{strategy_id}/{specification_version}/{code_version}/{configuration_version}/activate/` | Activate a version |

**Deliberately not implemented:** a bare `GET /api/v1/config/risk/` (list
every configuration id across all families). No repository method exists
for "list all configuration ids" — there was no demonstrated need for it
yet (today there is effectively one well-known id, `"default"`), and
inventing one now would be exactly the kind of premature endpoint
proliferation Checkpoint 8 §7 warns against. Add it when a second named
configuration family actually exists.

## 5. Request / Response Contracts

### Risk configuration response

```json
{
  "risk_configuration_id": "default",
  "version": "v1",
  "limits": {
    "max_intraday_loss": "10000.00",
    "max_position_size": "50000.00",
    "max_per_trade_risk": "2000.00"
  },
  "created_at": "2026-01-01T09:20:00Z",
  "is_active": true
}
```

Decimal fields serialize as **strings**, never floats
(`COERCE_DECIMAL_TO_STRING=True`, set at Checkpoint 4) — exact precision
preserved end-to-end from PostgreSQL `NUMERIC(14,2)` to JSON. Timestamps
serialize as ISO-8601 UTC. `is_active` is computed by the view at request
time (by comparing against the service's `get_active()` result) — it is
not a stored property of the immutable version record, since "active" is
a query-time relationship, not an intrinsic fact about a version.

### Universe response

```json
{
  "universe_id": "example",
  "version": "v1",
  "exchange": "NSE",
  "members": [{"instrument_id": "NSE:RELIANCE", "status": "INCLUDED"}],
  "created_at": "2026-01-01T09:20:00Z",
  "is_active": false
}
```

### Strategy version response

```json
{
  "strategy_id": "example-strategy",
  "specification_version": "spec-v1",
  "code_version": "code-v1",
  "configuration_version": "cfg-v1",
  "universe_version": "v1",
  "timeframe": "5m",
  "maturity_state": "IDEA",
  "created_at": "2026-01-01T09:20:00Z",
  "is_active": false
}
```

## 6. Error Contract

Every error response uses this exact, stable shape
(`application/contracts/errors.py:ApiErrorSerializer`):

```json
{
  "error_code": "not_found",
  "message": "risk configuration 'default' has no version 'v9'"
}
```

| `error_code` | HTTP status | Meaning |
|---|---|---|
| `not_found` | 404 | The requested configuration id/version does not exist |
| `invalid_activation` | 404 | Activation referenced a version that does not exist |
| `duplicate_version` | 409 | A version already exists (not reachable via the current read/activate-only API surface — reserved for a future write endpoint) |
| `internal_error` | 500 | An unexpected error — the real exception is logged server-side via structlog and never included in the response body |

No Django exception, SQL error, stack trace, or table name is ever
returned to the client (Checkpoint 8 §10) — verified by a test asserting
the error body never contains `traceback`, `django.db`, `select `, or
`integrityerror`.

## 7. Activation Semantics

- Activation is **idempotent**: activating an already-active version
  returns the same 200 response as the first call (backed by
  `update_or_create` on the active-pointer table — Checkpoint 7).
- Activation **never mutates historical version rows** — only the
  separate active-pointer table changes (Checkpoint 7 §6).
- Activating an unknown version returns `404 invalid_activation`, never a
  500 or a silently-ignored no-op.
- Activation returns the newly-active representation (`200`, not `201` —
  no new resource is created; an existing version's active status
  changed).

## 8. HTTP Status Codes Used

`200` (successful read/activate), `404` (unknown resource or invalid
activation target), `409` (reserved for future duplicate-version write
endpoints — not reachable today), `500` (unexpected error, generic body).
`201`/`400`/`422` were considered and not used: no endpoint *creates* a
new resource via this API yet (no `201`); malformed path segments are
handled by Django's URL resolver itself before reaching a view; no
project convention distinguishes `422` from `400` yet, so it was not
introduced without one (Checkpoint 8 §9: "do not invent status codes
merely for theoretical purity").

## 9. Serialization Details

- Decimal → JSON string (never float) — verified by test.
- `datetime` → ISO-8601 UTC string — verified by test.
- Enum values (`Exchange`, `UniverseMembershipStatus`, `Timeframe`,
  `StrategyMaturityState`) → their string `.value` (e.g. `"NSE"`,
  `"INCLUDED"`, `"5m"`, `"IDEA"`) — stable, matches what
  `application/config_schema` loaders already accept as input, so a
  response body is valid input to the corresponding YAML config loader
  without transformation.
- Universe members (JSONB in PostgreSQL) → a JSON array with a fixed,
  documented shape (`instrument_id`, `status`).

## 10. OpenAPI / Frontend Contract Generation

`python manage.py spectacular --fail-on-warn` succeeds cleanly — every
endpoint, request/response schema, and error schema is present in the
generated schema, with no warnings suppressed.

**TypeScript generation into `frontend/shared/generated_contracts` is
deliberately deferred**, not forgotten: no codegen tool (e.g.
`openapi-typescript`) is installed in `frontend/package.json` yet — the
frontend bootstrap (Checkpoint 4) only established the toolchain, not the
contract-generation step. Wiring it up now, for an API with no frontend
consumer yet, would mean generating and committing TypeScript types
nobody imports — premature. It is also the natural moment CI's current
OpenAPI "smoke check" step (`.github/workflows/ci.yml`, added Checkpoint 4)
should become a *real* drift-diff check, which deserves its own
checkpoint's attention rather than being folded into this one. Both are
explicitly named as the trigger for the next frontend-focused checkpoint.

## 11. Security Notes

- No SQL injection surface: every query goes through the Django ORM via
  the repository layer; no raw SQL exists anywhere in this checkpoint.
- No mass assignment: response bodies are hand-constructed dicts in the
  view layer (`_to_response_dict`), not `ModelSerializer.data` reflecting
  arbitrary model fields — only the fields explicitly listed are ever
  returned.
- No internal Django model primary keys (`id`) are exposed — responses
  use only the domain/application identity fields (`risk_configuration_id`
  + `version`, etc.), never the Django auto-increment `id`.
- Activation only accepts a configuration id + version from the URL path
  (validated against existing rows by the repository) — no arbitrary
  field can be modified through the activation endpoint.

## 12. Performance Notes

- No N+1 query risk: `list_versions` issues one `filter().order_by()`
  query; `get_active` issues at most two simple lookups (pointer, then
  version) — no per-item queries in a loop.
- No pagination added: resource sizes (config versions per id) are small
  and not expected to grow into pagination territory yet; revisit if a
  configuration family accumulates hundreds of versions.
- No caching introduced — not justified yet (Checkpoint 8 §22); each
  request reads directly from PostgreSQL, which is intentional given
  activation must be immediately visible to the next read.
