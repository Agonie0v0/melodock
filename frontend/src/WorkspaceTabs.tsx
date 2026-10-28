import type { LucideIcon } from "lucide-react";
import { useEffect, useRef } from "react";

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
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const reveal = () => {
      const tab = element.querySelector<HTMLElement>('[aria-selected="true"]');
      if (!tab) return;
      const box = tab.getBoundingClientRect(),
        bounds = element.getBoundingClientRect();
      if (box.left < bounds.left || box.right > bounds.right)
        element.scrollLeft +=
          box.left - bounds.left - (bounds.width - box.width) / 2;
    };
    reveal();
    const observer = new ResizeObserver(reveal);
    observer.observe(element);
    return () => observer.disconnect();
  }, [active]);
  return (
    <div
      ref={container}
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
