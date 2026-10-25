import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  History,
  RefreshCw,
  RotateCcw,
  X,
  Download,
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
  rename: "批量重命名",
  export_lyrics: "导出歌词",
  import_lyrics: "嵌入歌词",
  export_cover: "导出专辑封面",
  import_cover: "嵌入专辑封面",
  clear: "清空内嵌标签",
  convert: "格式转换",
  split: "CUE 分轨",
  quality: "音频完整性与参数检查",
  artist_artwork: "刮削艺术家图片",
};
const sourceNames: Record<string, string> = {
  netease: "网易云",
  qq: "QQ音乐",
  migu: "咪咕音乐",
  kugou: "酷狗音乐",
  kuwo: "酷我音乐",
  musicbrainz: "MusicBrainz",
  acoustid: "AcoustID",
};
type Version = {
  job_id: string;
  created_at: number;
  action: string;
  status: string;
  restorable: boolean;
  before: Record<string, string>;
  after: Record<string, string>;
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
  const [filter, setFilter] = useState("all");
  const [queries, setQueries] = useState<Record<string, string>>({});
  const [versions, setVersions] = useState<Record<string, Version[]>>({});
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
          `/library/jobs?offset=${offset}&size=30&status=${filter}`,
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
  }, [selected, offset, refresh, filter]);
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
  const visibleJobs = jobs.filter(
    (job) =>
      filter === "all" ||
      (filter === "active"
        ? active.has(job.status)
        : filter === "failed"
          ? ["failed", "partial", "paused"].includes(job.status)
          : job.status === filter),
  );
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
            <a
              className="secondary"
              href={`/api/library/jobs/${detail.id}/report`}
              download
            >
              <Download />
              导出处理报告
            </a>
            {["ready", "needs_review", "partial"].includes(detail.status) &&
              !["duplicates", "quality"].includes(detail.action) && (
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
          {detail.settings && (
            <p className="setting-help processing-rules">
              本次来源：
              {detail.settings.sources
                .map((id) => sourceNames[id] || id)
                .join("、") || "无"}{" "}
              · {detail.settings.overwrite ? "覆盖未锁定标签" : "只补缺失标签"}{" "}
              · 手动锁定字段保留
            </p>
          )}
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
                  本次检查未发现重复候选。不同检查方式的判断范围不同，可切换方式进一步检查。
                </p>
              )}
            </div>
          )}
          {detail.action !== "duplicates" && (
            <div className="processing-items">
              {detail.items?.map((item) => {
                const chosenCandidate = item.candidates.find(
                  (c) => c.id === item.chosen,
                );
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
                      {["scrape", "both"].includes(detail.action) &&
                        ["ready", "needs_review", "failed"].includes(
                          item.status,
                        ) &&
                        !active.has(detail.status) && (
                          <form
                            className="candidate-search"
                            onSubmit={async (e) => {
                              e.preventDefault();
                              setBusy("search");
                              setError("");
                              try {
                                setDetail(
                                  await api<LibraryJob>(
                                    `/library/jobs/${detail.id}/search`,
                                    "POST",
                                    {
                                      item: item.id,
                                      query:
                                        queries[item.id] ||
                                        `${item.before.title} ${item.before.artist}`.trim(),
                                    },
                                  ),
                                );
                              } catch (e) {
                                setError((e as Error).message);
                              } finally {
                                setBusy("");
                              }
                            }}
                          >
                            <label>
                              搜索歌曲资料
                              <input
                                maxLength={200}
                                required
                                value={
                                  queries[item.id] ??
                                  `${item.before.title} ${item.before.artist}`.trim()
                                }
                                onChange={(e) =>
                                  setQueries({
                                    ...queries,
                                    [item.id]: e.target.value,
                                  })
                                }
                                placeholder="歌名 歌手"
                              />
                            </label>
                            <button className="secondary" disabled={!!busy}>
                              重新搜索候选
                            </button>
                          </form>
                        )}
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
                                {` · ${candidate.score} 分`}
                                {candidate.date ? ` · ${candidate.date}` : ""}
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
                          匹配分数{" "}
                          {
                            item.candidates.find((c) => c.id === item.chosen)
                              ?.score
                          }{" "}
                          ·{" "}
                          {item.candidates
                            .find((c) => c.id === item.chosen)
                            ?.reasons.join("、")}
                          。分数用于辅助审核，不代表识别正确率；发行日期、曲序等以所选发行版本为准。
                        </p>
                      )}
                      {chosenCandidate?.field_sources && (
                        <p className="setting-help">
                          补充资料来源：
                          {Object.entries(chosenCandidate.field_sources)
                            .map(
                              ([field, source]) =>
                                `${tagLabels[field] || { lyrics: "歌词", cover_url: "封面" }[field] || field}（${{ netease: "网易云", qq: "QQ音乐", musicbrainz: "MusicBrainz" }[source] || source}）`,
                            )
                            .join("、")}
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
                      {item.artwork && (
                        <p className="setting-help">
                          艺术家：{item.artwork.artist} · 来源：
                          {item.artwork.source}
                        </p>
                      )}
                      {item.quality && (
                        <div className="library-checks">
                          {Object.entries(item.quality).map(([key, value]) => (
                            <span key={key}>
                              {(
                                {
                                  duration: "时长（秒）",
                                  bitrate: "码率（bps）",
                                  sample_rate: "采样率（Hz）",
                                  channels: "声道",
                                  bits_per_sample: "位深",
                                } as Record<string, string>
                              )[key] || key}
                              ：{value ?? "未知"}
                            </span>
                          ))}
                          <span>完整解码通过</span>
                        </div>
                      )}
                      {item.outputs && (
                        <div>
                          <h4>输出文件（原件保留）</h4>
                          {item.outputs.map((output) => (
                            <p className="library-path" key={output.path}>
                              {output.path}
                              {output.start != null
                                ? ` · ${output.start.toFixed(2)}s – ${output.end?.toFixed(2)}s`
                                : ""}
                            </p>
                          ))}
                        </div>
                      )}
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
                      <button
                        className="secondary"
                        disabled={!!busy}
                        onClick={async () => {
                          setBusy("versions");
                          setError("");
                          try {
                            const result = await api<{ versions: Version[] }>(
                              `/library/versions?path=${encodeURIComponent(item.path)}`,
                            );
                            setVersions({
                              ...versions,
                              [item.id]: result.versions,
                            });
                          } catch (e) {
                            setError((e as Error).message);
                          } finally {
                            setBusy("");
                          }
                        }}
                      >
                        查看此曲标签版本
                      </button>
                      {versions[item.id] && (
                        <div className="processing-versions">
                          {versions[item.id].length ? (
                            versions[item.id].map((version) => (
                              <details key={version.job_id}>
                                <summary>
                                  {new Date(
                                    version.created_at * 1000,
                                  ).toLocaleString("zh-CN")}{" "}
                                  ·{" "}
                                  {actionNames[version.action] ||
                                    version.action}{" "}
                                  ·{" "}
                                  {processingLabels[version.status] ||
                                    version.status}
                                </summary>
                                {Object.entries(version.after)
                                  .filter(
                                    ([key, value]) =>
                                      version.before[key] !== value,
                                  )
                                  .map(([key, value]) => (
                                    <p key={key}>
                                      {tagLabels[key] || key}：
                                      {version.before[key] || "空"} →{" "}
                                      {value || "空"}
                                    </p>
                                  ))}
                                {version.restorable && (
                                  <button
                                    className="secondary"
                                    disabled={!!busy}
                                    onClick={async () => {
                                      setBusy("restore");
                                      setError("");
                                      try {
                                        await api(
                                          `/library/jobs/${version.job_id}/restore`,
                                          "POST",
                                          { items: [item.id] },
                                        );
                                        setVersions({
                                          ...versions,
                                          [item.id]: [],
                                        });
                                        setSelected(version.job_id);
                                        setDetail(null);
                                        setRefresh((v) => v + 1);
                                      } catch (e) {
                                        setError((e as Error).message);
                                      } finally {
                                        setBusy("");
                                      }
                                    }}
                                  >
                                    恢复此曲到本次修改前
                                  </button>
                                )}
                              </details>
                            ))
                          ) : (
                            <p>暂无可显示的修改版本。</p>
                          )}
                        </div>
                      )}
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
            <div className="library-job-filters" aria-label="筛选整理任务">
              <span className="setting-help">筛选全部任务</span>
              {[
                ["all", "全部"],
                ["needs_review", "待确认"],
                ["ready", "待应用"],
                ["active", "处理中"],
                ["failed", "失败 / 部分完成"],
              ].map(([id, label]) => (
                <button
                  key={id}
                  className="secondary"
                  aria-pressed={filter === id}
                  onClick={() => {
                    setFilter(id);
                    setOffset(0);
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            {visibleJobs.length ? (
              <div className="processing-list">
                {visibleJobs.map((job) => (
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
                <h3>
                  {filter !== "all" ? "没有符合条件的任务" : "还没有整理任务"}
                </h3>
                <p>
                  在“选择与处理”中选择歌曲并生成预览，也可在“设置 →
                  刮削与归档”开启下载后自动处理。
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
