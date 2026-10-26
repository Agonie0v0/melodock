import { useRef } from "react";
import { Check, Monitor, Moon, Sun } from "lucide-react";

const themes = [
  ["system", "跟随系统", Monitor],
  ["light", "浅色", Sun],
  ["dark", "深色", Moon],
] as const;

export function ThemePicker({
  theme,
  change,
}: {
  theme: "system" | "light" | "dark";
  change: (theme: "system" | "light" | "dark") => void;
}) {
  const menu = useRef<HTMLDivElement>(null);
  const Icon = themes.find(([value]) => value === theme)![2];
  return (
    <>
      <button
        className="icon-button theme-toggle"
        aria-label="切换主题"
        title="切换主题"
        popoverTarget="theme-picker"
      >
        <Icon aria-hidden="true" />
      </button>
      <div ref={menu} id="theme-picker" popover="auto" className="theme-picker">
        <div role="group" aria-label="界面主题">
          {themes.map(([value, label, OptionIcon]) => (
            <button
              key={value}
              aria-pressed={theme === value}
              onClick={() => {
                change(value);
                menu.current?.hidePopover();
              }}
            >
              <OptionIcon aria-hidden="true" />
              <span>{label}</span>
              {theme === value && <Check aria-hidden="true" />}
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
