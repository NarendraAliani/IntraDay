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

## Depends On

domain

## Must Not Depend On

Any specific API framework

