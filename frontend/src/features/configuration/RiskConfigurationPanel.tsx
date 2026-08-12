// frontend/src/features/configuration/RiskConfigurationPanel.tsx
//
// Checkpoint 9: read-only risk-configuration view. Displays every persisted
// version for the given configuration id, with active/historical
// distinguished via ActiveBadge (backed by the API's own `is_active`).
//
// Checkpoint 10: adds the first state-changing human workflow - activating
// a historical version. The backend remains authoritative: this component
// never mutates `is_active` locally on success, it re-fetches the real
// version list from the API (`refetch()`) and lets the fresh response
// determine what's shown as active.
import { useState } from "react";

import { activateRiskConfigurationVersion, listRiskConfigurationVersions } from "../../common/api/configApi";
import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { ActiveBadge } from "../../common/components/ActiveBadge";
import { ConfirmDialog } from "../../common/components/ConfirmDialog";
import { EmptyState } from "../../common/components/EmptyState";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import { useConfigQuery } from "../../common/useConfigQuery";
import type { RiskConfigurationResponse } from "../../common/api/configApi";

function formatAmount(value: string): string {
  const numeric = Number(value);
  if (Number.isNaN(numeric)) {
    return value;
  }
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(numeric);
}

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("en-IN");
}

function describeApiError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

type ActivationState =
  | { phase: "idle" }
  | { phase: "confirming"; target: RiskConfigurationResponse }
  | { phase: "submitting"; target: RiskConfigurationResponse }
  | { phase: "error"; target: RiskConfigurationResponse; message: string }
  | { phase: "success"; version: string };

export function RiskConfigurationPanel(): JSX.Element {
  const [configurationId, setConfigurationId] = useState("default");
  const [inputValue, setInputValue] = useState("default");
  const { state, refetch } = useConfigQuery(listRiskConfigurationVersions, configurationId);
  const [activation, setActivation] = useState<ActivationState>({ phase: "idle" });

  const activeRecord =
    state.status === "success" ? state.data.find((record) => record.is_active) : undefined;

  function requestActivation(target: RiskConfigurationResponse): void {
    setActivation({ phase: "confirming", target });
  }

  function cancelActivation(): void {
    setActivation({ phase: "idle" });
  }

  async function confirmActivation(): Promise<void> {
    if (activation.phase !== "confirming" && activation.phase !== "error") {
      return;
    }
    const target = activation.target;
    setActivation({ phase: "submitting", target });
    try {
      await activateRiskConfigurationVersion(target.risk_configuration_id, target.version);
      // Backend is authoritative: re-pull real state rather than assuming
      // the POST's own response body is still current by the time this
      // renders (e.g. a concurrent activation by someone else).
      await refetch();
      setActivation({ phase: "success", version: target.version });
    } catch (error) {
      setActivation({ phase: "error", target, message: describeApiError(error) });
    }
  }

  return (
    <section aria-labelledby="risk-panel-heading">
      <h2 id="risk-panel-heading">Risk Configuration</h2>
      <form
        className="lookup-form"
        onSubmit={(event) => {
          event.preventDefault();
          setActivation({ phase: "idle" });
          setConfigurationId(inputValue.trim());
        }}
      >
        <label htmlFor="risk-configuration-id">Configuration ID</label>
        <input
          id="risk-configuration-id"
          type="text"
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
        />
        <button type="submit">Load</button>
      </form>

      {activation.phase === "success" && (
        <p role="status" className="state state--success">
          Version {activation.version} is now the active risk configuration.
        </p>
      )}

      {state.status === "loading" && <LoadingState label="Loading risk configuration versions…" />}
      {state.status === "error" && <ErrorState message={state.message} />}
      {state.status === "success" && state.data.length === 0 && (
        <EmptyState message={`No risk configuration versions found for "${configurationId}".`} />
      )}
      {state.status === "success" && state.data.length > 0 && (
        <ul className="version-list">
          {state.data.map((record) => (
            <li key={record.version} className="version-card">
              <div className="version-card__header">
                <h3>
                  {record.risk_configuration_id} — {record.version}
                </h3>
                <ActiveBadge isActive={record.is_active} />
              </div>
              <dl>
                <dt>Created</dt>
                <dd>{formatDateTime(record.created_at)}</dd>
                <dt>Max intraday loss</dt>
                <dd>{formatAmount(record.limits.max_intraday_loss)}</dd>
                <dt>Max position size</dt>
                <dd>{formatAmount(record.limits.max_position_size)}</dd>
                <dt>Max per-trade risk</dt>
                <dd>{formatAmount(record.limits.max_per_trade_risk)}</dd>
              </dl>
              {!record.is_active && (
                <button
                  type="button"
                  className="activate-button"
                  onClick={() => requestActivation(record)}
                >
                  Activate Version {record.version}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {(activation.phase === "confirming" ||
        activation.phase === "submitting" ||
        activation.phase === "error") && (
        <ConfirmDialog
          titleId="activate-risk-configuration-dialog-title"
          title={`Activate Risk Configuration — Version ${activation.target.version}`}
          confirmLabel={`Confirm Activation of Version ${activation.target.version}`}
          status={
            activation.phase === "error"
              ? "error"
              : activation.phase === "submitting"
                ? "submitting"
                : "idle"
          }
          errorMessage={activation.phase === "error" ? activation.message : undefined}
          onConfirm={() => void confirmActivation()}
          onCancel={cancelActivation}
        >
          <p>
            <strong>Current active version:</strong>{" "}
            {activeRecord ? activeRecord.version : "none"}
          </p>
          <p>
            <strong>New active version:</strong> {activation.target.version}
          </p>
          <ul>
            <li>Max intraday loss: {formatAmount(activation.target.limits.max_intraday_loss)}</li>
            <li>Max position size: {formatAmount(activation.target.limits.max_position_size)}</li>
            <li>Max per-trade risk: {formatAmount(activation.target.limits.max_per_trade_risk)}</li>
          </ul>
          <p>
            This will make Version {activation.target.version} the active risk configuration for{" "}
            <strong>{activation.target.risk_configuration_id}</strong>. Version{" "}
            {activeRecord?.version ?? "the current active version"} will become historical.
          </p>
        </ConfirmDialog>
      )}
    </section>
  );
}
