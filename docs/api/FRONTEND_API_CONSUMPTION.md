# Frontend API Consumption

Checkpoint 9. Describes how the frontend consumes the backend's HTTP API:
the OpenAPI → TypeScript contract-generation pipeline, the generated
contracts directory, the API client, and CI drift detection. See
[CONFIGURATION_API.md](CONFIGURATION_API.md) for the API itself and
[../architecture/TECHNOLOGY_MAPPING.md](../architecture/TECHNOLOGY_MAPPING.md)
§9 for the original technology decision.

## Pipeline overview

```
Django + drf-spectacular          openapi-typescript              React
  (source of truth)      ---->   (codegen, not hand-edited)  ---->  components
  manage.py spectacular          frontend/shared/generated_
                                  contracts/api-types.ts
```

1. `manage.py spectacular` introspects the DRF views/serializers and
   produces an OpenAPI 3.0 schema. **`--format openapi-json` must be passed
   explicitly** — the command's default `--format` is YAML regardless of
   the output filename's extension (a real gap found this checkpoint: a
   file named `openapi.json` written without this flag contains YAML, not
   JSON).
2. `openapi-typescript` converts that schema into a single TypeScript
   declarations file. Nothing under `frontend/shared/generated_contracts/`
   is ever hand-edited — see that directory's own `README.md`.
3. Frontend code imports types from the generated file via the pre-existing
   `@shared/*` path alias (`frontend/tsconfig.json`, configured at
   Checkpoint 4), e.g. `import type { components } from
   "@shared/generated_contracts/api-types"`.

## Regenerating the contracts

From `frontend/`:

```
npm run generate:api
```

This runs `generate:api:schema` (regenerates `openapi.json` at the repo
root — gitignored, an intermediate build artifact, not the committed
contract) followed by `generate:api:types` (regenerates
`frontend/shared/generated_contracts/api-types.ts` — committed). Run this,
inspect the diff, and commit it whenever the backend's API surface changes.

Requires Poetry-managed Python dependencies installed at the repo root
(`poetry install`) and `npm install` run in `frontend/`.

## Determinism

Generation is deterministic given the same schema: `openapi-typescript` is
pinned via `frontend/package-lock.json`
(`devDependencies.openapi-typescript`), and the OpenAPI schema itself is
produced by the same `drf-spectacular` version pinned in `poetry.lock`. No
timestamps or non-deterministic ordering are introduced by either tool in
this project's usage.

## CI drift detection

`.github/workflows/ci.yml` regenerates both the OpenAPI schema and the
TypeScript types on every run and runs `git diff --exit-code` against the
committed `frontend/shared/generated_contracts/api-types.ts`. If the
generated file differs from what's committed — because the backend API
changed but nobody ran `npm run generate:api` and committed the result, or
vice versa — the build fails with a message pointing at the regeneration
command. CI never overwrites or commits the file itself; a human must run
the generation command locally and commit the result.

## API client

`frontend/src/common/api/client.ts` is a small, dependency-free `fetch`
wrapper (no React Query/SWR/axios) exposing `apiGet<T>(path)`:

- `T` is always a `components["schemas"][...]` type imported from the
  generated contract — never a hand-duplicated interface.
- The base URL comes from the `VITE_API_BASE_URL` environment variable
  (see `frontend/.env.example`), defaulting to the local Django dev server
  address when unset. This is a `VITE_*` variable, so it is bundled into
  the built JS and visible to the browser — it must never hold a secret,
  and it doesn't need to (it's just a URL).
- On a non-2xx response, the client decodes the body as
  `components["schemas"]["ApiError"]` (the backend's own
  `ApiErrorSerializer` contract — see `CONFIGURATION_API.md`) and throws
  `ApiRequestError` carrying `status`, `errorCode`, and `message`. If the
  body doesn't match that shape (e.g. an upstream proxy's HTML error page),
  the client falls back to a generic, safe message — it never surfaces raw
  response text, so no Django/SQL internals can leak into the UI.
- A separate `ApiNetworkError` is thrown when `fetch` itself fails (offline,
  DNS, CORS).

`frontend/src/common/api/configApi.ts` wraps the three read endpoints the
Configuration Viewer uses (`listRiskConfigurationVersions`,
`listUniverseVersions`, `listStrategyVersions`), each returning the array of
persisted versions for a given identity — the array already carries
`is_active` per version, so no separate "active" call is needed to
distinguish active from historical.

## Configuration Viewer screen

`frontend/src/features/configuration/ConfigurationViewer.tsx` is a
three-tab (Risk Configuration / Universe / Strategy Version), read-only
screen. Each tab has its own panel component
(`RiskConfigurationPanel.tsx`, `UniversePanel.tsx`,
`StrategyVersionPanel.tsx`) that:

- Accepts an identity (configuration/universe/strategy ID) via a small
  lookup form — the API has no "list all" endpoint, only "list versions for
  a given ID", so the viewer needs an ID to query.
- Renders `LoadingState` / `ErrorState` / `EmptyState` /
  version cards (`frontend/src/common/components/`) for the loading,
  error, empty, and success cases respectively.
- Marks each version with `ActiveBadge`, driven purely by the API's own
  `is_active` field (never a frontend-invented flag), distinguished by
  icon and text, not color alone.

## Environment configuration

Copy `frontend/.env.example` to `frontend/.env.local` (gitignored) to
override `VITE_API_BASE_URL` for local development. No secrets are needed
or permitted in any `VITE_*` variable.

## Testing

`frontend/src/common/api/client.test.ts` and
`frontend/src/features/configuration/RiskConfigurationPanel.test.tsx` mock
only `global.fetch` (the network boundary) — the real generated types, the
real `configApi`/`client` functions, and the real React component are all
exercised together, proving the generated-type → API-client → component
boundary rather than a fully mocked interface.

## Known issues (dev-tooling only)

`npm audit` reports vulnerabilities in `esbuild`/`vite`'s dev server (path
traversal / `server.fs.deny` bypass / NTLMv2 hash disclosure over UNC
paths) — all scoped to `vite`'s dev server, none affecting `vite build`'s
static output. Not force-fixed this checkpoint (`npm audit fix --force`
would force a breaking Vite 8 / Vitest 4 upgrade); tracked here for
re-evaluation at the next dependency bump, following the same
documented-not-hidden pattern used for the Python `pip-audit` exceptions in
`.github/workflows/ci.yml`.
