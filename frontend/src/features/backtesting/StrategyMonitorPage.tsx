// frontend/src/features/backtesting/StrategyMonitorPage.tsx
//
// Checkpoint 27 Part 20: a safe research strategy-monitor view.
// Pause/Resume controls RESEARCH_ACTIVE/RESEARCH_PAUSED/DISABLED
// status only - they do NOT control live trading (no such capability
// exists anywhere in this codebase yet).
import { useEffect, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { useAuth } from "../../common/auth/AuthContext";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import { listResearchStatuses, setResearchStatus } from "../../common/api/backtestingApi";
import type { ResearchStatusResponse } from "../../common/api/backtestingApi";
import { Icon } from "../../common/icons/Icon";

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

export function StrategyMonitorPage(): JSX.Element {
  const { state: authState } = useAuth();
  const canControl =
    authState.status === "authenticated" &&
    authState.capabilities.includes("configuration.activate");

  const [statuses, setStatuses] = useState<ResearchStatusResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload(): Promise<void> {
    try {
      setStatuses(await listResearchStatuses());
    } catch (err) {
      setError(describeError(err));
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  async function toggle(strategyId: string, current: string): Promise<void> {
    const next = current === "RESEARCH_ACTIVE" ? "RESEARCH_PAUSED" : "RESEARCH_ACTIVE";
    try {
      await setResearchStatus(strategyId, next);
      await reload();
    } catch (err) {
      setError(describeError(err));
    }
  }

  if (error) return <ErrorState message={error} />;
  if (!statuses) return <LoadingState label="Loading strategy monitor…" />;

  return (
    <div className="strategy-monitor-page">
      <h1>Strategy Monitor</h1>
      <p className="configuration-viewer__subtitle">
        Research-only pause/resume state per strategy. This does NOT control live trading - no
        live-trading capability exists in this application yet.
      </p>
      <table>
        <thead>
          <tr>
            <th>Strategy</th>
            <th>Status</th>
            {canControl && <th>Action</th>}
          </tr>
        </thead>
        <tbody>
          {statuses.map((row) => (
            <tr key={row.strategy_id}>
              <td>{row.strategy_id}</td>
              <td>
                <span
                  className={
                    row.status === "RESEARCH_ACTIVE"
                      ? "badge badge--ok"
                      : row.status === "RESEARCH_PAUSED"
                        ? "badge badge--pending"
                        : "badge badge--danger"
                  }
                >
                  <Icon
                    name={
                      row.status === "RESEARCH_ACTIVE"
                        ? "success"
                        : row.status === "RESEARCH_PAUSED"
                          ? "warning"
                          : "error"
                    }
                  />{" "}
                  {row.status}
                </span>
              </td>
              {canControl && (
                <td>
                  {row.status !== "DISABLED" && (
                    <button type="button" onClick={() => void toggle(row.strategy_id, row.status)}>
                      {row.status === "RESEARCH_ACTIVE" ? "Pause Research" : "Resume Research"}
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
