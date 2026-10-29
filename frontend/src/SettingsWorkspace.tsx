import type { ComponentProps } from "react";
import {
  Bell,
  Download,
  Library,
  WandSparkles,
  MessageSquare,
} from "lucide-react";
import { AISettings } from "./AISettings";
import { EngineSettings } from "./EngineSettings";
import { LibrarySettings } from "./LibrarySettings";
import { BotSettings } from "./BotSettings";
import { WorkspaceTabs } from "./WorkspaceTabs";

const tabs = [
  ["engine", "音源与下载", Download],
  ["library", "刮削与归档", WandSparkles],
  ["navidrome", "Navidrome 连接", Library],
  ["bots", "通知与机器人", Bell],
  ["ai", "AI 助手", MessageSquare],
] as const;
export type SettingsTab = (typeof tabs)[number][0];

export function SettingsWorkspace({
  tab,
  setTab,
  ...engine
}: ComponentProps<typeof EngineSettings> & {
  tab: SettingsTab;
  setTab: (tab: SettingsTab) => void;
}) {
  return (
    <>
      <WorkspaceTabs
        id="settings"
        label="设置分类"
        tabs={tabs}
        active={tab}
        change={(value) => setTab(value as SettingsTab)}
      />
      <section
        className="view"
        role="tabpanel"
        id={`settings-panel-${tab}`}
        aria-labelledby={`settings-tab-${tab}`}
      >
        {tab === "engine" && <EngineSettings {...engine} />}
        {(tab === "library" || tab === "navidrome") && (
          <LibrarySettings
            key={tab}
            section={tab}
            openSources={() => setTab("engine")}
          />
        )}
        {tab === "bots" && <BotSettings />}
        {tab === "ai" && <AISettings />}
      </section>
    </>
  );
}
