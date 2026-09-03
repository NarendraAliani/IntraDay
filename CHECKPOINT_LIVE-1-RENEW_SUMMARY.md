# Checkpoint LIVE-1-RENEW — Credential Renewal Path: OPERATOR ACTION REQUIRED

```
checkpoint: LIVE-1-RENEW
verdict: OPERATOR_ACTION_REQUIRED
new_token_expiry: N/A (not renewed automatically — see reason below)
operator_steps: [see numbered list below]
where_to_enter_token: Settings page → Dhan (Broker) card → Client ID + Access Token fields → Save (saves to the exact DB row effective_credentials() reads)
commit: e6c5... (summary only, no code touched)
```

## Why automatic renewal was NOT attempted

`renew_dhan_token()` (`token_renewal_client.py:63`) only needs the
**already-stored** `client_id` + `current_access_token` — genuinely
automatable, no human login required, *if* the current token is still
`EXPIRING_SOON` (still active). Its own docstring is explicit: **"Never
called automatically for a token already known EXPIRED."**

Checked at **06:55:31 UTC**: the token's recorded `exp` was
**06:49:34 UTC — already ~6 minutes in the past.** Not expiring-soon,
already expired. Dhan's own documented behavior (already recorded
elsewhere in this codebase's own remediation copy,
`live_paper_readiness.py`): *"Dhan's own Renew Token API only extends
an ACTIVE token — an already-expired one must be replaced via Dhan's
Generate Token flow."* Calling `renew_dhan_token()` now would predict-
ably be rejected (401/403) — exactly the kind of known-doomed call this
session's discipline says not to make. Not attempted.

## Operator action required — exact steps

1. Go to Dhan's own developer/trading portal and generate a **fresh
   access token** (Dhan's "Generate Token" flow — this is the
   platform's own re-authentication step; only the operator can do
   this, it is not something stored in this codebase).
2. Copy the new **Client ID** and **Access Token**.
3. **Enter them here**: this app's **Settings page → Dhan (Broker)
   card** (`DhanSettingsCard`) → the **Client ID** and **Access
   Token** fields → click **Save**.
   - This calls `POST /api/v1/config/settings/dhan/save/`
     (`settingsApi.ts:24`), which writes to the same DB-stored
     credential row `DhanSettingsService.effective_credentials()`
     reads everywhere in this codebase (the live worker, the
     supervisor, the historical backfill path) — entering it here is
     sufficient; no separate `.env` edit or management command is
     needed.
4. Once saved, re-run `CHECKPOINT LIVE-1` from Part 0 — its own
   `effective_credentials()` check will pick up the new token
   immediately, no restart of anything required.

**No code was changed. No Dhan network call was made.**
