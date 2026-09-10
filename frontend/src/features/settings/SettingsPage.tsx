// frontend/src/features/settings/SettingsPage.tsx
//
// Checkpoint 22: Settings screen container - Dhan/Telegram/Discord cards
// stacked vertically (not tabbed like ConfigurationViewer, since a
// reader wants to see all three connectivity statuses at a glance, not
// hunt through tabs for which provider is misconfigured).
import { DhanSettingsCard } from "./DhanSettingsCard";
import { DiscordSettingsCard } from "./DiscordSettingsCard";
import { HistoricalMarketDataCard } from "./HistoricalMarketDataCard";
import { TelegramSettingsCard } from "./TelegramSettingsCard";

export function SettingsPage(): JSX.Element {
  return (
    <div className="settings-page">
      <h1>Settings</h1>
      <p className="configuration-viewer__subtitle">
        Configure broker connectivity and notification channels. Credentials are stored encrypted
        and are never shown in full once saved.
      </p>
      <div className="settings-page__cards">
        {/* CHECKPOINT-FRONTEND-6: the three connection-status cards are
            genuinely independent (each its own provider, its own form,
            no shared state) and similarly shaped - grouped in a
            responsive grid per FRONTEND_DESIGN_SYSTEM.md's own density
            rule. `HistoricalMarketDataCard` stays full-width below,
            deliberately excluded - it is a different KIND of content
            (a multi-instrument/timeframe fetch tool, not a peer
            "connection status" card) and needs its own full row. */}
        <div className="page-summary-grid">
          <DhanSettingsCard />
          <TelegramSettingsCard />
          <DiscordSettingsCard />
        </div>
        <HistoricalMarketDataCard />
      </div>
    </div>
  );
}
