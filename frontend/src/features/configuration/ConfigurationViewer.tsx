// frontend/src/features/configuration/ConfigurationViewer.tsx
//
// Checkpoint 9: tab container for the read-only Configuration Viewer.
// Implements the WAI-ARIA tabs pattern (role="tablist"/"tab"/"tabpanel",
// arrow-key navigation) so the screen is keyboard-accessible, not just
// mouse-clickable.
import { useState } from "react";

import { RiskConfigurationPanel } from "./RiskConfigurationPanel";
import { StrategyVersionPanel } from "./StrategyVersionPanel";
import { UniversePanel } from "./UniversePanel";

type TabId = "risk" | "universe" | "strategy";

const TABS: { id: TabId; label: string }[] = [
  { id: "risk", label: "Risk Configuration" },
  { id: "universe", label: "Universe" },
  { id: "strategy", label: "Strategy Version" },
];

export function ConfigurationViewer(): JSX.Element {
  const [activeTab, setActiveTab] = useState<TabId>("risk");

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>): void {
    const index = TABS.findIndex((tab) => tab.id === activeTab);
    if (event.key === "ArrowRight") {
      setActiveTab(TABS[(index + 1) % TABS.length].id);
    } else if (event.key === "ArrowLeft") {
      setActiveTab(TABS[(index - 1 + TABS.length) % TABS.length].id);
    }
  }

  return (
    <div className="configuration-viewer">
      <h1>Configuration Viewer</h1>
      <p className="configuration-viewer__subtitle">
        Read-only view of persisted risk, universe, and strategy configuration versions.
      </p>

      <div role="tablist" aria-label="Configuration sections" onKeyDown={handleKeyDown}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={activeTab === tab.id}
            aria-controls={`tabpanel-${tab.id}`}
            tabIndex={activeTab === tab.id ? 0 : -1}
            className={activeTab === tab.id ? "tab tab--active" : "tab"}
            onClick={() => setActiveTab(tab.id)}
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        id={`tabpanel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
        className="tabpanel"
      >
        {activeTab === "risk" && <RiskConfigurationPanel />}
        {activeTab === "universe" && <UniversePanel />}
        {activeTab === "strategy" && <StrategyVersionPanel />}
      </div>
    </div>
  );
}
