# Operational Settings

Checkpoint 22. Establishes a Settings UI and API for operational
provider configuration — Dhan (broker connectivity), Telegram, and
Discord (notification channels). This is configuration management for
credentials, not a trading, signal, or business-logic checkpoint: no
order placement, no strategy execution, no signal generation exists
anywhere in this code path.

## Scope boundary

What this checkpoint IS:

- Secure storage (encrypted at rest) of Dhan/Telegram/Discord
  credentials.
- A read/save/test-connection API and Settings UI for each provider.
- A shared, honest connection-status model (`Configured` is not
  `Connected`).
- Configuration precedence between the database (Settings UI) and
  `.env`/environment variables.

What this checkpoint is NOT:

- Order placement, position management, or any Dhan trading endpoint —
  the Dhan client (`infrastructure/brokers/dhan/client.py`) calls
  exactly one endpoint, `GET /v2/profile`, Dhan's own documented
  connectivity-check endpoint.
- A notification-routing/templating framework — Telegram/Discord
  clients expose exactly two operations each (connectivity check,
  explicit test message), not a general messaging system.
- WhatsApp support — the architecture below is provider-agnostic enough
  to add a fourth provider later, but no WhatsApp code exists yet.

## Configuration precedence

```
Settings UI (database) value?
        │
   YES ─┴──→ use it, source = "DATABASE"
        │
        NO
        ↓
Environment variable set?
        │
   YES ─┴──→ use it, source = "ENVIRONMENT"
        │
        NO
        ↓
    source = "UNCONFIGURED"
```

Implemented once, generically, in
`application/services/provider_settings.py`'s `_resolve()` function and
reused identically by all three providers' settings services. A
database value is **never** overwritten by an environment variable on
any read — this resolver only ever reads both sources and picks one; it
has no write-back path to either. `.env`/the environment remains a
permanent bootstrap/fallback source, not a value that gets "promoted"
into the database automatically. Each field (client id, access token,
etc.) resolves its source independently — a Dhan client id saved in the
database and an access token that still falls back to the environment
is a valid, explicitly-reported combination (`client_id_source:
"DATABASE"`, `access_token_source: "ENVIRONMENT"`), not an error state.

This was verified against a genuine, non-synthetic case during this
checkpoint: the local sandbox had a real `DHAN_ACCESS_TOKEN` set at the
OS environment level (outside `.env`, which was blank). The API
correctly reported `access_token_source: "ENVIRONMENT"` before any
Settings-UI save — proving the precedence resolver behaves correctly
against `python-dotenv`'s own documented behavior (`load_dotenv()`
never overrides an already-set OS environment variable), not just
against test fixtures.

## Storage model

One singleton row per provider (`DhanCredential`, `TelegramCredential`,
`DiscordCredential` — `infrastructure/persistence/models.py`),
enforced by application-level convention (`get_or_create(pk=1)`
in `infrastructure/persistence/provider_settings_repositories.py`), not
a database constraint — the same convention this codebase already uses
for `AuditLogEntry`'s append-only invariant. One account, one bot, one
webhook per deployment is the correct model for this checkpoint's scope;
multi-account support is not implied by anything built here.

Secrets (`access_token`, `bot_token`, `webhook_url`) are stored as
`BinaryField`, encrypted via Fernet
(`infrastructure/persistence/encryption.py`) before being written and
decrypted only inside a separately-named `get_decrypted_*()` method —
never inside the safe `get()` method whose entire purpose is to be
handed to the API layer without further scrubbing. See
`docs/architecture/PROVIDER_CONNECTIVITY_ARCHITECTURE.md` for the
encryption-key precedence and connectivity-client details.

Non-secret identifiers (Dhan client id, Telegram channel id) are stored
in plaintext (they are not credentials — Dhan's own documentation
treats `dhanClientId` as an account identifier, not a secret) but are
still masked in every API response (`_mask_identifier()` in
`application/services/provider_settings.py`), since this project treats
all communication configuration as controlled configuration, not merely
"secrets vs. everything else."

## Write-only secret replacement pattern

A save request's secret fields (`access_token`, `bot_token`,
`webhook_url`) are `required=False, allow_blank=True`. The API layer
(`infrastructure/api/settings_views.py`'s `_blank_to_none()`) translates
an omitted or blank field into `None` before calling the repository;
`None` means "leave the stored value unchanged" at every layer below
that translation
(`application/repositories/provider_settings.py`'s own documented
contract). A non-blank value means "replace." This is why the frontend
never pre-fills a secret field with a masked placeholder that looks like
a real value — the field is always rendered blank, and leaving it blank
on submit is itself the "don't change this" action, not a separate UI
affordance.

## Connection status model — Configured ≠ Connected

`ProviderConnectionStatus` (`infrastructure/persistence/models.py`) is
a single model, reused structurally across all three providers, keyed
by `provider`. It tracks the outcome of the **last performed** "Test
Connection" action — saving credentials never updates it. Three
distinct operations exist and are never conflated:

1. **Save settings** (`POST .../save/`) — persists credentials. Never
   performs a connectivity check.
2. **Test connection** (`POST .../test/`) — performs exactly one live,
   read-only outbound check and records the result.
3. **Read status** (`GET .../status/`) — returns the last recorded
   result. Never performs a live check itself (proven in
   `test_settings_api.py`'s
   `test_provider_status_endpoint_never_performs_a_live_check_itself`).

The status enum (`NOT_CONFIGURED`, `CONFIGURED`, `CONNECTING`,
`CONNECTED`, `DISCONNECTED`, `AUTHENTICATION_FAILED`, `TOKEN_EXPIRED`,
`CONNECTION_ERROR`, `DISABLED`) is shared verbatim across all three
providers. `CONFIGURED` and `CONNECTED` are rendered with visibly
different badges on the frontend (`ConnectionStatusBadge.tsx`) — a
configured-but-untested provider is never shown with the same "success"
styling as a provider that has actually authenticated successfully.

## Rate limiting and debounce

Test-connection endpoints are protected two ways:

- **`ScopedRateThrottle`** (`throttle_scope = "provider_connection_test"`,
  `10/min`, `settings/base.py`'s `DEFAULT_THROTTLE_RATES`) — the same
  DRF mechanism and cache backend as the existing login throttle
  (Checkpoint 11), applied per-provider view via `.cls.throttle_scope`
  exactly like `auth_views.py`'s own `login_view.cls.throttle_scope =
  "login"` precedent.
- **A separate 5-second server-side debounce**
  (`_debounced()` in `settings_views.py`), keyed per-provider, guarding
  against the specific case of an accidental double-click re-triggering
  a real outbound HTTP call within the same second — independent of the
  per-user rate limit above.

## RBAC — reused, not reinvented

No new capability token was introduced. Reading settings requires
`configuration.read` (`IsAuthenticated` — any authenticated user);
saving credentials or testing a connection requires
`configuration.activate` (`IsConfigurationOperator`, the existing
`configuration-operators` Group). Provider settings are exactly the
kind of security-sensitive configuration change that capability already
gates for risk/universe/strategy activation (Checkpoints 8–10) — this
was a deliberate reuse decision, verified against the existing
capability-list assertions in `test_auth_api.py` before implementation,
not an oversight.

## Audit trail — reused, not reinvented

Every credential change is recorded in the existing append-only
`AuditLogEntry` table (Checkpoint 12) via
`_audit_credential_change()`, in the same database transaction as the
credential write itself. `action = "settings.provider_credential_changed"`,
`resource_type = "provider_credential"`, `resource_id` is the provider
name, `version_identifier` carries which field(s) changed (e.g.
`"access_token"`, `"client_id,enabled"`) — there is no real "version"
concept for a credential the way there is for risk/universe/strategy
configuration, so this field is repurposed rather than left unused. The
audit entry never contains the secret value itself, only which field
changed (see `test_provider_settings_repositories.py`'s
`test_dhan_save_records_an_audit_entry_without_the_secret_value`). A
no-op save (every field blank/unchanged) writes no audit entry — an
audit trail exists to record real changes, not every API call.

## Frontend

`frontend/src/features/settings/` — three separate card components
(`DhanSettingsCard.tsx`, `TelegramSettingsCard.tsx`,
`DiscordSettingsCard.tsx`), matching this codebase's existing
per-resource panel convention (`RiskConfigurationPanel` /
`UniversePanel` / `StrategyVersionPanel` are likewise three separate
files rather than one generic parameterized panel). Each card:

- Fetches its settings and last-known status on mount (two parallel
  `GET`s — never a live connectivity check on page load).
- Renders masked/safe values only — the generated OpenAPI TypeScript
  contract types (`DhanSettingsResponse` etc.) have no field for a raw
  secret, so there is no code path by which one could leak into the
  DOM.
- Renders the save/test-connection form only for a user whose session
  carries `configuration.activate` — a UX convenience only, not the
  security boundary (the backend's `IsConfigurationOperator` permission
  is what actually rejects an unauthorized write, exactly as
  Checkpoint 11's `RiskConfigurationPanel` already established for
  activation).
- Clears secret input fields after a successful save (never re-displays
  the just-submitted value).

Reachable from a new top-level "Settings" navigation entry in
`App.tsx`, alongside the existing "Configuration" entry — no routing
library was introduced for two screens, a single piece of local state
toggles which one renders, matching this project's existing
no-heavy-framework convention.

## Deferred / explicitly out of scope

- **WhatsApp** — no code. The `ConnectivityCheckResult` contract
  (`communication/contracts/connectivity.py`) is provider-agnostic
  enough that a future WhatsApp adapter could reuse it, but nothing
  here assumes it will look identical.
- **Docker** — unchanged, still deferred to a future "Production
  Hardening/Deployment" checkpoint.
- **Multi-account support** — one Dhan account / one Telegram bot / one
  Discord webhook per deployment is the current, explicit model.
- **Notification routing/templating** — `communication/notification_router/`
  remains an unpopulated placeholder; this checkpoint only proves each
  channel is reachable, not how alerts are composed or routed to it.
