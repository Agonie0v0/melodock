import { useEffect, useRef, useState } from "react";
import {
  ImagePlus,
  MessageSquare,
  Plus,
  Send,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { api } from "./api";
import "./ai.css";

type Summary = { id: string; title: string; status: string };
type Event = {
  tool: string;
  status: string;
  detail: string;
  operation?: string;
  result?: unknown;
};
type ResultRow = {
  title?: string;
  name?: string;
  artist?: string;
  status?: string;
  detail?: string;
  track_count?: number;
  track?: { title?: string; artist?: string };
};
function ExecutionResult({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return null;
  const envelope = value as Record<string, unknown>;
  const result = (
    envelope.data && typeof envelope.data === "object" ? envelope.data : value
  ) as Record<string, unknown>;
  const rows = [
    "tracks",
    "playlists",
    "downloads",
    "files",
    "library_jobs",
  ].flatMap((key) =>
    Array.isArray(result[key]) ? (result[key] as ResultRow[]) : [],
  );
  if (!rows.length) return <pre>{JSON.stringify(result, null, 2)}</pre>;
  return (
    <ul className="ai-result-list">
      {rows.map((row, index) => (
        <li key={index}>
          <strong>{row.title || row.name || row.track?.title || "任务"}</strong>
          {(row.artist || row.track?.artist) && (
            <span>{row.artist || row.track?.artist}</span>
          )}
          {row.track_count !== undefined && <span>{row.track_count} 首</span>}
          {row.status && (
            <span>
              {states[row.status] ||
                (
                  {
                    queued: "已入队",
                    downloading: "下载中",
                    paused: "已暂停",
                    exists: "已存在",
                    needs_review: "待审核",
                    ready: "可审核",
                  } as Record<string, string>
                )[row.status] ||
                row.status}
            </span>
          )}
          {row.detail && <small>{row.detail}</small>}
        </li>
      ))}
    </ul>
  );
}
type Session = Summary & {
  detail: string;
  messages: { role: string; content: string; has_image?: boolean }[];
  events: Event[];
};
const labels: Record<string, string> = {
  search_music: "搜索音乐",
  list_playlists: "查询歌单",
  read_playlist: "读取歌单",
  create_playlist: "创建歌单",
  add_to_playlist: "加入歌单",
  download_music: "下载音乐",
  get_status: "查询任务",
  browse_library: "查询音乐库",
  preview_organize: "生成整理预览",
  list_project_operations: "查询项目操作",
  query_project: "查询项目",
  execute_project: "执行项目操作",
  wait_for_tasks: "等待后台任务",
};
const states: Record<string, string> = {
  running: "执行中",
  stopping: "正在停止",
  complete: "已完成",
  failed: "失败",
  stopped: "已停止",
  interrupted: "已中断",
  idle: "待开始",
};
const examples = [
  "搜索周杰伦的《晴天》，列出可下载版本",
  "把图片上的歌曲加入歌单「截图收藏」",
  "搜索陈奕迅的《十年》，下载后整理入库",
];
const active = (session: Summary | null) =>
  !!session && ["running", "stopping"].includes(session.status);

export function AIAssistant({
  openSettings,
  changed,
  navigate,
}: {
  openSettings: () => void;
  changed: () => Promise<void>;
  navigate: (view: "queue" | "playlists" | "organize") => void;
}) {
  const [sessions, setSessions] = useState<Summary[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [message, setMessage] = useState("");
  const [image, setImage] = useState("");
  const [imageName, setImageName] = useState("");
  const [allowActions, setAllowActions] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ready, setReady] = useState<boolean | null>(null);
  const [loaded, setLoaded] = useState(false);
  const upload = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const mounted = useRef(true);
  function remember(value: Session | null) {
    setSession(value);
    try {
      if (value) localStorage.setItem("melokeep-ai-session", value.id);
      else localStorage.removeItem("melokeep-ai-session");
    } catch {
      /* Optional preference. */
    }
  }
  async function load() {
    setError("");
    try {
      const [list, settings] = await Promise.all([
        api<Summary[]>("/agent/sessions"),
        api<{ enabled: boolean; model: string; base_url: string }>(
          "/agent/settings",
        ),
      ]);
      if (!mounted.current) return;
      setSessions(list);
      setReady(!!(settings.enabled && settings.model && settings.base_url));
      let last = "";
      try {
        last = localStorage.getItem("melokeep-ai-session") || "";
      } catch {
        /* Optional preference. */
      }
      const selected = list.find((s) => s.id === last) || list[0];
      if (selected) {
        const value = await api<Session>(`/agent/sessions/${selected.id}`);
        if (mounted.current) remember(value);
      }
      setLoaded(true);
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    }
  }
  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
    };
  }, []);
  const isRunning = active(session);
  useEffect(() => {
    if (!session || !isRunning) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await api<Session>(`/agent/sessions/${session!.id}`);
        if (disposed) return;
        setSession(value);
        setError("");
        if (!active(value)) {
          setSessions(await api<Summary[]>("/agent/sessions"));
          await changed();
        } else timer = setTimeout(() => void poll(), 1200);
      } catch (e) {
        if (!disposed) {
          setError((e as Error).message);
          timer = setTimeout(() => void poll(), 4000);
        }
      }
    }
    timer = setTimeout(() => void poll(), 800);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [session?.id, isRunning]);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest", behavior: "instant" });
  }, [session?.messages.length]);
  async function send() {
    if (busy || isRunning || (!message.trim() && !image)) return;
    setBusy(true);
    setError("");
    try {
      const target = session || (await api<Session>("/agent/sessions", "POST"));
      remember(target);
      const result = await api<Session>(
        `/agent/sessions/${target.id}/messages`,
        "POST",
        { message, image: image || null, allow_actions: allowActions },
      );
      remember(result);
      setMessage("");
      setImage("");
      setImageName("");
      setSessions(await api<Summary[]>("/agent/sessions"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="view ai-workspace">
      <div className="ai-toolbar">
        <label>
          对话
          <select
            aria-label="选择 AI 对话"
            value={session?.id || ""}
            disabled={busy}
            onChange={async (e) => {
              setBusy(true);
              setError("");
              try {
                remember(
                  await api<Session>(`/agent/sessions/${e.target.value}`),
                );
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <option value="" disabled>
              新对话
            </option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title} ·{" "}
                {states[s.id === session?.id ? session.status : s.status] ||
                  s.status}
              </option>
            ))}
          </select>
        </label>
        <button
          className="secondary"
          disabled={busy}
          onClick={() => {
            remember(null);
            setError("");
            input.current?.focus();
          }}
        >
          <Plus />
          新对话
        </button>
        <button
          className="icon-button"
          aria-label="删除当前 AI 对话"
          disabled={!session || isRunning || busy}
          onClick={async () => {
            if (
              !session ||
              !window.confirm(
                "删除此对话及执行记录？已创建的歌单和下载任务会保留。",
              )
            )
              return;
            setBusy(true);
            try {
              await api(`/agent/sessions/${session.id}`, "DELETE");
              remember(null);
              setSessions(await api<Summary[]>("/agent/sessions"));
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Trash2 />
        </button>
        <button className="text-button" onClick={openSettings}>
          模型设置
        </button>
      </div>
      {ready === false && (
        <div className="ai-setup">
          <strong>先连接你的 AI 模型</strong>
          <p>
            在设置中填写 OpenAI
            兼容接口、密钥和模型，即可通过对话操作音乐工作台。
          </p>
          <button className="primary" onClick={openSettings}>
            配置 AI 助手
          </button>
        </div>
      )}
      {error && (
        <div className="ai-error" role="alert">
          {error}
          {!loaded && (
            <button className="secondary" onClick={() => void load()}>
              重新加载
            </button>
          )}
        </div>
      )}
      <div className="ai-layout">
        <div className="ai-conversation">
          <div
            className="ai-messages"
            aria-label="AI 对话记录"
            aria-busy={isRunning}
          >
            {!session?.messages.length && (
              <div className="ai-empty">
                <MessageSquare aria-hidden="true" />
                <h2>从一句话或一张歌单截图开始</h2>
                <p>
                  搜索下载、管理歌单与曲库，也可以修改设置、管理任务和维护项目。
                </p>
                <div className="ai-examples">
                  {examples.map((example) => (
                    <button
                      key={example}
                      className="secondary"
                      onClick={() => {
                        setMessage(example);
                        input.current?.focus();
                      }}
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {session?.messages.map((item, index) => (
              <article key={index} className={`ai-message ai-${item.role}`}>
                <strong>{item.role === "user" ? "你" : "MeloKeep 助手"}</strong>
                {item.has_image && <small>附有图片</small>}
                <p>{item.content}</p>
              </article>
            ))}
            {session && (
              <p
                className={`ai-turn-status ${session.status === "failed" ? "ai-error" : ""}`}
                role="status"
              >
                {session.detail}
              </p>
            )}
            <div ref={end} />
          </div>
          <form
            className="ai-composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            {image && (
              <div className="ai-attachment">
                <img src={image} alt="待发送的歌单截图" />
                <span>{imageName}</span>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="移除图片"
                  onClick={() => {
                    setImage("");
                    setImageName("");
                  }}
                >
                  <X />
                </button>
              </div>
            )}
            <label htmlFor="ai-message">告诉助手你想做什么</label>
            <textarea
              id="ai-message"
              ref={input}
              value={message}
              maxLength={8000}
              disabled={busy || isRunning}
              placeholder="例如：把图片里的歌加入「通勤」，并下载整理入库"
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  (e.ctrlKey || e.metaKey) &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <div className="ai-composer-options">
              <label className="ready-filter">
                <input
                  type="checkbox"
                  checked={allowActions}
                  disabled={busy || isRunning}
                  onChange={(e) => setAllowActions(e.target.checked)}
                />
                允许本轮执行项目操作
              </label>
              <small>
                包括修改设置、整理和删除；按你的要求执行。取消勾选后仅查询 ·
                Ctrl / ⌘ + Enter 发送
              </small>
            </div>
            <div className="ai-actions">
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                ref={upload}
                hidden
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file) return;
                  if (
                    !["image/png", "image/jpeg", "image/webp"].includes(
                      file.type,
                    ) ||
                    file.size > 5 * 1024 * 1024
                  ) {
                    setError("请选择 5 MB 以内的 PNG、JPEG 或 WebP 图片");
                    return;
                  }
                  try {
                    const data = await new Promise<string>(
                      (resolve, reject) => {
                        const reader = new FileReader();
                        reader.onload = () => resolve(String(reader.result));
                        reader.onerror = () =>
                          reject(new Error("图片读取失败，请重新选择"));
                        reader.readAsDataURL(file);
                      },
                    );
                    setImage(data);
                    setImageName(file.name);
                    setError("");
                  } catch (e) {
                    setError((e as Error).message);
                  }
                }}
              />
              <button
                className="secondary"
                type="button"
                disabled={busy || isRunning}
                onClick={() => upload.current?.click()}
              >
                <ImagePlus />
                添加图片
              </button>
              <small>图片会发送给所配置的模型服务</small>
              {isRunning ? (
                <button
                  type="button"
                  className="secondary"
                  disabled={session?.status === "stopping"}
                  onClick={async () => {
                    try {
                      remember(
                        await api<Session>(
                          `/agent/sessions/${session!.id}/stop`,
                          "POST",
                        ),
                      );
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  <Square />
                  停止本轮
                </button>
              ) : (
                <button
                  type="submit"
                  className="primary"
                  disabled={
                    busy ||
                    ready !== true ||
                    !loaded ||
                    (!message.trim() && !image)
                  }
                >
                  <Send />
                  {busy ? "正在发送…" : "发送"}
                </button>
              )}
            </div>
          </form>
        </div>
        <aside className="ai-execution" aria-label="AI 执行记录">
          <h2>执行记录</h2>
          <p>每一步操作都会出现在这里。下载进度以下载队列为准。</p>
          <div className="ai-destinations">
            <button
              className="text-button"
              onClick={() => navigate("playlists")}
            >
              查看歌单
            </button>
            <button className="text-button" onClick={() => navigate("queue")}>
              下载队列
            </button>
            <button
              className="text-button"
              onClick={() => navigate("organize")}
            >
              审核整理
            </button>
          </div>
          {!session?.events.length && <p>尚未调用项目工具</p>}
          {session?.events.map((event, index) => (
            <details key={index} className="ai-event">
              <summary>
                <span>{labels[event.tool] || event.tool}</span>
                <small className={event.status === "failed" ? "ai-error" : ""}>
                  {states[event.status] || event.status}
                </small>
              </summary>
              {event.operation && <p>{event.operation}</p>}
              <p>{event.detail}</p>
              {event.result !== undefined && (
                <ExecutionResult value={event.result} />
              )}
            </details>
          ))}
        </aside>
      </div>
    </section>
  );
}
