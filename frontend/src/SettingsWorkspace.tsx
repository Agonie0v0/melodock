import type { ComponentProps } from "react";
import { Bell, Download, Library, Sun, WandSparkles } from "lucide-react";
import { EngineSettings } from "./EngineSettings";
import { LibrarySettings } from "./LibrarySettings";
import { BotSettings } from "./BotSettings";
import { WorkspaceTabs } from "./WorkspaceTabs";

const tabs = [
  ["engine", "音源与下载", Download],
  ["library", "刮削与归档", WandSparkles],
  ["navidrome", "Navidrome 连接", Library],
  ["bots", "通知与机器人", Bell],
  ["appearance", "外观", Sun],
] as const;
export type SettingsTab = (typeof tabs)[number][0];

export function SettingsWorkspace({
  tab,
  setTab,
  theme,
  setTheme,
  ...engine
}: ComponentProps<typeof EngineSettings> & {
  tab: SettingsTab;
  setTab: (tab: SettingsTab) => void;
  theme: "system" | "light" | "dark";
  setTheme: (theme: "system" | "light" | "dark") => void;
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
        {tab === "appearance" && (
          <div className="engine-settings">
            <section className="settings-section">
              <h2>界面外观</h2>
              <p>主题偏好自动保存在当前浏览器中。</p>
              <label>
                界面主题
                <select
                  aria-label="界面主题"
                  value={theme}
                  onChange={(event) =>
                    setTheme(event.target.value as typeof theme)
                  }
                >
                  <option value="system">跟随系统</option>
                  <option value="light">浅色</option>
                  <option value="dark">深色</option>
                </select>
              </label>
            </section>
          </div>
        )}
      </section>
    </>
  );
}
