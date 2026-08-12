# frontend/shared/generated_contracts

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Destination for contracts/types generated from application/contracts, keeping frontend parameter definitions non-duplicated (Rule 13). Generation mechanism locked at Checkpoint 3: OpenAPI 3.x schema (via drf-spectacular) → TypeScript types (via openapi-typescript or equivalent) — see [TECHNOLOGY_MAPPING.md](../../../docs/architecture/TECHNOLOGY_MAPPING.md) §9.

**Drift-detection responsibility, clarified at Checkpoint 2 (Section 9):**

```
domain/* (business meaning) → application/contracts, application/config_schema (API/config contract)
    → frontend/shared/generated_contracts (mechanically generated) → frontend/* (UI)
```

Files in this directory must **never be hand-edited** — any manual edit here
is by definition a drift bug, because it means the frontend and
`application/contracts` have diverged from a single source of truth. A CI
step (GitHub Actions, locked at Checkpoint 3) regenerates this directory from
`application/contracts`'s OpenAPI schema and fails the build on any diff
against what's committed — that check is the concrete mechanism that makes
frontend/backend configuration drift detectable, not merely documented.

**Why this directory is still empty at Checkpoint 4:** the OpenAPI
generation pipeline itself is wired and verified (CI runs
`manage.py spectacular` as a smoke check — see
`.github/workflows/ci.yml`), but no *business* API contract exists yet
(only infrastructure endpoints: `/healthz`, `/readyz`, `/version`, which are
not part of `application/contracts`'s domain-facing surface and are
intentionally not generated into this directory). Generating TypeScript
types now would mean generating types for nothing meaningful — deferred,
not forgotten, to the checkpoint that adds the first real
`application/contracts` entry. This directory remains tracked (not
gitignored) per policy, even while empty.

## Depends On

application/contracts

## Must Not Depend On

Hand-written duplicate parameter definitions

