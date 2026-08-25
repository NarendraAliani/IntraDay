// frontend/src/features/market-data/MarketDataArchivePage.tsx
//
// Checkpoint 64.80-F Phase 6: the MINIMAL Market Data / Archive detail
// shell. No complex historical charting this checkpoint.
//
// This page is deliberately, visibly honest. Checkpoint 64.73 added a
// `market_data_archive` Django MANAGEMENT COMMAND. A management command
// is not an HTTP API: there is no archive view in
// `infrastructure/api/urls.py` and no archive/reconciliation schema in
// `shared/generated_contracts/api-types.ts`. Rather than fabricate
// expected/actual/missing bar counts, this page shows the real field
// skeleton the archive contract defines, every value explicitly marked
// "Not available", and names the missing backend endpoint as a blocker.
//
// The trading date IS real - it comes from the same single session API
// the dashboard uses (`getMarketSession`), never from the browser clock.
import { useCallback, useEffect, useState } from "react";
import type { JSX } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { getMarketSession } from "../../common/api/marketDataApi";
import type { SessionResponse } from "../../common/api/marketDataApi";
import { CapabilityStatus } from "../../common/components/CapabilityStatus";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import { StatusBadge } from "../dashboard/StatusBadge";
import { describeMarketSession } from "../dashboard/dashboardModel";

const NOT_AVAILABLE = "Not available — no archive HTTP API";

/** The real archive contract's field skeleton (domain/market_data/
 * archive.py), shown so the operator can see exactly what WILL be
 * reported once an endpoint exists - never populated with sample data. */
const ARCHIVE_FIELDS: ReadonlyArray<{ label: string }> = [
  { label: "Symbols" },
  { label: "Timeframe" },
  { label: "Expected bars" },
  { label: "Actual bars" },
  { label: "Missing bars" },
  { label: "Duplicate bars" },
  { label: "First observation" },
  { label: "Last observation" },
  { label: "Archive status" },
  { label: "Reconciliation status" },
];

type LoadPhase = "loading" | "ready" | "error";

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred while loading the archive overview.";
}

export function MarketDataArchivePage(): JSX.Element {
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [session, setSession] = useState<SessionResponse | null>(null);

  const load = useCallback(async () => {
    setPhase("loading");
    try {
      setSession(await getMarketSession());
      setPhase("ready");
    } catch (error) {
      setErrorMessage(describeError(error));
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="dashboard" aria-labelledby="archive-heading">
      <header className="dashboard__header">
        <h1 id="archive-heading">Market Data Archive</h1>
        <p className="dashboard__subtitle">
          Read-only daily archive overview. This screen writes no data.
        </p>
      </header>

      {phase === "loading" && <LoadingState label="Loading archive overview…" />}

      {phase === "error" && (
        <>
          <ErrorState message={errorMessage} />
          <button type="button" className="dashboard__action" onClick={() => void load()}>
            Retry loading archive overview
          </button>
        </>
      )}

      {phase === "ready" && (
        <>
          <section className="dashboard__market" aria-labelledby="archive-session-heading">
            <h2 id="archive-session-heading">Trading Session</h2>
            <p className="dashboard__market-value">
              <StatusBadge status={describeMarketSession(session)} />
            </p>
            <dl className="dashboard__facts">
              <div>
                <dt>Trading date</dt>
                <dd>{session ? session.session_date : "Not available"}</dd>
              </div>
              <div>
                <dt>Exchange</dt>
                <dd>{session ? session.exchange : "Not available"}</dd>
              </div>
            </dl>
          </section>

          <article className="dashboard__card" aria-labelledby="archive-detail-heading">
            <div className="dashboard__card-header">
              <h2 id="archive-detail-heading">Archive Completeness</h2>
              <StatusBadge
                status={{ label: "NOT AVAILABLE", tone: "UNAVAILABLE", detail: "" }}
              />
            </div>
            <div className="table-scroll">
              <table className="market-data-monitor__table">
                <caption className="sr-only">
                  Daily market-data archive fields and their current availability
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Field</th>
                    <th scope="col">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {ARCHIVE_FIELDS.map((field) => (
                    <tr key={field.label}>
                      <th scope="row">{field.label}</th>
                      <td>{NOT_AVAILABLE}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <CapabilityStatus
              title="Archive and reconciliation status API"
              description="Archive completeness and reconciliation results are currently produced only by the market_data_archive management command. No HTTP endpoint exposes them, so no real figures can be shown here."
              status="BLOCKED"
              blocker="No archive or reconciliation endpoint exists in the backend API contract. Adding one is backend work, out of scope for this frontend-only checkpoint."
              prerequisite="Backend: expose a read-only archive + reconciliation status endpoint."
            />
          </article>
        </>
      )}
    </section>
  );
}
