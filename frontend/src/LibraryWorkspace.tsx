import { useState, type ComponentProps } from "react";
import { Folder, History, Library, Settings, WandSparkles } from "lucide-react";
import { MusicLibrary } from "./MusicLibrary";
import { NavidromeLibrary } from "./NavidromeLibrary";
import { LibraryJobs } from "./LibraryJobs";
import { LibrarySettings, tagLabels } from "./LibrarySettings";
import { LibraryWorkbench } from "./LibraryWorkbench";
import { Modal } from "./components";
import { api } from "./api";
import type { LibraryFile, LibraryJob } from "./types";
import "./library.css";

type LibraryProps = ComponentProps<typeof MusicLibrary>;
export type LibraryAction =
  | "scrape"
  | "organize"
  | "both"
  | "edit"
  | "extract"
  | "clean"
  | "duplicates"
  | "rename"
  | "export_lyrics"
  | "import_lyrics"
  | "export_cover"
  | "import_cover"
  | "clear"
  | "convert"
  | "split"
  | "quality"
  | "artist_artwork";

export function LibraryWorkspace({
  openSettings,
  tab,
  setTab,
  ...props
}: LibraryProps & {
  openSettings: () => void;
  tab: string;
  setTab: (tab: string) => void;
}) {
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
  const [filenameTemplate, setFilenameTemplate] = useState(
    "${tracknumber.zfill(2) + '. ' if tracknumber else ''}${title} - ${artist}",
  );
  const [extractTemplate, setExtractTemplate] = useState("");
  const [chinese, setChinese] = useState("none");
  const [repairEncoding, setRepairEncoding] = useState(false);
  const [duplicateMode, setDuplicateMode] = useState("file");
  const [format, setFormat] = useState("flac");
  const [bitrate, setBitrate] = useState(320);
  const [sampleRate, setSampleRate] = useState(0);
  const [cue, setCue] = useState("");
  async function submit(
    action: LibraryAction,
    files: LibraryFile[],
    options: Record<string, unknown> = {},
  ) {
    setBusy(true);
    setError("");
    try {
      const job = await api<LibraryJob>("/library/jobs", "POST", {
        paths:
          options.scope_dir !== undefined
            ? []
            : files.filter((file) => file.track).map((file) => file.path),
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
    if (
      [
        "scrape",
        "organize",
        "both",
        "export_lyrics",
        "import_lyrics",
        "export_cover",
        "import_cover",
        "quality",
        "artist_artwork",
      ].includes(action)
    ) {
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
    ["workbench", "选择与处理", WandSparkles],
    ["jobs", "任务与审核", History],
    ["rules", "来源与归档规则", Settings],
    ["navidrome", "Navidrome", Library],
  ] as const;
  return (
    <>
      <div
        className="library-tabs"
        role="tablist"
        aria-label="音乐库管理"
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
        {tab === "workbench" && (
          <>
            <LibraryWorkbench
              count={
                props.files.filter(
                  (file) => file.track && props.selected.includes(file.path),
                ).length
              }
              busy={props.busy || busy}
              rules={() => setTab("rules")}
              start={(action, options) =>
                void submit(
                  action,
                  props.files.filter(
                    (file) => file.track && props.selected.includes(file.path),
                  ),
                  options,
                )
              }
            />
            <MusicLibrary
              {...props}
              busy={props.busy || busy}
              manage={manage}
              processing
            />
          </>
        )}
        {tab === "rules" && <LibrarySettings openSources={openSettings} />}
        {tab === "jobs" && (
          <LibraryJobs focus={focus} changed={props.refresh} />
        )}
        {tab === "navidrome" && (
          <NavidromeLibrary
            play={props.play}
            queue={props.queue}
            openSettings={() => setTab("rules")}
          />
        )}
      </div>
      {operation && (
        <Modal
          title={
            (
              {
                edit: "编辑选中歌曲",
                extract: "从文件名提取标签",
                clean: "清理标签文本",
                rename: "批量重命名",
                duplicates: "重复文件检查",
                convert: "转换音频格式",
                split: "CUE 分轨",
                clear: "清空内嵌标签",
              } as Record<string, string>
            )[operation.action] || "音乐处理"
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
                    ? {
                        filename_order: filenameOrder,
                        extract_template: extractTemplate,
                      }
                    : operation.action === "rename"
                      ? { filename_template: filenameTemplate }
                      : operation.action === "duplicates"
                        ? { duplicate_mode: duplicateMode }
                        : ["convert", "split"].includes(operation.action)
                          ? {
                              output_format: format,
                              bitrate,
                              sample_rate: sampleRate,
                              cue,
                            }
                          : {
                              find,
                              replacement,
                              chinese,
                              repair_encoding: repairEncoding,
                            },
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
                  {
                    " 支持 ${title}、${albumartist}、${counter} 等变量，按每首歌原标签计算。"
                  }
                </p>
              </>
            )}
            {operation.action === "extract" && (
              <>
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
                <label>
                  自定义提取模板（可选）
                  <input
                    value={extractTemplate}
                    onChange={(e) => setExtractTemplate(e.target.value)}
                    placeholder="{track_number} - {artist} - {title}"
                  />
                  <small>模板包含分隔符和标签变量；填写后优先使用模板。</small>
                </label>
              </>
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
                <label>
                  中文转换
                  <select
                    value={chinese}
                    aria-label="中文转换"
                    onChange={(e) => setChinese(e.target.value)}
                  >
                    <option value="none">保留原文</option>
                    <option value="simplified">繁体转简体</option>
                    <option value="traditional">简体转繁体</option>
                  </select>
                </label>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={repairEncoding}
                    onChange={(e) => setRepairEncoding(e.target.checked)}
                  />
                  修复 UTF-8 被按 Latin1 误读的乱码
                </label>
              </>
            )}
            {operation.action === "rename" && (
              <label>
                文件名模板
                <input
                  required
                  maxLength={1000}
                  aria-label="文件名模板"
                  value={filenameTemplate}
                  onChange={(e) => setFilenameTemplate(e.target.value)}
                />
                <small>
                  {
                    "支持 ${title}、${artist}、${tracknumber}、${counter} 和条件表达式；扩展名自动保留，目录不变。"
                  }
                </small>
              </label>
            )}
            {operation.action === "duplicates" && (
              <label>
                检查方式
                <select
                  value={duplicateMode}
                  aria-label="检查方式"
                  onChange={(e) => setDuplicateMode(e.target.value)}
                >
                  <option value="file">文件字节完全相同（含标签）</option>
                  <option value="audio">
                    解码音频相同（忽略标签，耗时较长）
                  </option>
                  <option value="identity">
                    标题、歌手和时长相同（疑似重复）
                  </option>
                </select>
                <small>生成报告后可比较文件和音频参数，再自行删除。</small>
              </label>
            )}
            {["convert", "split"].includes(operation.action) && (
              <>
                <div className="settings-grid">
                  <label>
                    输出格式
                    <select
                      value={format}
                      aria-label="输出格式"
                      onChange={(e) => {
                        setFormat(e.target.value);
                        setSampleRate(0);
                        setBitrate(e.target.value === "opus" ? 128 : 320);
                      }}
                    >
                      {["flac", "mp3", "m4a", "opus", "wav"].map((v) => (
                        <option key={v} value={v}>
                          {v.toUpperCase()}
                        </option>
                      ))}
                    </select>
                  </label>
                  {["mp3", "m4a", "opus"].includes(format) && (
                    <label>
                      码率（kbps）
                      <input
                        type="number"
                        min={32}
                        max={format === "mp3" ? 320 : 512}
                        value={bitrate}
                        onChange={(e) => setBitrate(Number(e.target.value))}
                      />
                    </label>
                  )}
                  <label>
                    采样率
                    <select
                      value={sampleRate}
                      aria-label="采样率"
                      onChange={(e) => setSampleRate(Number(e.target.value))}
                    >
                      {(format === "opus"
                        ? [0, 8000, 16000, 24000, 48000]
                        : format === "mp3"
                          ? [0, 22050, 44100, 48000]
                          : [0, 44100, 48000, 88200, 96000, 192000]
                      ).map((v) => (
                        <option key={v} value={v}>
                          {v ? `${v} Hz` : "保留原采样率"}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                {operation.action === "split" && (
                  <label>
                    CUE 文本（可选）
                    <textarea
                      rows={8}
                      aria-label="CUE 文本（可选）"
                      value={cue}
                      onChange={(e) => setCue(e.target.value)}
                      placeholder="留空使用每个音频旁的同名 .cue 文件"
                    />
                    <small>
                      支持 UTF-8 / GB18030 的多 FILE CUE，按 INDEX 01
                      分割。歌词时间轴保留在原件中。
                    </small>
                  </label>
                )}
                <p className="setting-help">
                  使用服务器 FFmpeg
                  生成新文件，保留原音频。转码不能提升原始音质；输出路径会在预览中列出。
                </p>
              </>
            )}
            {operation.action === "clear" && (
              <p className="library-warning">
                将清空全部标签（含自定义标签）、内嵌歌词与封面。同名歌词和图片文件保留。下一步请核对修改预览，应用后可从任务记录恢复。
              </p>
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
