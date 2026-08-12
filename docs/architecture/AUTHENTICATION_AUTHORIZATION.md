# Authentication & Authorization Architecture

Checkpoint 11. Establishes the first-generation authentication/
authorization boundary for the IntraDay control plane, protecting the
Checkpoint 8 configuration API (and the Checkpoint 9/10 frontend that
consumes it). See [../api/CONFIGURATION_API.md](../api/CONFIGURATION_API.md)
§3 for the prior "deliberately unauthenticated" decision this checkpoint
supersedes, and [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) for
the decision-log entry.

## 1. Mechanism decision

**Chosen: Django session authentication with secure, HttpOnly cookies +
Django's CSRF protection**, via Django REST Framework's built-in
`SessionAuthentication`.

Rejected alternatives:

| Alternative | Why rejected |
|---|---|
| JWT (access/refresh tokens) | No demonstrated need for a stateless, cross-service token (this is one Django backend, one frontend origin pair, no microservices, no third-party API consumers yet). Would require inventing token storage on the frontend (localStorage is XSS-exposed; an in-memory-only token loses the session on refresh), a refresh-token rotation scheme, and revocation logic Django's session store already provides for free. Chosen against per the checkpoint's own instruction: "Do NOT automatically choose JWT simply because it is common." |
| DRF Token authentication (`rest_framework.authtoken`) | Simpler than JWT but still requires the frontend to store a bearer token somewhere JS can read it (defeating HttpOnly protection) and has no built-in expiry - Django sessions already give bounded expiry (`SESSION_COOKIE_AGE`) and store-side revocation (`logout()` flushes the session) with less code. |
| OAuth2 / SSO / external identity provider | No external identity provider exists or is planned; this is a single-organization internal control plane, not a multi-tenant SaaS product. Explicitly out of scope per the checkpoint brief. |
| Custom cookie/header scheme | Reinvents what Django's session framework + `CsrfViewMiddleware` already provide, correctly, with a decade of hardening. No justification to hand-roll it. |

Why session + HttpOnly cookies fits this architecture specifically:

- Django is already the framework - `django.contrib.auth`, `django.contrib.sessions`, and `CsrfViewMiddleware` were already installed (Checkpoint 4) and required no new framework-level dependency.
- The frontend and backend are (in every environment considered so far) either same-origin (a production deployment serving the built frontend from/adjacent to Django) or a fixed, known cross-origin pair (the Vite dev server) - both are cases session cookies + CORS handle cleanly, unlike a public multi-origin API surface that would push toward tokens.
- HttpOnly cookies are inherently immune to token theft via XSS (a JWT/localStorage token is not) - meaningful for a platform that will eventually gate real state-changing trading-adjacent actions.
- Django's session invalidation (`logout()` flushes the server-side session row immediately) gives real, immediate revocation - a JWT without a server-side denylist cannot be revoked before it expires.

## 2. Identity model

Django's built-in `auth.User` model, unmodified - **no custom user
model** was introduced. `django.contrib.auth` was already an installed
app (Checkpoint 4); its `User`/`Group`/`Session` tables already exist,
requiring no new migration to create them. A custom user model would
only be justified by a genuine domain need (e.g. email-only login, extra
required profile fields) - none exists yet, and introducing one later is
a well-supported Django migration path if that need arises. Per the
checkpoint brief's explicit instruction, this decision is stated rather
than silently assumed.

Fields used: `username`, `password` (Django's own PBKDF2 hashing, never
touched directly), `is_active`, `is_superuser`, and Group membership.

## 3. Authorization model

Three tiers, matching the checkpoint brief's minimum:

| Tier | Capability tokens |
|---|---|
| Unauthenticated | none |
| Authenticated control-plane user | `configuration.read` |
| Configuration operator/admin | `configuration.read`, `configuration.activate` |

Mechanism: **Django's built-in `Group` model**, not a bespoke permission
table or Django's per-model custom-permission mechanism. A single group,
`configuration-operators` (seeded by a data migration -
`infrastructure/persistence/migrations/0002_seed_configuration_operators_group.py`),
grants `configuration.activate`; `is_superuser` also grants it
unconditionally. `configuration.read` requires only `IsAuthenticated` -
every authenticated user has it, no group needed.

Why Groups over Django's per-model custom permissions: custom
permissions attach to a model's `Meta.permissions`, and there is no
natural model that owns "may activate configuration" - it's a capability
over an application-layer action (the same `activate()` use case spans
three different resource types: risk/universe/strategy), not a Django
model CRUD permission. Groups are Django's standard mechanism for a
capability not tied to one model, remain trivially extensible (add more
groups for finer roles later), and required zero new tables.

Enforcement: `infrastructure/api/permissions.py`'s `IsConfigurationOperator`
DRF permission class, combined with `IsAuthenticated` on every write
(`activate`) view; every read view uses `IsAuthenticated` alone. The same
module's `user_capabilities()` function is the single source of truth
both the permission class and the `/api/v1/auth/session/` response body
call - the frontend's capability list and the backend's actual
authorization decision can never independently drift.

## 4. Protected API surface

| Endpoint | Method | Permission |
|---|---|---|
| `/healthz`, `/readyz`, `/version` | GET | Open (unchanged - orchestration probes) |
| `/api/v1/auth/login/` | POST | Open (must be, to authenticate) |
| `/api/v1/auth/logout/` | POST | `IsAuthenticated` |
| `/api/v1/auth/session/` | GET | Open (must answer "am I logged in" for anyone) |
| `/api/v1/config/risk/...` (list/get/active) | GET | `IsAuthenticated` |
| `/api/v1/config/risk/.../activate/` | POST | `IsAuthenticated` + `IsConfigurationOperator` |
| `/api/v1/config/universe/...` (list/get/active) | GET | `IsAuthenticated` |
| `/api/v1/config/universe/.../activate/` | POST | `IsAuthenticated` + `IsConfigurationOperator` |
| `/api/v1/config/strategy/...` (list/get/active) | GET | `IsAuthenticated` |
| `/api/v1/config/strategy/.../activate/` | POST | `IsAuthenticated` + `IsConfigurationOperator` |

HTTP status behavior: DRF's `SessionAuthentication` does not implement
`authenticate_header()` (there is no HTTP challenge scheme to advertise
for a browser session), so an anonymous request to an `IsAuthenticated`
view receives **403 Forbidden**, not 401 - this is DRF's own documented,
standard behavior, not a custom choice. **401** is reserved for
authentication *failure* (a bad login attempt) and for the "session no
longer valid" signal the frontend's `setSessionExpiredHandler` listens
for. **403** covers both "not authenticated at all" and "authenticated
but lacking the `configuration.activate` capability" - the response body
(`error_code`) does not further distinguish these to avoid adding a new
information-disclosure surface; the frontend does not need to distinguish
them either (both cases show the same "you can't do that" UI outcome).

## 5. Login / logout / current-user flow

Three endpoints, all under `/api/v1/auth/` (`infrastructure/api/auth_views.py`):

- **`POST /api/v1/auth/login/`** - body `{username, password}`
  (`LoginRequestSerializer`). Calls Django's `authenticate()` then
  `login()` (which rotates the session key - session-fixation
  protection). Returns `CurrentUserResponseSerializer` on success (200);
  a single generic `401 invalid_credentials` for every failure mode
  (unknown user, wrong password, inactive account) - never distinguishes
  them (no user-enumeration leakage). Throttled to 5 requests/minute per
  client (see §Rate limiting below).
- **`POST /api/v1/auth/logout/`** - requires `IsAuthenticated`. Calls
  Django's `logout()`, which flushes the session store entry (not just
  clearing the cookie) - a leaked/cached cookie from before logout cannot
  be replayed. Returns the anonymous `CurrentUserResponseSerializer` shape.
- **`GET /api/v1/auth/session/`** - always 200, `{is_authenticated,
  username, capabilities}`. Deliberately never 401 for an anonymous
  caller - this endpoint's entire purpose is "let the frontend safely ask
  with no prior assumption." Also the mechanism that guarantees a
  `csrftoken` cookie is set (via `django.middleware.csrf.get_token(request)`,
  Django's own documented pattern for SPA/AJAX clients), so the frontend
  always has a CSRF token available before its first state-changing call.

None of the three ever return a password, session key, or other
credential material in the response body.

## 6. Frontend authentication boundary

`frontend/src/common/auth/AuthContext.tsx` - a single React Context +
`AuthProvider`, not Redux or another state-management library (matches
this project's existing "no heavy framework" pattern for the API layer,
Checkpoint 9 §11). States: `loading` (initial `GET /session/` in flight),
`anonymous`, `authenticated` (carries `username` + `capabilities`).
`login()`/`logout()` call the real endpoints and only ever reflect what
the backend actually returned - the context never assumes a state the
backend hasn't confirmed.

A minimal session-expiry hook (`setSessionExpiredHandler` in
`common/api/client.ts`) drops the frontend back to `anonymous` if *any*
API call comes back `401` (e.g. an expired/invalidated session cookie) -
registered once by `AuthProvider`, not duplicated per screen.

`frontend/src/features/auth/LoginScreen.tsx` - username/password form,
loading/disabled state while authenticating, `role="alert"` error
display using the real `ApiError` message, accessible labels, no
password persistence beyond the current keystroke's controlled input
(never written to `localStorage`/`sessionStorage`).

## 7. Protected Configuration UI

`frontend/src/app/App.tsx` renders `LoginScreen` for `anonymous`/`loading`
and the real Configuration Viewer (with a "Signed in as X / Sign out"
header) only for `authenticated`. **This is a UX convenience, not the
security boundary** - the backend's permission classes (§4) are what
actually reject an unauthorized request; the frontend routing exists so
a legitimate anonymous visitor sees a login form instead of a broken,
half-loaded screen full of 403 errors.

Similarly, `RiskConfigurationPanel.tsx` only renders the "Activate"
button when `useAuth().state.capabilities` includes
`configuration.activate` - again cosmetic. `App.test.tsx`'s end-to-end
test and the backend's `test_permission_cannot_be_bypassed_by_direct_api_request`
together prove the real enforcement point is the server: a non-operator
session gets `403` from the API regardless of what the UI shows or does.

## 8. CSRF architecture

Django's `CsrfViewMiddleware` remains fully enabled (never
`@csrf_exempt`). DRF's `SessionAuthentication.enforce_csrf()` performs
the actual check for API views: it validates the `X-CSRFToken` request
header against the `csrftoken` cookie **whenever a request resolves to a
session-authenticated user** - i.e. for every state-changing call made
by an already-logged-in session (`logout`, all three `activate`
endpoints). The frontend obtains the CSRF cookie via `GET
/api/v1/auth/session/` (called on every app load) and
`client.ts`'s `performRequest()` reads it from `document.cookie` and
attaches it as `X-CSRFToken` on every `POST`.

**Login itself is not CSRF-protected** by this mechanism, because no
session user exists yet at the point `SessionAuthentication.authenticate()`
runs for an anonymous request - this is DRF's standard, documented
behavior, not a gap introduced here. This is a known, accepted
limitation (`login-CSRF`): forcing a victim to authenticate into an
attacker-controlled account. Its usual impact (tricking a victim into
saving data into an attacker's account) does not apply to this
control-plane, which has no per-user generated content to leak that way,
so a bespoke CSRF-on-login mechanism was judged not worth the added
complexity for this checkpoint - documented here rather than silently
left unstated.

Verified by test: `test_csrf_protects_state_changing_requests_once_authenticated`
(`tests/unit/infrastructure/api/test_auth_api.py`) uses
`Client(enforce_csrf_checks=True)` to prove an authenticated POST without
the CSRF header is rejected (403) and the same request succeeds with a
valid token.

## 9. Session / cookie security

- `SESSION_COOKIE_HTTPONLY` - Django's default (`True`), unchanged: the
  session cookie is never readable by JavaScript.
- `SESSION_COOKIE_SAMESITE` - Django's default (`"Lax"`), unchanged:
  sufficient because the frontend and backend are same-site (differ only
  by port) in every environment considered so far; `Lax` still blocks the
  cross-site cases that matter.
- `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` - `False` (Django
  default) in development/testing (plain HTTP locally would otherwise
  never send the cookie at all); `True` in `production.py`, unchanged
  from Checkpoint 4.
- `SESSION_COOKIE_AGE` - new this checkpoint: 8 hours
  (`60 * 60 * 8`), not Django's 2-week default. A deliberate, documented
  bound for a system that can trigger configuration state changes -
  Django's default is too long for this profile.
- Session rotation after login - `django.contrib.auth.login()` calls
  `request.session.cycle_key()` internally, issuing a fresh session
  identifier on every successful authentication (session-fixation
  protection), never reusing whatever anonymous session existed before.
- Logout invalidation - `logout()` flushes the session store entry
  server-side, not merely clearing the cookie (§6). Verified by test
  (`test_session_invalidated_after_logout`).
- Development vs. production - only the `*_SECURE` flags and the CORS/
  CSRF-trusted-origin allowlists differ per environment (see §11); no
  setting claims production security in a non-production settings module.

## 10. Password security

Django's own `PBKDF2PasswordHasher` (the framework default) via
`authenticate()`/`User.objects.create_user()` - no custom hashing was
written. Passwords are never logged (no view logs `request.data`), never
returned in any response body (`LoginRequestSerializer.password` is
`write_only`; verified by test - `test_login_response_never_contains_password`),
and never appear in `.env.example` (that file has never contained user
credentials, only backend/service configuration).

## 11. CORS / development-origin configuration

`django-cors-headers` (new dependency, added this checkpoint) - the
smallest, standard mechanism for the browser to allow a cross-origin
`fetch()` to read the response and attach cookies; hand-rolling CORS
header logic was judged not worth it for a security-sensitive concern
with a mature, minimal library available.

- `base.py`: `CORS_ALLOWED_ORIGINS = []`, `CSRF_TRUSTED_ORIGINS = []` -
  empty by default, no cross-origin access permitted unless an
  environment module explicitly opts in. `CORS_ALLOW_CREDENTIALS = True`
  (required for the browser to send/receive cookies cross-origin) - safe
  specifically because the allowlist is never a wildcard (`CORS_ALLOW_ALL_ORIGINS`
  was never set, and browsers themselves reject wildcard origins for
  credentialed requests).
- `development.py`: explicitly lists the Vite dev server's two hostname
  forms (`http://localhost:5173`, `http://127.0.0.1:5173` - browsers
  treat these as distinct origins even though they resolve to the same
  host) in both `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`.
- `production.py`: reads a single `DJANGO_CORS_ALLOWED_ORIGINS`
  comma-separated env var into both lists - no hard-coded frontend URL
  (none is fixed yet; hosting remains deferred per
  [TECHNOLOGY_MAPPING.md](TECHNOLOGY_MAPPING.md) §22), empty (same-origin
  only) until a real deployment configures it.
- `testing.py`: inherits the empty default - pytest never makes a
  browser-origin request, so no CORS configuration is needed there.

## 12. Rate-limiting assessment

**Implemented, basic.** DRF's built-in, cache-backed `ScopedRateThrottle`
on the login view only, `5/min` per client (IP-keyed by default -
`REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"]`, `settings/base.py`).
No new dependency or distributed rate-limiting subsystem was added - this
reuses the `CACHES` backend already configured per environment (Redis in
development/production, LocMemCache in testing), consistent with the
brief's explicit "do not add an elaborate distributed security subsystem
unnecessarily." This bounds brute-force login attempts without requiring
new infrastructure; a distributed, IP-reputation-aware system would be
worth revisiting once the platform has multiple backend instances behind
a load balancer sharing a single rate-limit view (not the case yet).

## 13. Auditability / identity readiness

Checkpoint 10 identified: no append-only "who activated what, when" log
exists. **This checkpoint establishes the identity data future
auditability needs** (a real authenticated `request.user` now exists on
every activation request) but does **not** build the audit log itself -
not required for authentication to function, and the brief explicitly
scoped it out ("do NOT implement the full audit system unless required
for authentication"). Concretely: `activate()` views
(`infrastructure/api/{risk,universe,strategy}_views.py`) now execute
under `request.user` being a real, identified `User` instance whenever
the request reaches the view body (permission classes already guarantee
this) - a future audit-log checkpoint can pass `request.user.username`/`id`
into an append-only record without any further identity plumbing.

- **Authentication identity: implemented.**
- **Activation audit log: deferred** (unchanged from Checkpoint 10's
  documented gap - `ActiveRiskConfiguration.updated_at` still records
  *when*, not *who* or *what changed from what*).

## 14. Security hardening review

| Setting | development.py | testing.py | production.py |
|---|---|---|---|
| `DEBUG` | `True` | `False` | `False` |
| `ALLOWED_HOSTS` | `localhost`/`127.0.0.1`/`0.0.0.0` | `testserver` | from `DJANGO_ALLOWED_HOSTS` env var |
| `CSRF_TRUSTED_ORIGINS` | Vite dev server origins | `[]` (inherited) | from `DJANGO_CORS_ALLOWED_ORIGINS` env var |
| `SESSION_COOKIE_SECURE` | `False` (Django default) | `False` (Django default) | `True` (Checkpoint 4, unchanged) |
| `CSRF_COOKIE_SECURE` | `False` (Django default) | `False` (Django default) | `True` (Checkpoint 4, unchanged) |
| `SESSION_COOKIE_HTTPONLY` | `True` (Django default) | `True` (Django default) | `True` (Django default) |
| `SECURE_CONTENT_TYPE_NOSNIFF` | Django default (`True`) | Django default | `True` explicit (Checkpoint 4) |
| `X_FRAME_OPTIONS` | Django default (`"DENY"`) | Django default | Django default |
| `SECURE_REFERRER_POLICY` | Django default (`"same-origin"`) | Django default | Django default |
| HSTS | not set | not set | `SECURE_HSTS_SECONDS=31536000` + subdomains + preload (Checkpoint 4) |

No production-only setting was blindly enabled in development (would
break local HTTP development); no development-only relaxation leaked
into `production.py`. This table itself is new (Checkpoint 11) - the
individual settings mostly predate this checkpoint (Checkpoint 4) and are
listed here for a single, current, security-focused reference.

## 15. Known limitations / not production-ready

- No login-CSRF protection (§8) - documented, accepted risk for this
  control-plane's threat model.
- No append-only activation audit log (§13) - deferred.
- No account lockout beyond the login rate limit (§12) - a sustained
  low-and-slow attack across many IPs is not mitigated by a single-IP
  rate limit; acceptable for a first-generation internal control plane,
  revisit if the platform gains external-facing exposure.
- No password-reset/forgot-password flow - out of scope per the
  checkpoint brief ("Do NOT build ... billing, invitations" etc.); an
  administrator resets a password via `manage.py changepassword` until a
  future checkpoint adds a real flow.
- No multi-factor authentication.
- `django-cors-headers`' own dependency-vulnerability status is tracked
  the same way as every other dependency (see `docs/api/FRONTEND_API_CONSUMPTION.md`'s
  npm-audit section and this checkpoint's `pip-audit` run) - no new
  findings from adding it this checkpoint.

Given the above, **production readiness: NOT READY** - this is a real,
backend-enforced authentication/authorization boundary suitable for
continued internal development, not a hardened, externally-exposed
production control plane.
