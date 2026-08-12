# application/contracts

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Canonical API/schema contracts (OpenAPI-style, technology-neutral) — single source of truth so backend and frontend never duplicate parameter/state definitions (Rule 13).

**Domain contract vs. API contract, clarified at Checkpoint 2 (Section 8):**
a `domain/*` contract states the *business meaning* of a concept (e.g. what a
Signal is) with no I/O shape. An API contract here is the *wire-level*
request/response shape exposed to callers — it may be a thin passthrough of a
domain contract, or a DTO combining/pagination-wrapping several domain
contracts for one screen's needs (e.g. a dashboard summary combining Signal +
Position + Risk data). API contracts may depend on and reshape domain
contracts; they must never invent new business meaning that isn't traceable
back to a domain contract, and must never leak infrastructure/storage shape
(e.g. a database row) into the wire format.

**Implemented at Checkpoint 8:** DRF `Serializer` classes for the
configuration API resources (risk, universe, strategy version) plus the
shared `ApiErrorSerializer`. See
[docs/api/CONFIGURATION_API.md](../../docs/api/CONFIGURATION_API.md).

**Note on the "any specific API framework" guardrail below:** this was
written at Checkpoint 1, before Checkpoint 3 locked Django REST Framework
as the API technology. Now that DRF is the locked choice (not merely a
placeholder), using DRF `Serializer` classes here is consistent with the
rest of the codebase's technology mapping — it is not a violation of the
original *intent* (never invent business meaning not traceable to a
domain contract; never leak infrastructure/storage shape), only an update
to wording that predates the technology decision it now describes.

## Depends On

domain, application/config_schema, application/repositories (for the dataclasses these serializers represent), Django REST Framework (locked at Checkpoint 3)

## Must Not Depend On

infrastructure (mechanically enforced by `.importlinter` contract #6); domain dataclasses must never inherit from or depend on a serializer here (the coupling runs one way only)

