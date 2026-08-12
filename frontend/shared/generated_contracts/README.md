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

**History:** this directory was still empty at Checkpoint 4 — the OpenAPI
generation pipeline was wired and verified (CI ran `manage.py spectacular`
as a smoke check), but no *business* API contract existed yet (only
infrastructure endpoints: `/healthz`, `/readyz`, `/version`, not part of
`application/contracts`'s domain-facing surface and intentionally not
generated into this directory).

**Populated at Checkpoint 9**, once the Checkpoint 8 business API
(`/api/v1/config/...`) existed: `api-types.ts` is now generated here via
`npm run generate:api` (see
[../../docs/api/FRONTEND_API_CONSUMPTION.md](../../../docs/api/FRONTEND_API_CONSUMPTION.md)
for the full pipeline). CI (`.github/workflows/ci.yml`) regenerates this
file on every run and fails the build on any diff against what's
committed — the drift-detection mechanism described above, now active
rather than a placeholder.

## Depends On

application/contracts

## Must Not Depend On

Hand-written duplicate parameter definitions

