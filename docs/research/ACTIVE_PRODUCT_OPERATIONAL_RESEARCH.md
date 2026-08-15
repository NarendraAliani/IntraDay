# Active Product Operational Research (Checkpoint 36 Part 2 & Part 21)

Fresh external research for this checkpoint's active-product audit.
Confidence tags follow the project's established convention:
`VERIFIED_PRIMARY` (fetched directly from the authoritative source this
session), `VERIFIED_SECONDARY` (corroborated via reputable secondary
sources, primary source unreachable or non-specific this session),
`UNVERIFIED` (single weak source), `CONTRADICTED` (sources disagree).

## 1. Dhan Sandbox API (Part 21 — dedicated investigation)

### What was attempted

- `WebFetch` of `https://docs.dhanhq.co/api/v2/sandbox` (the primary docs
  URL) again this checkpoint — same as Checkpoint 35's attempt — returned
  no sandbox-specific content ("cannot find specific information about the
  Dhan Sandbox API" from the page's actually-rendered content). This is
  almost certainly a JS-rendered documentation page that a plain markdown
  fetch cannot execute; this is a tooling limitation of this session, not
  evidence the sandbox doesn't exist or work as described.
- `WebSearch` for "Dhan HQ Sandbox API trading simulation documentation
  2026" returned corroborating detail from secondary sources:
  `docs.openalgo.in/connect-brokers/brokers/dhan-sandbox` and
  `marketcalls.in`'s dedicated Dhan Sandbox writeup.

### Findings (VERIFIED_SECONDARY — primary source not directly readable this session)

- Sandbox is a fully simulated environment: **no order is routed to a real
  exchange**.
- **All orders fill at a fixed price of ₹100**, regardless of the
  instrument's real market price — this is a hard constraint that makes
  the sandbox unsuitable for validating actual fill-price realism,
  slippage modeling, or P&L correctness. It is suitable only for testing
  API integration mechanics (auth, request/response shapes, order
  lifecycle transitions, error handling).
- **Capital resets to ₹10,00,000 every day** — no session-to-session
  capital continuity, so it cannot be used to validate multi-day paper
  P&L tracking either.
- **No static IP required** (a real requirement for Dhan's live/production
  API, per this project's own `DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md`)
  — this materially lowers the operational barrier to trying it.
- Signup is separate and lightweight: `developer.dhanhq.co`, email +
  mobile, no funded Dhan account required.

### Decision: `USE_LATER`

Not `USE_NOW`: the fixed ₹100 fill price makes it useless for anything
this project currently needs from paper trading (realistic fills against
this project's own `PaperBroker` pricing model, P&L correctness). Using it
today would mean building a second, parallel "paper broker" concept
alongside the existing in-process `PaperBroker` (Checkpoint 32-35) for no
present benefit — exactly the kind of premature, parallel-framework
expansion this checkpoint's principles forbid.

Not `DO_NOT_USE`: it is a real, free, no-static-IP-required environment
for validating the **wire protocol** of a future real Dhan
`BrokerGateway` adapter (`trading_engine/broker_abstraction`) — request
shapes, auth flow, error responses, rate limits — before that adapter ever
touches a funded or even a real-fill-price account. That is a distinct,
legitimate future use case: **adapter development and protocol
conformance testing, not paper-trading fill simulation.**

**Recommended trigger to revisit:** the checkpoint that first begins real
`BrokerGateway` implementation work against Dhan (not before — building
against a fixed-price sandbox before there's a concrete adapter to test
would itself be premature).

## 2. Existing findings re-confirmed, not re-litigated

`docs/research/TRADING_UI_UX_RESEARCH.md` (Checkpoint 35) and
`docs/research/ACTIVE_PRODUCT_READINESS_RESEARCH.md` (Checkpoint 34) are
not superseded by this checkpoint; their findings stand. This document
adds only what is new this checkpoint (the Dhan Sandbox deep-dive above)
plus the dependency-security findings below, which belong here because
they came from external advisory databases, not code inspection.

## 3. Dependency security research (feeds Part 19)

### Frontend (`npm audit --json`, run against `frontend/package-lock.json`)

5 vulnerabilities, **all in devDependencies** — `esbuild`, `vite`,
`vite-node`, `vitest`, `@vitest/mocker`:

| Advisory | Severity | Package | Real-world applicability to this project |
|---|---|---|---|
| `GHSA-5xrq-8626-4rwp` | Critical (CVSS 9.8) | `vitest` | Requires the Vitest **UI server** to be actively listening and reachable. `grep -rn "\-\-ui"` across `frontend/` and `package.json` scripts finds no such usage anywhere in this project's tooling. Not exploitable in this project's actual usage pattern. |
| `GHSA-fx2h-pf6j-xcff` | High | `vite` | Path-traversal in the Vite **dev server**. `frontend/vite.config.ts` binds the dev server to `127.0.0.1` explicitly (not `0.0.0.0`), and the dev server is never run in production. Not remotely exploitable as configured. |
| 3 moderate | Moderate | `esbuild`, `vite-node` | Transitive, dev/build-tool only; none run in the shipped frontend bundle. |

Fix requires **semver-major** upgrades (`vitest` 3.x -> 4.1.10, `vite` 6.x
-> 8.2.1) that would need full compatibility verification against the
104-test frontend suite before adopting — not attempted this checkpoint
per the explicit "do not blindly force-upgrade" instruction. Classified
**P2** (real but low-practical-risk given actual usage; needs a dedicated
tooling-upgrade checkpoint, not a rushed fix bundled into a feature
checkpoint).

### Backend (`pip-audit`, run against a filtered `pip freeze` — the local
editable self-install line was excluded; it made `pip-audit` attempt to
`git fetch` a commit that only exists locally and was never pushed,
which is expected given this project's "never push" invariant, not a
real vulnerability)

8 known advisories across 2 packages, **both dev-only**:

| Package | Version | Advisories | Where it comes from |
|---|---|---|---|
| `pytest` | 8.4.2 | `PYSEC-2026-1845` (fix: 9.0.3) | `[tool.poetry.group.dev.dependencies]` directly — the test runner itself; never imported by production code. |
| `starlette` | 0.52.1 | `PYSEC-2026-161`, `-248`, `-249`, `-2280`, `-2281` (fixes: 1.0.1 / 1.3.0 / 1.3.1 / 1.1.0) | Transitive, via `schemathesis` and `starlette-testclient` (both `[dev]` group, used only for API contract testing) — not a runtime dependency of the Django application at all. |

Neither package is imported by any module under `src/intraday/` outside
the test suite (`grep -rn "^import starlette\|^from starlette"
src/intraday/` and the equivalent for `pytest` return nothing in
production code paths). Classified **P3** — real advisories, zero
production exposure; a version bump of `pytest`/`schemathesis` is safe to
do in a routine dependency-maintenance pass but not urgent.

**No production/runtime dependency (Django, DRF, `pandas`, broker/market-
data libraries) has a known vulnerability as of this audit.**
