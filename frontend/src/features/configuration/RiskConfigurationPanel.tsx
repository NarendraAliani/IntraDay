// frontend/src/features/configuration/RiskConfigurationPanel.tsx
//
// Checkpoint 9: read-only risk-configuration view. Displays every persisted
// version for the given configuration id, with active/historical
// distinguished via ActiveBadge (backed by the API's own `is_active`).
import { useState } from "react";

import { listRiskConfigurationVersions } from "../../common/api/configApi";
import { ActiveBadge } from "../../common/components/ActiveBadge";
import { EmptyState } from "../../common/components/EmptyState";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import { useConfigQuery } from "../../common/useConfigQuery";

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

export function RiskConfigurationPanel(): JSX.Element {
  const [configurationId, setConfigurationId] = useState("default");
  const [inputValue, setInputValue] = useState("default");
  const state = useConfigQuery(listRiskConfigurationVersions, configurationId);

  return (
    <section aria-labelledby="risk-panel-heading">
      <h2 id="risk-panel-heading">Risk Configuration</h2>
      <form
        className="lookup-form"
        onSubmit={(event) => {
          event.preventDefault();
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
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
