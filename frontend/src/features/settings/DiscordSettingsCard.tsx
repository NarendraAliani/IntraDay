// frontend/src/features/settings/DiscordSettingsCard.tsx
//
// Checkpoint 22: Discord notification-channel settings card. Mirrors
// DhanSettingsCard.tsx/TelegramSettingsCard.tsx's structure exactly. The
// webhook URL is the entire credential (no separate id/secret split) -
// stored and replaced as a single write-only field.
import { useEffect, useState } from "react";

import {
  getDiscordSettings,
  getProviderStatus,
  saveDiscordSettings,
  testDiscordConnection,
} from "../../common/api/settingsApi";
import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { useAuth } from "../../common/auth/AuthContext";
import { ConnectionStatusBadge } from "../../common/components/ConnectionStatusBadge";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import type {
  ConnectionStatusResponse,
  DiscordSettingsResponse,
} from "../../common/api/settingsApi";

type LoadState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; settings: DiscordSettingsResponse };

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

export function DiscordSettingsCard(): JSX.Element {
  const { state: authState } = useAuth();
  const canWrite =
    authState.status === "authenticated" && authState.capabilities.includes("configuration.activate");

  const [loadState, setLoadState] = useState<LoadState>({ phase: "loading" });
  const [status, setStatus] = useState<ConnectionStatusResponse | null>(null);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>({ phase: "idle" });
  const [testState, setTestState] = useState<TestState>({ phase: "idle" });

  useEffect(() => {
    let cancelled = false;

    async function load(): Promise<void> {
      try {
        const [settings, statusResponse] = await Promise.all([
          getDiscordSettings(),
          getProviderStatus("discord"),
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
      const settings = await saveDiscordSettings({ webhook_url: webhookUrl, enabled });
      setLoadState({ phase: "ready", settings });
      setWebhookUrl("");
      setSaveState({ phase: "idle" });
    } catch (error) {
      setSaveState({ phase: "error", message: describeError(error) });
    }
  }

  async function handleTestConnection(): Promise<void> {
    setTestState({ phase: "testing" });
    try {
      const result = await testDiscordConnection();
      setStatus(result);
      setTestState({ phase: "idle" });
    } catch (error) {
      setTestState({ phase: "error", message: describeError(error) });
    }
  }

  return (
    <section className="settings-card" aria-labelledby="discord-settings-heading">
      <div className="settings-card__header">
        <h3 id="discord-settings-heading">Discord</h3>
        {status && <ConnectionStatusBadge status={status.status} />}
      </div>
      <p className="settings-card__description">
        Notification channel via webhook. Testing validates the webhook without posting a
        message.
      </p>

      {loadState.phase === "loading" && <LoadingState label="Loading Discord settings…" />}
      {loadState.phase === "error" && <ErrorState message={loadState.message} />}

      {loadState.phase === "ready" && (
        <>
          <dl className="settings-card__current">
            <dt>Webhook</dt>
            <dd>{loadState.settings.webhook_configured ? "Configured" : "Not configured"}</dd>
            <dt>Source</dt>
            <dd>{loadState.settings.webhook_source}</dd>
          </dl>

          {canWrite ? (
            <form className="settings-card__form" onSubmit={(event) => void handleSave(event)}>
              <label htmlFor="discord-webhook-url">Webhook URL</label>
              <input
                id="discord-webhook-url"
                type="password"
                autoComplete="off"
                placeholder="Leave blank to keep the current value"
                value={webhookUrl}
                onChange={(event) => setWebhookUrl(event.target.value)}
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
