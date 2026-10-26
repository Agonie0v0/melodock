import { useEffect, useState } from "react";
import { ArrowRight, WandSparkles } from "lucide-react";
import { api } from "./api";
import type { LibraryConfig } from "./types";

export function LibraryWorkbench({
  count,
  busy,
  start,
  rules,
}: {
  count: number;
  busy: boolean;
  start: (
    action: "scrape" | "organize" | "both",
    options: Record<string, unknown>,
  ) => void;
  rules: () => void;
}) {
  const [config, setConfig] = useState<LibraryConfig | null>(null);
  const [error, setError] = useState("");
  const [action, setAction] = useState<"scrape" | "organize" | "both">("both");
  const [directoryMode, setDirectoryMode] = useState(false);
  const [directory, setDirectory] = useState("incoming");
  const load = () =>
    api<LibraryConfig>("/library/settings")
      .then(setConfig)
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
  }, []);
  return (
    <section className="view library-workbench" aria-label="刮削整理工作台">
      <div className="library-heading">
        <div>
          <h2>处理音乐文件</h2>
          <p>
            选择文件、查找资料，再审核标签和归档路径。确认应用后才会修改文件。
          </p>
        </div>
        <button className="secondary" onClick={rules}>
          前往规则设置 <ArrowRight />
        </button>
      </div>
      {!config && (
        <p role={error ? "alert" : "status"}>
          {error || "正在读取刮削规则…"}{" "}
          {error && (
            <button
              className="secondary"
              onClick={() => {
                setError("");
                void load();
              }}
            >
              重新加载
            </button>
          )}
        </p>
      )}
      {config && (
        <>
          <div className="workbench-options">
            <label>
              处理范围
              <select
                value={directoryMode ? "directory" : "selection"}
                aria-label="处理范围"
                disabled={busy}
                onChange={(e) =>
                  setDirectoryMode(e.target.value === "directory")
                }
              >
                <option value="selection">下方选中的歌曲</option>
                <option value="directory">目录内全部歌曲（含子目录）</option>
              </select>
            </label>
            {directoryMode && (
              <label>
                目录路径
                <input
                  value={directory}
                  aria-label="目录路径"
                  onChange={(e) => setDirectory(e.target.value)}
                  placeholder="相对音乐根目录，例如 incoming"
                />
                <small>单次最多 1000 首；留空选择整个音乐根目录。</small>
              </label>
            )}
            <label>
              本次处理
              <select
                aria-label="本次处理"
                value={action}
                disabled={busy}
                onChange={(e) => setAction(e.target.value as typeof action)}
              >
                <option value="both">刮削资料并整理目录</option>
                <option value="scrape">只刮削标签、歌词与封面</option>
                <option value="organize">只按现有标签整理目录</option>
              </select>
            </label>
          </div>
          <div className="workbench-rule-summary" aria-label="当前处理规则">
            <p>使用已保存的默认规则</p>
            {action !== "organize" && (
              <p>
                资料来源：
                {config.sources
                  .map(
                    (id) =>
                      config.metadata_sources?.find(
                        (source) => source.id === id,
                      )?.label || id,
                  )
                  .join("、") || "未选择"}{" "}
                · {config.overwrite ? "覆盖未锁定标签" : "仅补全空值"}
              </p>
            )}
            {action !== "scrape" && (
              <p className="library-path">
                目标目录：{config.library_dir} / {config.folder_template} /{" "}
                {config.filename_template}
              </p>
            )}
          </div>
          <div className="management-toolbar workbench-submit">
            <span aria-live="polite">
              {directoryMode
                ? `目录：${directory || "音乐根目录"}`
                : `已选 ${count} 首歌曲`}
            </span>
            <button
              className="primary"
              disabled={
                busy ||
                (!count && !directoryMode) ||
                (action !== "organize" && !config.sources.length)
              }
              onClick={() =>
                start(action, {
                  ...(directoryMode ? { scope_dir: directory } : {}),
                })
              }
            >
              <WandSparkles />
              {busy ? "正在创建预览…" : "生成修改预览"}
            </button>
            {!count && !directoryMode && (
              <small>先在下方选择需要处理的歌曲</small>
            )}
            {action !== "organize" && !config.sources.length && (
              <small role="status">请选择至少一个刮削来源</small>
            )}
          </div>
          <p className="setting-help">
            资料来源、覆盖规则、歌词封面和归档模板统一在“设置 →
            刮削与归档”中配置。
          </p>
        </>
      )}
    </section>
  );
}
