import { useState, type ComponentProps } from "react";
import { Folder, History, Library, WandSparkles } from "lucide-react";
import { MusicLibrary } from "./MusicLibrary";
import { NavidromeLibrary } from "./NavidromeLibrary";
import { LibraryJobs } from "./LibraryJobs";
import { tagLabels } from "./LibrarySettings";
import { Modal } from "./components";
import { api } from "./api";
import type { LibraryFile, LibraryJob } from "./types";
import "./library.css";

type LibraryProps = ComponentProps<typeof MusicLibrary>;
export type LibraryAction =
  "scrape" | "organize" | "both" | "edit" | "extract" | "clean" | "duplicates";

export function LibraryWorkspace({
  openSettings,
  ...props
}: LibraryProps & { openSettings: () => void }) {
  const [tab, setTab] = useState("local");
  const [focus, setFocus] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [operation, setOperation] = useState<{
    action: LibraryAction;
    files: LibraryFile[];
  } | null>(null);
  const [changes, setChanges] = useState<Record<string, string>>({});
  const [fields, setFields] = useState<string[]>([]);
  const [lyrics, setLyrics] = useState("");
  const [editLyrics, setEditLyrics] = useState(false);
  const [cover, setCover] = useState<string | null>(null);
  const [coverName, setCoverName] = useState("");
  const [find, setFind] = useState("");
  const [replacement, setReplacement] = useState("");
  const [filenameOrder, setFilenameOrder] = useState("title_artist");
  async function submit(
    action: LibraryAction,
    files: LibraryFile[],
    options: Record<string, unknown> = {},
  ) {
    setBusy(true);
    setError("");
    try {
      const job = await api<LibraryJob>("/library/jobs", "POST", {
        paths: files.filter((file) => file.track).map((file) => file.path),
        action,
        ...options,
      });
      setOperation(null);
      setFocus(job.id);
      setTab("jobs");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function manage(action: LibraryAction, files: LibraryFile[]) {
    const audio = files.filter((file) => file.track);
    if (!audio.length) return;
    if (["scrape", "organize", "both", "duplicates"].includes(action)) {
      void submit(action, audio);
      return;
    }
    setError("");
    setFields([]);
    setLyrics("");
    setEditLyrics(false);
    setCover(null);
    setCoverName("");
    setChanges(
      audio.length === 1
        ? audio[0].metadata || {
            title: audio[0].track!.title,
            artist: audio[0].track!.artist,
            album: audio[0].track!.album,
          }
        : {},
    );
    setOperation({ action, files: audio });
  }
  const tabs = [
    ["local", "本地音乐", Folder],
    ["jobs", "刮削与整理", History],
    ["navidrome", "Navidrome", Library],
  ] as const;
  return (
    <>
      <div
        className="library-tabs"
        role="tablist"
        aria-label="音乐库来源"
        onKeyDown={(e) => {
          const index = tabs.findIndex(([id]) => id === tab);
          const next =
            e.key === "ArrowRight"
              ? (index + 1) % tabs.length
              : e.key === "ArrowLeft"
                ? (index + tabs.length - 1) % tabs.length
                : e.key === "Home"
                  ? 0
                  : e.key === "End"
                    ? tabs.length - 1
                    : -1;
          if (next < 0) return;
          e.preventDefault();
          setTab(tabs[next][0]);
          document.getElementById(`library-tab-${tabs[next][0]}`)?.focus();
        }}
      >
        {tabs.map(([id, label, Icon]) => (
          <button
            key={id}
            role="tab"
            tabIndex={tab === id ? 0 : -1}
            aria-selected={tab === id}
            aria-controls={`library-panel-${id}`}
            id={`library-tab-${id}`}
            onClick={() => setTab(id)}
          >
            <Icon />
            {label}
          </button>
        ))}
      </div>
      {error && !operation && (
        <p role="alert" className="library-error">
          {error}
        </p>
      )}
      <div
        role="tabpanel"
        id={`library-panel-${tab}`}
        aria-labelledby={`library-tab-${tab}`}
      >
        {tab === "local" && (
          <MusicLibrary {...props} busy={props.busy || busy} manage={manage} />
        )}
        {tab === "jobs" && (
          <LibraryJobs focus={focus} changed={props.refresh} />
        )}
        {tab === "navidrome" && (
          <NavidromeLibrary
            play={props.play}
            queue={props.queue}
            openSettings={openSettings}
          />
        )}
      </div>
      {operation && (
        <Modal
          title={
            operation.action === "edit"
              ? "编辑选中歌曲"
              : operation.action === "extract"
                ? "从文件名提取标签"
                : "清理标签文本"
          }
          close={busy ? undefined : () => setOperation(null)}
        >
          <form
            className="library-edit library-batch-edit"
            onSubmit={(e) => {
              e.preventDefault();
              void submit(
                operation.action,
                operation.files,
                operation.action === "edit"
                  ? {
                      changes: Object.fromEntries(
                        fields.map((key) => [key, changes[key] || ""]),
                      ),
                      lyrics: editLyrics ? lyrics : null,
                      cover_data: cover,
                    }
                  : operation.action === "extract"
                    ? { filename_order: filenameOrder }
                    : { find, replacement },
              );
            }}
          >
            <p>
              已选 {operation.files.length}{" "}
              首歌曲。下一步先预览修改，确认后才写入文件。
            </p>
            {operation.action === "edit" && (
              <>
                <div className="batch-tag-fields">
                  {Object.entries(tagLabels).map(([key, label]) => (
                    <label key={key}>
                      <span className="check-label">
                        <input
                          type="checkbox"
                          checked={fields.includes(key)}
                          onChange={(e) =>
                            setFields(
                              e.target.checked
                                ? [...fields, key]
                                : fields.filter((field) => field !== key),
                            )
                          }
                        />
                        修改{label}
                      </span>
                      <input
                        aria-label={`批量${label}`}
                        disabled={!fields.includes(key)}
                        value={changes[key] || ""}
                        maxLength={key === "comment" ? 2000 : 300}
                        onChange={(e) =>
                          setChanges({ ...changes, [key]: e.target.value })
                        }
                        placeholder={
                          fields.includes(key) ? "留空将清除此标签" : "不修改"
                        }
                      />
                    </label>
                  ))}
                </div>
                <label>
                  <span className="check-label">
                    <input
                      type="checkbox"
                      checked={editLyrics}
                      onChange={(e) => setEditLyrics(e.target.checked)}
                    />
                    修改歌词
                  </span>
                  <textarea
                    rows={6}
                    disabled={!editLyrics}
                    placeholder="粘贴纯文本或 LRC 歌词，留空可清空内嵌歌词"
                    value={lyrics}
                    onChange={(e) => setLyrics(e.target.value)}
                  />
                </label>
                <label>
                  替换封面（PNG/JPEG，最多 8 MB）
                  <input
                    type="file"
                    accept="image/png,image/jpeg"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (!file) {
                        setCover(null);
                        setCoverName("");
                        return;
                      }
                      if (
                        file.size > 8 * 1024 * 1024 ||
                        !["image/png", "image/jpeg"].includes(file.type)
                      ) {
                        setError("请选择不超过 8 MB 的 PNG/JPEG 图片");
                        e.target.value = "";
                        return;
                      }
                      const reader = new FileReader();
                      reader.onload = () => {
                        setCover(String(reader.result));
                        setCoverName(file.name);
                        setError("");
                      };
                      reader.onerror = () =>
                        setError("封面读取失败，请重新选择");
                      reader.readAsDataURL(file);
                    }}
                  />
                  {coverName && <small>{coverName}</small>}
                </label>
                <p className="setting-help">
                  只修改勾选的字段。手动修改后的文字标签会锁定，后续自动刮削会保留。
                </p>
              </>
            )}
            {operation.action === "extract" && (
              <label>
                文件名格式
                <select
                  value={filenameOrder}
                  onChange={(e) => setFilenameOrder(e.target.value)}
                >
                  <option value="title_artist">歌曲标题 - 歌手</option>
                  <option value="artist_title">歌手 - 歌曲标题</option>
                </select>
                <small>
                  按带空格的短横线拆分，不改变文件名。无法匹配的文件保留原标签。
                </small>
              </label>
            )}
            {operation.action === "clean" && (
              <>
                <p className="setting-help">
                  自动合并多余空白，去除首尾空格；还可替换所有文字标签中的指定内容。
                </p>
                <label>
                  查找文本（可选）
                  <input
                    maxLength={300}
                    value={find}
                    onChange={(e) => setFind(e.target.value)}
                  />
                </label>
                <label>
                  替换为
                  <input
                    maxLength={300}
                    value={replacement}
                    onChange={(e) => setReplacement(e.target.value)}
                  />
                  <small>替换内容留空时移除查找文本。</small>
                </label>
              </>
            )}
            {error && (
              <p role="alert" className="library-error">
                {error}
              </p>
            )}
            <div className="management-toolbar">
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setOperation(null)}
              >
                取消
              </button>
              <button
                className="primary"
                disabled={
                  busy ||
                  (operation.action === "edit" &&
                    !fields.length &&
                    !editLyrics &&
                    !cover)
                }
              >
                <WandSparkles />
                {busy ? "正在创建预览…" : "预览修改"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
