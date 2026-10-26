import { useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Download,
  Folder,
  ListMusic,
  Music2,
  Search,
  Settings,
  ScrollText,
  WandSparkles,
  X,
} from "lucide-react";

const items = [
  ["search", "搜索音乐", Search],
  ["player", "正在播放", Music2],
  ["playlists", "歌单", ListMusic],
  ["queue", "下载队列", Download],
  ["files", "音乐库", Folder],
  ["organize", "刮削整理", WandSparkles],
  ["logs", "运行日志", ScrollText],
  ["settings", "设置", Settings],
] as const;
export type NavigationView = (typeof items)[number][0];
const defaults = items.map(([id]) => id);

export function Navigation({
  active,
  change,
  downloads,
}: {
  active: string;
  change: (view: NavigationView) => void;
  downloads: number;
}) {
  const [order, setOrder] = useState<NavigationView[]>(() => {
    try {
      const saved: unknown = JSON.parse(
        localStorage.getItem("melokeep-navigation") || "null",
      );
      if (Array.isArray(saved))
        return [...new Set([...saved, ...defaults])].filter(
          (id): id is NavigationView => defaults.includes(id),
        );
    } catch {
      /* Local preferences are optional. */
    }
    return defaults;
  });
  const dragged = useRef<NavigationView | null>(null);
  function save(next: NavigationView[]) {
    setOrder(next);
    try {
      localStorage.setItem("melokeep-navigation", JSON.stringify(next));
    } catch {
      /* Storage may be unavailable. */
    }
  }
  function move(id: NavigationView, target: NavigationView) {
    if (id === target) return;
    const next = order.filter((value) => value !== id);
    next.splice(order.indexOf(target), 0, id);
    save(next);
  }
  return (
    <div className="navigation-group">
      <nav aria-label="主导航">
        {order.map((id, index) => {
          const [, label, Icon] = items.find(([value]) => value === id)!;
          return (
            <button
              key={id}
              className={`nav-item ${active === id ? "active" : ""}`}
              aria-current={active === id ? "page" : undefined}
              draggable
              title={`${label}；拖动可调整顺序，或按 Alt + 左右方向键移动`}
              onDragStart={(event) => {
                dragged.current = id;
                event.dataTransfer.setData("text/plain", id);
                event.dataTransfer.effectAllowed = "move";
              }}
              onDragOver={(event) => {
                if (dragged.current) event.preventDefault();
              }}
              onDrop={(event) => {
                event.preventDefault();
                if (dragged.current) move(dragged.current, id);
                dragged.current = null;
              }}
              onDragEnd={() => {
                dragged.current = null;
              }}
              onKeyDown={(event) => {
                if (
                  !event.altKey ||
                  !["ArrowLeft", "ArrowRight"].includes(event.key)
                )
                  return;
                event.preventDefault();
                const target = index + (event.key === "ArrowLeft" ? -1 : 1);
                if (target >= 0 && target < order.length)
                  move(id, order[target]);
              }}
              onClick={() => change(id)}
            >
              <Icon />
              {label}
              {id === "queue" && downloads > 0 && (
                <span className="nav-count">{downloads}</span>
              )}
            </button>
          );
        })}
      </nav>
      <div id="navigation-order" popover="auto" className="navigation-order">
        <div className="navigation-order-heading">
          <strong>导航顺序</strong>
          <button
            className="icon-button"
            aria-label="关闭导航排序"
            popoverTarget="navigation-order"
            popoverTargetAction="hide"
          >
            <X />
          </button>
        </div>
        <p>拖动导航栏目，或使用下方按钮调整。顺序自动保存在当前浏览器。</p>
        <ol>
          {order.map((id, index) => {
            const [, label, Icon] = items.find(([value]) => value === id)!;
            return (
              <li key={id}>
                <Icon />
                <span>{label}</span>
                <button
                  className="icon-button"
                  aria-label={`前移${label}`}
                  disabled={index === 0}
                  onClick={() => move(id, order[index - 1])}
                >
                  <ArrowUp />
                </button>
                <button
                  className="icon-button"
                  aria-label={`后移${label}`}
                  disabled={index === order.length - 1}
                  onClick={() => move(id, order[index + 1])}
                >
                  <ArrowDown />
                </button>
              </li>
            );
          })}
        </ol>
        <button className="secondary" onClick={() => save(defaults)}>
          恢复默认顺序
        </button>
      </div>
    </div>
  );
}
