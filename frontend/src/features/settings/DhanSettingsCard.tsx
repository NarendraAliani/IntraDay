// frontend/src/features/settings/DhanSettingsCard.tsx
//
// Checkpoint 22: Dhan broker connectivity settings card. Read-only
// connectivity configuration ONLY — no order placement, no trading
// controls exist anywhere in this component (matches the backend's own
// scope: infrastructure/brokers/dhan/client.py calls GET /v2/profile
// only).
//
// Write-only secret pattern: the access-token field is always rendered
// blank (never pre-filled with a masked placeholder that looks like a
// real value) - a blank submission means "leave the stored token
// unchanged" (translated to `None` server-side). This mirrors
// application/repositories/provider_settings.py's own documented
// contract exactly.
//
// Read (`configuration.read`) is available to any authenticated user;
// save/test-connection require `configuration.activate` (the existing
// `configuration-operators` group) - reusing exactly the same
// capability the Configuration Viewer's activation controls already
// use, per Checkpoint 22's RBAC-reuse decision.
import { useEffect, useState } from "react";

import {
  getDhanSettings,
  getProviderStatus,
  saveDhanSettings,
  testDhanConnection,
} from "../../common/api/settingsApi";
import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { useAuth } from "../../common/auth/AuthContext";
import { ConnectionStatusBadge } from "../../common/components/ConnectionStatusBadge";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import type {
  ConnectionStatusResponse,
  DhanSettingsResponse,
} from "../../common/api/settingsApi";

type LoadState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; settings: DhanSettingsResponse };

type SaveState = { phase: "idle" } | { phase: "saving" } | { phase: "error"; message: string };

type TestState =
  | { phase: "idle" }
  | { phase: "testing" }
  | { phase: "error"; message: string };

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

// Checkpoint 64: the "Connected" badge above is driven by a CACHED
// connection-test result and can go stale relative to the token's
// actual expiry (Dhan's ~24h token TTL) - this environment's own
// configured token was found genuinely EXPIRED by a live connectivity
// check while that badge still said Connected. This badge is computed
// fresh from the token's own claims on every page load instead.
function TokenStateBadge(props: {
  state: DhanSettingsResponse["token_state"];
  expiresAt: string | null;
}): JSX.Element {
  const labels: Record<DhanSettingsResponse["token_state"], string> = {
    UNCONFIGURED: "Not configured",
    VALID: "Valid",
    EXPIRING_SOON: "Expiring soon",
    EXPIRED: "Expired — renew required",
    MALFORMED: "Unrecognized token format",
  };
  const badgeClass =
    props.state === "VALID"
      ? "badge badge--active"
      : props.state === "EXPIRING_SOON"
        ? "badge badge--pending"
        : props.state === "UNCONFIGURED"
          ? "badge"
          : "badge badge--danger";

  return (
    <span>
      <strong className={badgeClass}>{labels[props.state]}</strong>
      {props.expiresAt && (
        <span className="strategy-config-page__help-text">
          {" "}
          {props.state === "EXPIRED" ? "Expired at" : "Expires at"}{" "}
          {new Date(props.expiresAt).toLocaleString()}
        </span>
      )}
    </span>
  );
}

export function DhanSettingsCard(): JSX.Element {
  const { state: authState } = useAuth();
  const canWrite =
    authState.status === "authenticated" && authState.capabilities.includes("configuration.activate");

  const [loadState, setLoadState] = useState<LoadState>({ phase: "loading" });
  const [status, setStatus] = useState<ConnectionStatusResponse | null>(null);
  const [clientId, setClientId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>({ phase: "idle" });
  const [testState, setTestState] = useState<TestState>({ phase: "idle" });

  useEffect(() => {
    let cancelled = false;

    async function load(): Promise<void> {
      try {
        const [settings, statusResponse] = await Promise.all([
          getDhanSettings(),
          getProviderStatus("dhan"),
        ]);
        if (cancelled) return;
        setLoadState({ phase: "ready", settings });
        setEnabled(settings.enabled);
        setStatus(statusResponse);
      } catch (error) {
        if (!cancelled) {
          setLoadState({ phase: "error", message: describeError(error) });
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSave(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSaveState({ phase: "saving" });
    try {
      const settings = await saveDhanSettings({
        client_id: clientId,
        access_token: accessToken,
        enabled,
      });
      setLoadState({ phase: "ready", settings });
      setClientId("");
      setAccessToken("");
      setSaveState({ phase: "idle" });
    } catch (error) {
      setSaveState({ phase: "error", message: describeError(error) });
    }
  }

  async function handleTestConnection(): Promise<void> {
    setTestState({ phase: "testing" });
    try {
      const result = await testDhanConnection();
      setStatus(result);
      setTestState({ phase: "idle" });
    } catch (error) {
      setTestState({ phase: "error", message: describeError(error) });
    }
  }

  return (
    <section className="settings-card" aria-labelledby="dhan-settings-heading">
      <div className="settings-card__header">
        <h3 id="dhan-settings-heading">Dhan (Broker)</h3>
        {status && <ConnectionStatusBadge status={status.status} />}
      </div>
      <p className="settings-card__description">
        Read-only broker connectivity for account verification. No order placement or trading
        occurs through this platform.
      </p>

      {loadState.phase === "loading" && <LoadingState label="Loading Dhan settings…" />}
      {loadState.phase === "error" && <ErrorState message={loadState.message} />}

      {loadState.phase === "ready" && (
        <>
          <dl className="settings-card__current">
            <dt>Client ID</dt>
            <dd>{loadState.settings.client_id_masked || "Not configured"}</dd>
            <dt>Source</dt>
            <dd>{loadState.settings.client_id_source}</dd>
            <dt>Access token</dt>
            <dd>{loadState.settings.access_token_configured ? "Configured" : "Not configured"}</dd>
            <dt>Token status</dt>
            <dd>
              <TokenStateBadge
                state={loadState.settings.token_state}
                expiresAt={loadState.settings.token_expires_at}
              />
            </dd>
          </dl>

          {canWrite ? (
            <form className="settings-card__form" onSubmit={(event) => void handleSave(event)}>
              <label htmlFor="dhan-client-id">Client ID</label>
              <input
                id="dhan-client-id"
                type="text"
                autoComplete="off"
                placeholder="Leave blank to keep the current value"
                value={clientId}
                onChange={(event) => setClientId(event.target.value)}
              />

              <label htmlFor="dhan-access-token">Access Token</label>
              <input
                id="dhan-access-token"
                type="password"
                autoComplete="off"
                placeholder="Leave blank to keep the current value"
                value={accessToken}
                onChange={(event) => setAccessToken(event.target.value)}
              />

              <label className="settings-card__checkbox">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(event) => setEnabled(event.target.checked)}
                />
                Enabled
              </label>

              {saveState.phase === "error" && (
                <p role="alert" className="dialog__error">
                  {saveState.message}
                </p>
              )}

              <div className="settings-card__actions">
                <button type="submit" disabled={saveState.phase === "saving"}>
                  {saveState.phase === "saving" ? "Saving…" : "Save"}
                </button>
                <button
                  type="button"
                  onClick={() => void handleTestConnection()}
                  disabled={testState.phase === "testing"}
                >
                  {testState.phase === "testing" ? "Testing…" : "Test Connection"}
                </button>
              </div>

              {testState.phase === "error" && (
                <p role="alert" className="dialog__error">
                  {testState.message}
                </p>
              )}
              {status && status.status !== "NOT_CONFIGURED" && status.failure_reason_safe && (
                <p className="settings-card__status-detail">{status.failure_reason_safe}</p>
              )}
            </form>
          ) : (
            <p className="settings-card__readonly-note">
              You have read-only access to this configuration.
            </p>
          )}
        </>
      )}
    </section>
  );
}
