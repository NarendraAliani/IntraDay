# frontend

## Responsibility

Presentation layer for a non-technical end user (Section 12). Framework locked at Checkpoint 3: React + TypeScript + Vite (see [TECHNOLOGY_MAPPING.md](../docs/architecture/TECHNOLOGY_MAPPING.md) §8); structure here remains domain-aligned, framework-agnostic in shape.

**Checkpoint 9** added the first real screen — a read-only Configuration
Viewer under `src/features/configuration/`, consuming the Checkpoint 8
business API via generated TypeScript contracts. See
[../docs/api/FRONTEND_API_CONSUMPTION.md](../docs/api/FRONTEND_API_CONSUMPTION.md)
for the full contract-generation pipeline, API client design, and dev
workflow.

### Directory layout (as of Checkpoint 9)

- `src/app/` — application root (`App.tsx`) and global styles.
- `src/common/` — app-local shared code: the API client
  (`common/api/client.ts`, `common/api/configApi.ts`) and shared UI
  components (`common/components/`: loading/error/empty states, active
  badge). Deliberately named `common/`, not `shared/`, to avoid confusion
  with the repo-level `frontend/shared/` (generated contracts, `@shared`
  alias) below.
- `src/features/configuration/` — the Configuration Viewer screen.
- `src/test/` — Vitest setup (`setup.ts`).
- `shared/` — repo-level, cross-cutting frontend architecture; currently
  only `shared/generated_contracts/` (see its own README). Imported via
  the `@shared/*` path alias.

### Local development

```
npm install
npm run generate:api   # regenerate OpenAPI -> TypeScript contracts
npm run dev            # start the Vite dev server
npm run typecheck
npm run test
npm run build
```

Copy `.env.example` to `.env.local` to override `VITE_API_BASE_URL` for
local development (defaults to the local Django dev server).

## Depends On

application/contracts

## Must Not Depend On

domain internals, infrastructure internals, database technology directly

