# Provider Connectivity

Checkpoint 22. Documents the three outbound HTTP clients that back the
Settings feature's "Test Connection" action
(`docs/architecture/SETTINGS_ARCHITECTURE.md`), and the encryption
scheme protecting the credentials they use. Read-only/no-side-effect
connectivity checks only — no order placement, no message routing.

## Dhan — read-only broker connectivity

`infrastructure/brokers/dhan/client.py`. **Not** an implementation of
`domain.broker.BrokerGateway` (which requires order-placement,
cancellation, and position-query methods this checkpoint does not
authorize) — a deliberately narrower, standalone
`check_dhan_connectivity(client_id, access_token)` function.

Authoritative source, confirmed via direct fetch of the official
documentation during this checkpoint:
[dhanhq.co/docs/v2/authentication](https://dhanhq.co/docs/v2/authentication/).

- Base URL: `https://api.dhan.co/v2`
- Headers: `access-token: {JWT}`, `dhanClientId: {Client ID}`
- Endpoint: `GET /v2/profile` — Dhan's own documentation describes this
  as "a great test API for you to start integration," requiring only
  the access-token header. It is a read-only account-metadata lookup,
  never an order, position, or fund-transfer endpoint. This is enforced
  as a fact, not just a comment: `test_client.py`'s
  `test_only_calls_the_documented_profile_endpoint_never_an_order_endpoint`
  asserts the exact called URL.
- No official `dhanhq` Python SDK dependency was added. This
  checkpoint's scope is a single authenticated GET request, which the
  project's existing `httpx` dependency performs directly — pulling in
  a full trading SDK's order-placement surface before any order
  capability is authorized would be scope creep, not a convenience.

HTTP status → `ConnectionStatus` mapping:

| HTTP status | Status              |
|-------------|----------------------|
| 200         | `CONNECTED`          |
| 401         | `AUTHENTICATION_FAILED` |
| 403         | `TOKEN_EXPIRED`       |
| other / timeout / network error | `CONNECTION_ERROR` |

`check_dhan_connectivity()` never raises for an ordinary connectivity
failure — every reachable outcome is translated into a
`DhanConnectivityResult`, so the calling view never needs its own
`try`/`except httpx` handling.

## Telegram — Bot API

`communication/adapters/telegram/client.py`. Authoritative source: the
public [Telegram Bot API](https://core.telegram.org/bots/api), stable
and well-documented enough to need no further per-checkpoint research.

- **Connectivity check**: `GET /bot<token>/getMe` — validates the bot
  token without sending anything (Checkpoint 22's "prefer a safe
  connectivity/permission check" requirement). Enforced by
  `test_check_connectivity_never_sends_a_message` — asserts `httpx.post`
  is never called during a connectivity check.
- **Explicit test message**: `POST /bot<token>/sendMessage` with
  `chat_id` + `text` — sends a real, visible message. Only ever invoked
  by a separate, explicit user action; never called automatically or as
  part of a status check.

## Discord — Webhook API

`communication/adapters/discord/client.py`. Authoritative source:
[Discord's webhook resource docs](https://discord.com/developers/docs/resources/webhook).
The webhook URL itself
(`https://discord.com/api/webhooks/{id}/{token}`) **is** the entire
credential — stored and replaced as one opaque value, never split into
a separate id/token pair the official API doesn't ask for.

- **Connectivity check**: `GET <webhook_url>` — Discord returns the
  webhook's own metadata if valid, 404 otherwise. No message is posted.
- **Explicit test message**: `POST <webhook_url>` with a JSON body —
  sends a real message. Same explicit-action-only rule as Telegram.

## Shared connectivity contract

`communication/contracts/connectivity.py`'s `ConnectivityCheckResult`
(`success`, `status`, `safe_error`, `latency_ms`) is shared by the
Telegram and Discord clients only. Dhan deliberately defines its own,
separate `DhanConnectivityResult`
(`infrastructure/brokers/dhan/client.py`) with the same shape, rather
than importing the `communication` bounded context's contract —
`infrastructure/brokers` has no reason to depend on `communication`,
and this checkpoint does not introduce one.

## Safe error messages

Every `safe_error` string is constructed entirely from the HTTP status
code and each provider's own documented error semantics — never by
echoing raw response content, which could itself contain the request's
own header values or an upstream proxy's internals. No client ever
places a token/secret into a status or log message
(`test_access_token_is_sent_only_as_a_header_never_in_the_url_or_body`
proves this for Dhan; the equivalent Telegram/Discord tests prove no
secret appears in a request body echoed anywhere in the result).

## Encryption at rest

`infrastructure/persistence/encryption.py` uses `cryptography`'s
`Fernet` (AES-128-CBC + HMAC, authenticated symmetric encryption) — a
well-audited, standard-library-adjacent primitive, not a hand-rolled
cipher.

Key precedence:

1. `SETTINGS_ENCRYPTION_KEY` environment variable — a real Fernet key
   (`Fernet.generate_key()`), the correct value for any non-development
   deployment. `settings/production.py` **refuses to boot** without it
   (`RuntimeError` at startup), mirroring the existing
   `DJANGO_SECRET_KEY` production-boot-refusal pattern from
   Checkpoint 4.
2. A key deterministically derived from `DJANGO_SECRET_KEY` via
   SHA-256 — a **development-only** fallback, so encrypted values
   remain decryptable across local restarts without every developer
   needing to generate and manage a real key. Never reachable in
   production, by the same `production.py` refusal above.

Encryption round-trips (including tamper detection via
`cryptography.fernet.InvalidToken` → this project's own
`DecryptionError`, which never leaks ciphertext or key material) are
verified in `test_encryption.py`, independent of any Django/ORM layer.

## What "Test Connection" proves — and what it doesn't

A successful "Test Connection" proves the configured credential
authenticates against the real provider **at that moment**. It does
**not** prove:

- The credential will remain valid (Dhan access tokens expire; a
  `CONNECTED` result an hour ago says nothing about now — this is why
  `provider_status` always serves the *last recorded* result with its
  own `last_checked_at` timestamp, not an implicit "still valid"
  claim).
- Trading/order capability — the Dhan check exercises exactly one
  read-only endpoint; a working `/v2/profile` call is not evidence any
  order-placement endpoint (not implemented, not tested here) would
  succeed.

This honesty boundary is why the connection-status model
(`docs/architecture/SETTINGS_ARCHITECTURE.md`'s "Configured ≠
Connected" section) exists at all, rather than a single boolean
"is this working" flag.
