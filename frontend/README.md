# frontend

## Responsibility

Presentation layer for a non-technical end user (Section 12). Framework locked at Checkpoint 3: React + TypeScript + Vite (see [TECHNOLOGY_MAPPING.md](../docs/architecture/TECHNOLOGY_MAPPING.md) §8); structure here remains domain-aligned, framework-agnostic in shape.

**Checkpoint 9** added the first real screen — a read-only Configuration
Viewer under `src/features/configuration/`, consuming the Checkpoint 8
business API via generated TypeScript contracts. **Checkpoint 10** added
the first state-changing human workflow — activating a historical risk
configuration version, with an explicit confirmation dialog, real backend
state refresh, and double-submission protection. **Checkpoint 11** added
the authentication boundary — a login screen, session-cookie-based
`AuthProvider`, and per-capability UI gating (the activation control only
renders for a session with the `configuration.activate` capability;
enforcement remains backend-side regardless). See
[../docs/api/FRONTEND_API_CONSUMPTION.md](../docs/api/FRONTEND_API_CONSUMPTION.md)
and [../docs/architecture/AUTHENTICATION_AUTHORIZATION.md](../docs/architecture/AUTHENTICATION_AUTHORIZATION.md)
for the full contract-generation pipeline, API client design, activation
workflow, authentication model, and dev workflow.

### Directory layout (as of Checkpoint 11)

- `src/app/` — application root (`App.tsx`, routing between `LoginScreen`
  and the authenticated application shell) and global styles.
- `src/common/` — app-local shared code: the API client
  (`common/api/client.ts`, `common/api/configApi.ts`, `common/api/authApi.ts`),
  the authentication boundary (`common/auth/AuthContext.tsx`), and shared
  UI components (`common/components/`: loading/error/empty states, active
  badge, `ConfirmDialog`). Deliberately named `common/`, not `shared/`, to
  avoid confusion with the repo-level `frontend/shared/` (generated
  contracts, `@shared` alias) below.
- `src/features/configuration/` — the Configuration Viewer screen,
  including the risk-configuration activation workflow.
- `src/features/auth/` — `LoginScreen.tsx`.
- `src/test/` — Vitest setup (`setup.ts`) and `testAuth.tsx` (renders a
  component tree with a fixed, network-free `AuthContext` value).
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

