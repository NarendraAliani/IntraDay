// frontend/src/features/settings/SettingsPage.tsx
//
// Checkpoint 22: Settings screen container - Dhan/Telegram/Discord cards
// stacked vertically (not tabbed like ConfigurationViewer, since a
// reader wants to see all three connectivity statuses at a glance, not
// hunt through tabs for which provider is misconfigured).
import { DhanSettingsCard } from "./DhanSettingsCard";
import { DiscordSettingsCard } from "./DiscordSettingsCard";
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
        <DhanSettingsCard />
        <TelegramSettingsCard />
        <DiscordSettingsCard />
      </div>
    </div>
  );
}
