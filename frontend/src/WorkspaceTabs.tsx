import type { LucideIcon } from "lucide-react";

export function WorkspaceTabs({
  id,
  label,
  tabs,
  active,
  change,
}: {
  id: string;
  label: string;
  tabs: readonly (readonly [string, string, LucideIcon])[];
  active: string;
  change: (tab: string) => void;
}) {
  return (
    <div
      className="library-tabs"
      role="tablist"
      aria-label={label}
      onKeyDown={(event) => {
        const index = tabs.findIndex(([key]) => key === active);
        const next =
          event.key === "ArrowRight"
            ? (index + 1) % tabs.length
            : event.key === "ArrowLeft"
              ? (index + tabs.length - 1) % tabs.length
              : event.key === "Home"
                ? 0
                : event.key === "End"
                  ? tabs.length - 1
                  : -1;
        if (next < 0) return;
        event.preventDefault();
        change(tabs[next][0]);
        document.getElementById(`${id}-tab-${tabs[next][0]}`)?.focus();
      }}
    >
      {tabs.map(([key, title, Icon]) => (
        <button
          key={key}
          role="tab"
          tabIndex={active === key ? 0 : -1}
          aria-selected={active === key}
          aria-controls={`${id}-panel-${key}`}
          id={`${id}-tab-${key}`}
          onClick={() => change(key)}
        >
          <Icon />
          {title}
        </button>
      ))}
    </div>
  );
}
