// frontend/src/features/configuration/UniversePanel.tsx
//
// Checkpoint 9: read-only universe view. Shows instrument members' domain
// identity + status (never a broker token - the API never returns one).
import { useState } from "react";

import { listUniverseVersions } from "../../common/api/configApi";
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

export function UniversePanel(): JSX.Element {
  const [universeId, setUniverseId] = useState("example");
  const [inputValue, setInputValue] = useState("example");
  const { state } = useConfigQuery(listUniverseVersions, universeId);

  return (
    <section aria-labelledby="universe-panel-heading">
      <h2 id="universe-panel-heading">Universe</h2>
      <form
        className="lookup-form"
        onSubmit={(event) => {
          event.preventDefault();
          setUniverseId(inputValue.trim());
        }}
      >
        <label htmlFor="universe-id">Universe ID</label>
        <input
          id="universe-id"
          type="text"
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
        />
        <button type="submit">Load</button>
      </form>

      {state.status === "loading" && <LoadingState label="Loading universe versions…" />}
      {state.status === "error" && <ErrorState message={state.message} />}
      {state.status === "success" && state.data.length === 0 && (
        <EmptyState message={`No universe versions found for "${universeId}".`} />
      )}
      {state.status === "success" && state.data.length > 0 && (
        <ul className="version-list">
          {state.data.map((record) => (
            <li key={record.version} className="version-card">
              <div className="version-card__header">
                <h3>
                  {record.universe_id} — {record.version}
                </h3>
                <ActiveBadge isActive={record.is_active} />
              </div>
              <dl>
                <dt>Exchange</dt>
                <dd>{record.exchange}</dd>
                <dt>Created</dt>
                <dd>{formatDateTime(record.created_at)}</dd>
                <dt>Member count</dt>
                <dd>{record.members.length}</dd>
              </dl>
              {record.members.length > 0 && (
                <table className="member-table">
                  <caption className="sr-only">Universe members</caption>
                  <thead>
                    <tr>
                      <th scope="col">Instrument ID</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {record.members.map((member) => (
                      <tr key={member.instrument_id}>
                        <td>{member.instrument_id}</td>
                        <td>{member.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
