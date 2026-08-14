// frontend/src/features/paper-trading/PaperTradingPage.tsx
//
// Checkpoint 34 Part 15/16/17: the real "Paper Trading" operational
// surface. NOT a cosmetic dashboard - the kill switch section is wired
// to the real, tested backend (engage/reset actually work). Every
// capability this checkpoint's backend does NOT yet expose through a
// UI action (order submission, live position/order tables, P&L) uses
// the shared `CapabilityStatus` component - never bespoke "Coming
// Soon" markup (Part 16).
//
// Part 17's explicit requirement: PAPER MODE must never be visually
// confusable with LIVE. This entire page is captioned as simulated,
// and the one real backend capability wired here (the kill switch)
// already halts PAPER orders only - LIVE trading does not exist
// anywhere in this codebase to halt.
import { useCallback, useEffect, useState } from "react";

import {
  engageKillSwitch,
  getKillSwitchStatus,
  resetKillSwitch,
} from "../../common/api/killSwitchApi";
import type { KillSwitchStatusResponse } from "../../common/api/killSwitchApi";
import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { useAuth } from "../../common/auth/AuthContext";
import { CapabilityStatus } from "../../common/components/CapabilityStatus";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";

type LoadState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; killSwitch: KillSwitchStatusResponse };

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

export function PaperTradingPage(): JSX.Element {
  const { state: authState } = useAuth();
  const canOperate =
    authState.status === "authenticated" &&
    authState.capabilities.includes("configuration.activate");

  const [state, setState] = useState<LoadState>({ phase: "loading" });
  const [reason, setReason] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (): Promise<void> => {
    try {
      const killSwitch = await getKillSwitchStatus();
      setState({ phase: "ready", killSwitch });
    } catch (error) {
      setState({ phase: "error", message: describeError(error) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleEngage(): Promise<void> {
    setBusy(true);
    setActionError(null);
    try {
      await engageKillSwitch(reason);
      setReason("");
      await load();
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleReset(): Promise<void> {
    setBusy(true);
    setActionError(null);
    try {
      await resetKillSwitch();
      await load();
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="paper-trading-page">
      <h1>Paper Trading</h1>
      <div className="callout callout--warn" role="note">
        <strong>◐ PAPER MODE — simulated trading only.</strong> No fill shown anywhere on this
        page is a real broker execution. This platform has never placed a real order, and{" "}
        <strong>LIVE mode does not exist</strong> — there is no control anywhere in this
        application that enables it.
      </div>

      {state.phase === "loading" && <LoadingState label="Loading paper trading status…" />}
      {state.phase === "error" && <ErrorState message={state.message} />}

      {state.phase === "ready" && (
        <section className="capability-status-section" aria-labelledby="kill-switch-heading">
          <h2 id="kill-switch-heading">Kill Switch</h2>
          <p>
            Status:{" "}
            <span
              className={`badge ${state.killSwitch.status === "HALTED" ? "badge--danger" : "badge--active"}`}
            >
              {state.killSwitch.status === "HALTED" ? "✕ HALTED" : "● Active"}
            </span>
          </p>
          {state.killSwitch.status === "HALTED" && state.killSwitch.reason && (
            <p>
              <strong>Reason:</strong> {state.killSwitch.reason}
            </p>
          )}
          <p className="capability-status__description">
            While halted, the risk engine rejects every new paper order before it ever reaches
            the paper broker — proven by this checkpoint's own architecture-fitness tests, not
            only asserted here.
          </p>

          {canOperate ? (
            <>
              {state.killSwitch.status === "ACTIVE" ? (
                <div>
                  <label htmlFor="kill-switch-reason">Reason for halting</label>
                  <input
                    id="kill-switch-reason"
                    type="text"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder="e.g. unexpected repeated losses"
                  />
                  <button
                    type="button"
                    disabled={busy || reason.trim() === ""}
                    onClick={() => void handleEngage()}
                  >
                    {busy ? "Engaging…" : "Engage Kill Switch"}
                  </button>
                </div>
              ) : (
                <button type="button" disabled={busy} onClick={() => void handleReset()}>
                  {busy ? "Resetting…" : "Reset Kill Switch"}
                </button>
              )}
              {actionError && (
                <p role="alert" className="dialog__error">
                  {actionError}
                </p>
              )}
            </>
          ) : (
            <p className="settings-card__readonly-note">
              You have read-only access to this screen.
            </p>
          )}
        </section>
      )}

      <section className="capability-status-section" aria-labelledby="paper-lifecycle-heading">
        <h2 id="paper-lifecycle-heading">Paper Trading Lifecycle</h2>
        <div className="capability-status-grid">
          <CapabilityStatus
            title="Risk Gating"
            description="Every paper order is evaluated against max daily loss, max position size, max total exposure, max concurrent positions, duplicate-order, stale-data, session, and strategy-activation checks before it reaches the paper broker."
            status="AVAILABLE"
            documentationLink="docs/architecture/RISK_ENGINE_ARCHITECTURE.md"
          />
          <CapabilityStatus
            title="Order Execution Simulation"
            description="Market/limit/stop-loss/stop-loss-market order types, partial fills, slippage, and cost-model-based fees, all backend-tested."
            status="AVAILABLE"
            documentationLink="docs/architecture/PAPER_TRADING_ARCHITECTURE.md"
          />
          <CapabilityStatus
            title="Order Submission (UI)"
            description="Submitting a paper order from this screen — strategies, quantities, order types."
            status="NOT_YET_IMPLEMENTED"
            blocker="No frontend control exists yet to construct and submit an OrderIntent; the backend orchestration service is implemented and tested, but nothing in the UI calls it yet."
            prerequisite="A order-entry form + API endpoint wiring the existing PaperTradingService."
          />
          <CapabilityStatus
            title="Live Order / Position Monitor"
            description="Real-time view of pending orders, fills, and open positions."
            status="NOT_YET_IMPLEMENTED"
            blocker="No read API exists yet over the paper ledger tables."
          />
          <CapabilityStatus
            title="Reconciliation Report"
            description="Comparing local ledger state against the paper broker's own reported state."
            status="NOT_YET_IMPLEMENTED"
            blocker="The reconciliation engine exists and is tested, but no scheduled job or UI trigger runs it yet."
            documentationLink="docs/architecture/RISK_ENGINE_ARCHITECTURE.md"
          />
          <CapabilityStatus
            title="Live Trading"
            description="Real broker order placement."
            status="NOT_YET_IMPLEMENTED"
            blocker="This platform has never placed a real order, by design. LIVE mode does not exist anywhere in this codebase."
          />
        </div>
      </section>
    </div>
  );
}
