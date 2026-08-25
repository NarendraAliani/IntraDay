// frontend/src/features/dashboard/DashboardPage.tsx
//
// Checkpoint 64.80-F: the main Application Dashboard - the answer to
// "what is the current state of my trading application?" in one screen.
//
// HONESTY RULES THIS FILE ENFORCES (Phases 2, 8, 9, 21):
//  * Every number/state shown either comes from a REAL, already-existing
//    backend endpoint, or is rendered as an explicit "Not Available" /
//    "Not Configured" card. There is no mock data in this file.
//  * Market state comes from ONE selector (`describeMarketSession`) fed
//    by ONE API (`/api/v1/config/market-data/session/`) - never
//    recomputed from the browser clock.
//  * The Archive and Reconciliation cards are honestly UNAVAILABLE:
//    Checkpoint 64.73 shipped a `market_data_archive` MANAGEMENT COMMAND,
//    and management commands are not HTTP APIs. No archive/reconciliation
//    schema exists in `shared/generated_contracts/api-types.ts`. That is a
//    genuine backend gap, documented as a blocker - NOT filled in by
//    adding backend code from a frontend checkpoint.
//  * Research Readiness is rendered as a STATIC, explicitly-labelled
//    "not backed by a live API" section showing NOT READY. No endpoint
//    exposes the research-readiness gate (the strategy-engine
//    `research-status` endpoint is a per-strategy RESEARCH_ACTIVE/PAUSED/
//    DISABLED flag - a different concept, deliberately not reused here).
//  * Gainz is DISABLED and carries NO control of any kind.
//  * There is NO live-trading control anywhere on this page.
import { useCallback, useEffect, useState } from "react";
import type { JSX } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import {
  getMarketDataHealth,
  getMarketSession,
  getWorkerRuntimeStatus,
} from "../../common/api/marketDataApi";
import type {
  MarketDataHealthResponse,
  SessionResponse,
  WorkerRuntimeStatusResponse,
} from "../../common/api/marketDataApi";
import { getSystemReadiness } from "../../common/api/systemApi";
import type { SystemReadinessResponse } from "../../common/api/systemApi";
import { CapabilityStatus } from "../../common/components/CapabilityStatus";
import { Icon } from "../../common/icons/Icon";
import { EmptyState } from "../../common/components/EmptyState";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import { StatusBadge } from "./StatusBadge";
// Checkpoint 64.80-F3: the Decision Pipeline is a SHARED component in
// features/correlation - the dashboard hosts it, it does not own it.
import { DecisionPipeline } from "../correlation/DecisionPipeline";
import type { PipelineDestination } from "../correlation/correlationModel";
import {
  describeMarketSession,
  describeProviderHealth,
  describeSystemReadiness,
  describeWorkerState,
  formatAgeSeconds,
  formatTimestamp,
  normalizeWorkerState,
} from "./dashboardModel";

/** Phase 13: every API-backed section has all four states. */
type LoadPhase = "loading" | "ready" | "error";

interface DashboardData {
  session: SessionResponse | null;
  health: MarketDataHealthResponse | null;
  worker: WorkerRuntimeStatusResponse | null;
  readiness: SystemReadinessResponse | null;
}

const EMPTY_DATA: DashboardData = { session: null, health: null, worker: null, readiness: null };

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred while loading the dashboard.";
}

/** Each panel resolves independently: one failing endpoint must never
 * blank out the whole dashboard, and a failed panel is reported as
 * "Not Available" rather than as a fabricated healthy state. */
async function settle<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch {
    return null;
  }
}

export interface DashboardPageProps {
  /** Navigation callbacks into the EXISTING screens (Phases 6, 7, 10).
   * The dashboard never re-implements those pages. */
  onOpenMarketData: () => void;
  onOpenArchive: () => void;
  onOpenPaperTrading: () => void;
  onOpenBacktesting: () => void;
  /** Checkpoint 64.80-F3 Phase 7: the Decision Pipeline's drill-down.
   * Optional so every existing caller and test keeps working - when it
   * is absent the pipeline renders as a read-only diagram rather than
   * offering navigation controls that would go nowhere. */
  onNavigate?: (destination: PipelineDestination) => void;
}

export function DashboardPage({
  onOpenMarketData,
  onOpenArchive,
  onOpenPaperTrading,
  onOpenBacktesting,
  onNavigate,
}: DashboardPageProps): JSX.Element {
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [data, setData] = useState<DashboardData>(EMPTY_DATA);

  const load = useCallback(async () => {
    setPhase("loading");
    try {
      const [session, health, worker, readiness] = await Promise.all([
        settle(getMarketSession),
        settle(getMarketDataHealth),
        settle(getWorkerRuntimeStatus),
        settle(getSystemReadiness),
      ]);
      // Only a total failure of every panel is a page-level error -
      // anything else renders with per-card "Not Available" states.
      if (!session && !health && !worker && !readiness) {
        setErrorMessage(
          "None of the status APIs could be reached. Check that the IntraDay backend is running.",
        );
        setPhase("error");
        return;
      }
      setData({ session, health, worker, readiness });
      setPhase("ready");
    } catch (error) {
      setErrorMessage(describeError(error));
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (phase === "loading") {
    return (
      <section className="dashboard" aria-labelledby="dashboard-heading">
        <h1 id="dashboard-heading">Application Dashboard</h1>
        <LoadingState label="Loading application status…" />
      </section>
    );
  }

  if (phase === "error") {
    return (
      <section className="dashboard" aria-labelledby="dashboard-heading">
        <h1 id="dashboard-heading">Application Dashboard</h1>
        <ErrorState message={errorMessage} />
        <button type="button" className="dashboard__action" onClick={() => void load()}>
          Retry loading application status
        </button>
      </section>
    );
  }

  const { session, health, worker, readiness } = data;
  const market = describeMarketSession(session);
  const provider = describeProviderHealth(health);
  const workerStatus = describeWorkerState(worker);
  const systemStatus = describeSystemReadiness(readiness);
  const workerState = normalizeWorkerState(worker?.worker_state);

  return (
    <section className="dashboard" aria-labelledby="dashboard-heading">
      <header className="dashboard__header">
        <h1 id="dashboard-heading">Application Dashboard</h1>
        <p className="dashboard__subtitle">
          Read-only status overview. This screen contains no live-trading control.
        </p>
        <button type="button" className="dashboard__action" onClick={() => void load()}>
          <Icon name="refresh" />
          Refresh application status
        </button>
      </header>

      {/* --- PHASE 3: highly visible market status ------------------- */}
      {/* 64.80-F2 Phase 6: this hero is the dashboard's strongest visual
          anchor - the analytical grid, the signal rule and the orbital
          rings live here and nowhere else. */}
      <section className="dashboard__market" aria-labelledby="market-status-heading">
        <p className="dashboard__eyebrow">
          <Icon name="signal" />
          Session signal
        </p>
        <h2 id="market-status-heading">Market Status</h2>
        <p className="dashboard__market-value" data-tone={market.tone}>
          <StatusBadge status={market} />
        </p>
        <p className="dashboard__market-detail">{market.detail}</p>
        {session ? (
          <dl className="dashboard__facts">
            <div>
              <dt>Trading date</dt>
              <dd>{session.session_date}</dd>
            </div>
            <div>
              <dt>Exchange</dt>
              <dd>{session.exchange}</dd>
            </div>
            <div>
              <dt>Market open</dt>
              <dd>{formatTimestamp(session.market_open)}</dd>
            </div>
            <div>
              <dt>Market close</dt>
              <dd>{formatTimestamp(session.market_close)}</dd>
            </div>
            <div>
              <dt>Square-off deadline</dt>
              <dd>{formatTimestamp(session.square_off_deadline)}</dd>
            </div>
          </dl>
        ) : (
          <EmptyState message="The session API returned no trading-session details for today." />
        )}
      </section>

      {/* 64.80-F2 Phase 9: the eight cards are grouped into three
          labelled regions so the page reads as ONE product with a
          hierarchy, rather than eight unrelated status tiles. The group
          label is a <p> referenced by `aria-labelledby` rather than a
          heading, so the existing h1/h2 heading structure - which the
          64.80-F accessibility tests assert - is left exactly as it was. */}
      <section className="dashboard__group" aria-labelledby="group-system-heading">
        <p className="dashboard__section-title" id="group-system-heading">
          <Icon name="system-health" />
          System &amp; Data Health
        </p>
        <div className="dashboard__grid">
          {/* --- PHASE 4: system / data status ------------------------- */}
          <article className="dashboard__card" aria-labelledby="provider-card-heading">
          <div className="dashboard__card-header">
            <h2 id="provider-card-heading">
              <Icon name="market" />
              Data Provider
            </h2>
            <StatusBadge status={provider} />
          </div>
          {health ? (
            <dl className="dashboard__facts">
              <div>
                <dt>Last successful read</dt>
                <dd>{formatTimestamp(health.last_success_at)}</dd>
              </div>
              <div>
                <dt>Data freshness</dt>
                <dd>{formatAgeSeconds(health.freshness_age_seconds)}</dd>
              </div>
              <div>
                <dt>Reconnect count</dt>
                <dd>{health.reconnect_count}</dd>
              </div>
              <div>
                <dt>Consecutive failures</dt>
                <dd>{health.consecutive_failures}</dd>
              </div>
              <div>
                <dt>Subscription active</dt>
                <dd>{health.subscription_active ? "Yes" : "No"}</dd>
              </div>
            </dl>
          ) : (
            <EmptyState message="Provider health is not available from the backend right now." />
          )}
        </article>

        <article className="dashboard__card" aria-labelledby="worker-card-heading">
          <div className="dashboard__card-header">
            <h2 id="worker-card-heading">
              <Icon name="signal" />
              Worker Status
            </h2>
            <StatusBadge status={workerStatus} />
          </div>
          <p className="dashboard__card-detail">{workerStatus.detail}</p>
          {worker ? (
            <dl className="dashboard__facts">
              <div>
                <dt>Provider</dt>
                <dd>{worker.provider || "Not configured"}</dd>
              </div>
              <div>
                <dt>Worker state</dt>
                <dd>{workerState}</dd>
              </div>
              <div>
                <dt>Watchdog state</dt>
                <dd>{worker.watchdog_state || "Not available"}</dd>
              </div>
              <div>
                <dt>Last packet</dt>
                <dd>{formatTimestamp(worker.last_packet_at)}</dd>
              </div>
              <div>
                <dt>Last bar</dt>
                <dd>{formatTimestamp(worker.last_bar_at)}</dd>
              </div>
              <div>
                <dt>Reconnect count</dt>
                <dd>{worker.reconnect_count}</dd>
              </div>
              <div>
                <dt>Subscribed instruments</dt>
                <dd>{worker.subscribed_instrument_count}</dd>
              </div>
            </dl>
          ) : (
            <EmptyState message="The worker runtime status API could not be read." />
          )}
        </article>

        <article className="dashboard__card" aria-labelledby="system-card-heading">
          <div className="dashboard__card-header">
            <h2 id="system-card-heading">
              <Icon name="security" />
              System Readiness
            </h2>
            <StatusBadge status={systemStatus} />
          </div>
          {readiness ? (
            <>
              <dl className="dashboard__facts">
                <div>
                  <dt>Database</dt>
                  <dd>{readiness.database_ok ? "Reachable" : "Not reachable"}</dd>
                </div>
                <div>
                  <dt>Kill switch</dt>
                  <dd>{readiness.kill_switch_engaged ? "ENGAGED" : "Not engaged"}</dd>
                </div>
                <div>
                  <dt>Unresolved square-offs</dt>
                  <dd>{readiness.square_off_unresolved_count}</dd>
                </div>
              </dl>
              {readiness.reasons.length > 0 ? (
                <ul className="dashboard__reasons">
                  {readiness.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              ) : (
                <EmptyState message="The backend reports no outstanding readiness reasons." />
              )}
            </>
          ) : (
            <EmptyState message="The composed system-readiness API could not be read." />
          )}
        </article>
        </div>
      </section>

      <section className="dashboard__group" aria-labelledby="group-data-heading">
        <p className="dashboard__section-title" id="group-data-heading">
          <Icon name="archive" />
          Market Data &amp; Archive
        </p>
        <div className="dashboard__grid">
        {/* --- PHASE 5: today's market data ------------------------- */}
        <article className="dashboard__card" aria-labelledby="market-data-card-heading">
          <div className="dashboard__card-header">
            <h2 id="market-data-card-heading">
              <Icon name="market" />
              Today&apos;s Market Data
            </h2>
            <StatusBadge
              status={
                workerState === "RUNNING"
                  ? { label: "INGESTING", tone: "HEALTHY", detail: "" }
                  : { label: "NO INGESTION", tone: "INACTIVE", detail: "" }
              }
            />
          </div>
          <dl className="dashboard__facts">
            <div>
              <dt>Trading date</dt>
              <dd>{session ? session.session_date : "Not available"}</dd>
            </div>
            <div>
              <dt>Subscribed symbols</dt>
              <dd>{worker ? worker.subscribed_instrument_count : "Not available"}</dd>
            </div>
            <div>
              <dt>Last bar observed</dt>
              <dd>{worker ? formatTimestamp(worker.last_bar_at) : "Not available"}</dd>
            </div>
            <div>
              <dt>Expected / actual / missing bars</dt>
              <dd>Not available — no archive HTTP API</dd>
            </div>
            <div>
              <dt>Duplicate bars</dt>
              <dd>Not available — no archive HTTP API</dd>
            </div>
          </dl>
          <button type="button" className="dashboard__action" onClick={onOpenMarketData}>
            <Icon name="market" />
            View Market Data
          </button>
        </article>

        {/* --- PHASE 5/6: archive + reconciliation (honest gap) ------ */}
        <article className="dashboard__card" aria-labelledby="archive-card-heading">
          <div className="dashboard__card-header">
            <h2 id="archive-card-heading">
              <Icon name="archive" />
              Archive &amp; Reconciliation
            </h2>
            <StatusBadge
              status={{ label: "NOT AVAILABLE", tone: "UNAVAILABLE", detail: "" }}
            />
          </div>
          <CapabilityStatus
            title="Daily market-data archive status"
            description="Archive completeness (expected/actual/missing/duplicate bars) and reconciliation status are produced by the market_data_archive management command. No HTTP endpoint exposes them yet, so this dashboard cannot show real archive figures."
            status="BLOCKED"
            blocker="No archive or reconciliation HTTP API exists in the generated OpenAPI contract. A backend endpoint is required; adding one is out of scope for this frontend-only checkpoint."
            prerequisite="Backend: expose archive + reconciliation status as a read-only API."
          />
          <button type="button" className="dashboard__action" onClick={onOpenArchive}>
            <Icon name="archive" />
            View Archive
          </button>
        </article>
        </div>
      </section>

      <section className="dashboard__group" aria-labelledby="group-research-heading">
        <p className="dashboard__section-title" id="group-research-heading">
          <Icon name="research" />
          Simulation &amp; Research
        </p>
        <div className="dashboard__grid">
        {/* --- PHASE 7: paper trading entry point -------------------- */}
        {/* 64.80-F2 Phase 9: emphasised with the EXISTING paper hue as a
            left rule. No new colour, and emphasis never implies live. */}
        <article
          className="dashboard__card dashboard__card--paper"
          aria-labelledby="paper-card-heading"
        >
          <div className="dashboard__card-header">
            <h2 id="paper-card-heading">
              <Icon name="paper-trading" />
              Paper Trading
            </h2>
            <span className="badge badge--paper">
              <Icon name="paper-trading" /> PAPER TRADING — NOT LIVE TRADING
            </span>
          </div>
          <p className="dashboard__card-detail">
            Simulated execution only. No order placed from this application reaches a real
            exchange, and no live-trading control exists on this dashboard.
          </p>
          <button type="button" className="dashboard__action" onClick={onOpenPaperTrading}>
            <Icon name="paper-trading" />
            Open Paper Trading
          </button>
        </article>

        {/* --- PHASE 8: research readiness --------------------------- */}
        <article className="dashboard__card" aria-labelledby="research-card-heading">
          <div className="dashboard__card-header">
            <h2 id="research-card-heading">
              <Icon name="research" />
              Research Readiness
            </h2>
            <StatusBadge status={{ label: "NOT READY", tone: "BLOCKED", detail: "" }} />
          </div>
          <p className="dashboard__card-detail">
            Research readiness is <strong>NO</strong>. The criteria below are the project&apos;s
            recorded milestone gates. They are shown as a static, documented checklist — no
            backend endpoint currently publishes research readiness, so these are deliberately not
            presented as live data.
          </p>
          <ul className="dashboard__reasons">
            <li>Full NSE session validation — Pending</li>
            <li>Independent candle authority — Pending</li>
            <li>Reconciliation evidence — Pending</li>
          </ul>
          <button type="button" className="dashboard__action" onClick={onOpenBacktesting}>
            <Icon name="research" />
            Open Research &amp; Backtesting
          </button>
        </article>

        {/* --- PHASE 9: gainz (no controls, ever) -------------------- */}
        {/* 64.80-F2: a dashed border marks future scope. It is a
            presentation change only - Gainz remains DISABLED and still
            carries no control of any kind. */}
        <article
          className="dashboard__card dashboard__card--future"
          aria-labelledby="gainz-card-heading"
        >
          <div className="dashboard__card-header">
            <h2 id="gainz-card-heading">
              <Icon name="gainz" />
              Gainz
            </h2>
            <StatusBadge status={{ label: "DISABLED", tone: "INACTIVE", detail: "" }} />
          </div>
          <CapabilityStatus
            title="Gainz feature set"
            description="Gainz is DISABLED and not active. It is future scope and is shown here for visibility only — this dashboard intentionally provides no control to enable, configure, or run it."
            status="PLANNED"
            prerequisite="Research readiness must be achieved first."
          />
        </article>
        </div>
      </section>

      {/* --- 64.80-F3 Phase 4: the Decision Pipeline ----------------- */}
      {/* Placed last deliberately: the status cards above answer "what
          is happening right now", and this answers "how does this
          platform get from data to a decision, and which of those links
          are actually wired". It claims nothing the API does not
          expose. */}
      <DecisionPipeline onNavigate={onNavigate} />
    </section>
  );
}
