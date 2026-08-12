// frontend/src/features/configuration/StrategyVersionPanel.tsx
//
// Checkpoint 9: read-only strategy-version view. Identity is the
// (specification_version, code_version, configuration_version) 3-tuple,
// matching the domain model - never re-derived or renumbered by the
// frontend.
import { useState } from "react";

import { listStrategyVersions } from "../../common/api/configApi";
import { ActiveBadge } from "../../common/components/ActiveBadge";
import { EmptyState } from "../../common/components/EmptyState";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import { useConfigQuery } from "../../common/useConfigQuery";

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("en-IN");
}

export function StrategyVersionPanel(): JSX.Element {
  const [strategyId, setStrategyId] = useState("example-strategy");
  const [inputValue, setInputValue] = useState("example-strategy");
  const state = useConfigQuery(listStrategyVersions, strategyId);

  return (
    <section aria-labelledby="strategy-panel-heading">
      <h2 id="strategy-panel-heading">Strategy Version</h2>
      <form
        className="lookup-form"
        onSubmit={(event) => {
          event.preventDefault();
          setStrategyId(inputValue.trim());
        }}
      >
        <label htmlFor="strategy-id">Strategy ID</label>
        <input
          id="strategy-id"
          type="text"
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
        />
        <button type="submit">Load</button>
      </form>

      {state.status === "loading" && <LoadingState label="Loading strategy versions…" />}
      {state.status === "error" && <ErrorState message={state.message} />}
      {state.status === "success" && state.data.length === 0 && (
        <EmptyState message={`No strategy versions found for "${strategyId}".`} />
      )}
      {state.status === "success" && state.data.length > 0 && (
        <ul className="version-list">
          {state.data.map((record) => (
            <li
              key={`${record.specification_version}-${record.code_version}-${record.configuration_version}`}
              className="version-card"
            >
              <div className="version-card__header">
                <h3>{record.strategy_id}</h3>
                <ActiveBadge isActive={record.is_active} />
              </div>
              <dl>
                <dt>Specification version</dt>
                <dd>{record.specification_version}</dd>
                <dt>Code version</dt>
                <dd>{record.code_version}</dd>
                <dt>Configuration version</dt>
                <dd>{record.configuration_version}</dd>
                <dt>Universe version</dt>
                <dd>{record.universe_version}</dd>
                <dt>Timeframe</dt>
                <dd>{record.timeframe}</dd>
                <dt>Maturity state</dt>
                <dd>{record.maturity_state}</dd>
                <dt>Created</dt>
                <dd>{formatDateTime(record.created_at)}</dd>
              </dl>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
