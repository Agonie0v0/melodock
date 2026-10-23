import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  History,
  RefreshCw,
  RotateCcw,
  X,
} from "lucide-react";
import { api } from "./api";
import { processingLabels, tagLabels } from "./LibrarySettings";
import type { LibraryJob } from "./types";

const active = new Set([
  "queued",
  "identifying",
  "tagging",
  "organizing",
  "indexing",
  "restoring",
]);
const actionNames: Record<string, string> = {
  scrape: "刮削标签",
  organize: "整理目录",
  both: "刮削并整理",
  edit: "编辑标签",
  extract: "文件名提取",
  clean: "清理标签",
  duplicates: "重复文件检查",
};

export function LibraryJobs({
  focus,
  changed,
}: {
  focus: string;
  changed: () => void;
}) {
  const [jobs, setJobs] = useState<LibraryJob[]>([]);
  const [selected, setSelected] = useState(focus);
  const [detail, setDetail] = useState<LibraryJob | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const previousStatus = useRef("");
  useEffect(() => {
    if (focus) setSelected(focus);
  }, [focus]);
  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    async function load() {
      try {
        const result = await api<{ jobs: LibraryJob[]; has_more: boolean }>(
          `/library/jobs?offset=${offset}&size=30`,
        );
        if (stopped) return;
        setJobs(result.jobs);
        setHasMore(result.has_more);
        if (selected) {
          const value = await api<LibraryJob>(`/library/jobs/${selected}`);
          if (stopped) return;
          if (
            previousStatus.current !== `${value.id}:${value.status}` &&
            ["complete", "partial", "needs_review", "restored"].includes(
              value.status,
            )
          )
            changed();
          previousStatus.current = `${value.id}:${value.status}`;
          setDetail(value);
          if (active.has(value.status))
            timer = window.setTimeout(() => void load(), 1600);
        } else if (result.jobs.some((job) => active.has(job.status)))
          timer = window.setTimeout(() => void load(), 2000);
      } catch (e) {
        if (!stopped) setError((e as Error).message);
      } finally {
        if (!stopped) setLoading(false);
      }
    }
    setLoading(true);
    setError("");
    void load();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [selected, offset, refresh]);
  async function action(name: string) {
    if (!detail) return;
    setBusy(name);
    setError("");
    try {
      const result = await api<LibraryJob>(
        `/library/jobs/${detail.id}/${name}`,
        "POST",
        name === "apply" ? {} : undefined,
      );
      if (name === "retry") setSelected(result.id);
      setRefresh((value) => value + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function choose(item: string, candidate: string) {
    if (!detail || !candidate) return;
    setBusy("preview");
    setError("");
    try {
      setDetail(
        await api<LibraryJob>(`/library/jobs/${detail.id}/preview`, "POST", {
          choices: { [item]: candidate },
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  return (
    <section className="view library-jobs">
      <div className="library-heading">
        <div>
          <h2>刮削与整理任务</h2>
          <p>先检查标签和路径，再应用修改。处理历史可恢复原文件。</p>
        </div>
        <button
          className="secondary"
          disabled={loading || !!busy}
          onClick={() => setRefresh((value) => value + 1)}
        >
          <RefreshCw />
          刷新任务
        </button>
      </div>
      {error && (
        <p role="alert" className="library-error">
          {error}
        </p>
      )}
      {selected && (
        <button
          className="playlist-back"
          onClick={() => {
            setSelected("");
            setDetail(null);
          }}
        >
          <ArrowLeft />
          全部任务
        </button>
      )}
      {loading && !detail && <p role="status">正在读取整理任务…</p>}
      {selected && detail ? (
        <>
          <div className="processing-heading">
            <div>
              <h3>{actionNames[detail.action] || detail.action}</h3>
              <p>{detail.detail}</p>
              <small>
                {new Date(detail.created_at * 1000).toLocaleString("zh-CN")} ·{" "}
                {detail.total} 首
              </small>
            </div>
            <span
              className={`processing-status is-${detail.status}`}
              role="status"
            >
              {processingLabels[detail.status] || detail.status}
            </span>
          </div>
          <div className="management-toolbar">
            {["ready", "needs_review", "partial"].includes(detail.status) &&
              detail.action !== "duplicates" && (
                <button
                  className="primary"
                  disabled={
                    !!busy ||
                    !detail.items?.some((item) => item.status === "ready")
                  }
                  onClick={() => void action("apply")}
                >
                  <Check />
                  {busy === "apply" ? "正在提交…" : "应用已确认的更改"}
                </button>
              )}
            {["failed", "partial", "paused"].includes(detail.status) && (
              <button
                className="secondary"
                disabled={!!busy}
                onClick={() => void action("retry")}
              >
                <RefreshCw />
                重新检查未完成文件
              </button>
            )}
            {active.has(detail.status) && detail.status !== "restoring" && (
              <button
                className="secondary"
                disabled={!!busy}
                onClick={() => void action("cancel")}
              >
                <X />
                取消后续处理
              </button>
            )}
            {!active.has(detail.status) &&
              detail.items?.some(
                (item) => item.operation_id && item.status === "complete",
              ) && (
                <details className="restore-confirm">
                  <summary>
                    <RotateCcw />
                    恢复原文件
                  </summary>
                  <p>
                    恢复本次修改前的音频标签、文件名和目录。整理后被再次修改的文件会保留，需手动检查。
                  </p>
                  <button
                    className="secondary"
                    disabled={!!busy}
                    onClick={() => void action("restore")}
                  >
                    确认恢复本次修改
                  </button>
                </details>
              )}
          </div>
          {detail.warnings?.map((warning, index) => (
            <p key={index} className="library-warning" role="status">
              {warning}
            </p>
          ))}
          {detail.status === "needs_review" && (
            <p className="library-warning">
              有歌曲无法自动确定版本。请选定候选，或选择保留现有标签；已确认的歌曲可以先应用。
            </p>
          )}
          {detail.duplicates && (
            <div className="duplicate-groups">
              {detail.duplicates.length ? (
                detail.duplicates.map((group, index) => (
                  <div className="processing-item" key={index}>
                    <h4>相同文件组 {index + 1}</h4>
                    <ul>
                      {group.map((item) => (
                        <li key={item.id}>
                          <strong>{item.name}</strong>
                          <p className="library-path">{item.path}</p>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))
              ) : (
                <p className="empty">
                  未发现内容完全相同的文件。标签不同的同一首歌可能不会被此检查识别。
                </p>
              )}
            </div>
          )}
          {detail.action !== "duplicates" && (
            <div className="processing-items">
              {detail.items?.map((item) => {
                const changes = Object.entries(item.after).filter(
                  ([key, value]) => value !== item.before[key],
                );
                return (
                  <details
                    key={item.id}
                    className="processing-item"
                    open={
                      item.status === "needs_review" ||
                      item.status === "failed" ||
                      detail.total === 1
                    }
                  >
                    <summary>
                      <span>
                        <strong>{item.name}</strong>
                        <small>
                          {item.after.artist ||
                            item.before.artist ||
                            "未知歌手"}{" "}
                          ·{" "}
                          {item.after.album || item.before.album || "未知专辑"}
                        </small>
                      </span>
                      <span className={`processing-status is-${item.status}`}>
                        {processingLabels[item.status] || item.status}
                      </span>
                    </summary>
                    <div className="processing-item-body">
                      {!!item.candidates.length && (
                        <label className="candidate-select">
                          匹配结果
                          <select
                            value={item.chosen || ""}
                            disabled={
                              !!busy ||
                              active.has(detail.status) ||
                              ["complete", "restored", "skipped"].includes(
                                item.status,
                              )
                            }
                            onChange={(e) =>
                              void choose(item.id, e.target.value)
                            }
                          >
                            <option value="">请选择歌曲版本</option>
                            <option value="existing">保留现有标签</option>
                            {item.candidates.map((candidate) => (
                              <option value={candidate.id} key={candidate.id}>
                                {candidate.source === "qq"
                                  ? "QQ音乐"
                                  : candidate.source === "netease"
                                    ? "网易云"
                                    : candidate.source}
                                ：{candidate.title} / {candidate.artist} /{" "}
                                {candidate.album || "未知专辑"}
                                {candidate.conflicts.length
                                  ? `（${candidate.conflicts.join("、")}）`
                                  : ""}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                      {!item.candidates.length &&
                        item.status === "needs_review" && (
                          <button
                            className="secondary"
                            disabled={!!busy}
                            onClick={() => void choose(item.id, "existing")}
                          >
                            保留现有标签并继续
                          </button>
                        )}
                      {item.chosen && item.chosen !== "existing" && (
                        <p className="setting-help">
                          {item.candidates
                            .find((c) => c.id === item.chosen)
                            ?.reasons.join("、")}
                          。匹配依据仅用于辅助判断歌曲版本。
                        </p>
                      )}
                      {changes.length ? (
                        <div className="music-table-wrap">
                          <table className="tag-diff">
                            <thead>
                              <tr>
                                <th>标签</th>
                                <th>修改前</th>
                                <th>修改后</th>
                              </tr>
                            </thead>
                            <tbody>
                              {changes.map(([key, value]) => (
                                <tr key={key}>
                                  <th>{tagLabels[key] || key}</th>
                                  <td>{item.before[key] || "空"}</td>
                                  <td>{value || "清空"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <p className="setting-help">
                          文字标签无变化。歌词与封面将按任务规则补全。
                        </p>
                      )}
                      <div className="processing-paths">
                        <div>
                          <small>原文件</small>
                          <p className="library-path">{item.original_path}</p>
                        </div>
                        <div>
                          <small>整理后</small>
                          <p className="library-path">{item.target}</p>
                        </div>
                      </div>
                      {item.locks.length > 0 && (
                        <p className="setting-help">
                          手动锁定：
                          {item.locks
                            .map((key) => tagLabels[key] || key)
                            .join("、")}
                          ，自动刮削会保留这些字段。
                        </p>
                      )}
                      {item.warnings.map((warning, index) => (
                        <p key={index} className="library-warning">
                          {warning}
                        </p>
                      ))}
                      {item.error && (
                        <p role="alert" className="library-error">
                          {item.error}
                        </p>
                      )}
                      <a
                        className="secondary"
                        href={`/api/files/content?path=${encodeURIComponent(item.path)}`}
                        download
                      >
                        下载当前文件
                      </a>
                    </div>
                  </details>
                );
              })}
            </div>
          )}
        </>
      ) : (
        !loading && (
          <>
            {jobs.length ? (
              <div className="processing-list">
                {jobs.map((job) => (
                  <button
                    className="processing-list-row"
                    key={job.id}
                    onClick={() => {
                      setDetail(null);
                      setSelected(job.id);
                    }}
                  >
                    <History />
                    <span>
                      <strong>{actionNames[job.action] || job.action}</strong>
                      <small>{job.detail}</small>
                      <small>
                        {new Date(job.created_at * 1000).toLocaleString(
                          "zh-CN",
                        )}{" "}
                        · {job.total} 首
                      </small>
                    </span>
                    <span className={`processing-status is-${job.status}`}>
                      {processingLabels[job.status] || job.status}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="library-empty">
                <History />
                <h3>还没有整理任务</h3>
                <p>
                  在本地音乐库选择歌曲后开始刮削或整理，也可在设置中开启下载后自动处理。
                </p>
              </div>
            )}
            {(offset > 0 || hasMore) && (
              <div className="library-pagination">
                <button
                  className="secondary"
                  disabled={!offset}
                  onClick={() => setOffset(Math.max(0, offset - 30))}
                >
                  上一页
                </button>
                <span>第 {Math.floor(offset / 30) + 1} 页</span>
                <button
                  className="secondary"
                  disabled={!hasMore}
                  onClick={() => setOffset(offset + 30)}
                >
                  下一页
                </button>
              </div>
            )}
          </>
        )
      )}
    </section>
  );
}
