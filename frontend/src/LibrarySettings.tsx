import { useEffect, useState } from "react";
import { Check, PlugZap } from "lucide-react";
import { api } from "./api";
import type { LibraryConfig } from "./types";
import "./library.css";

export const tagLabels: Record<string, string> = {
  title: "歌曲标题",
  artist: "歌手",
  album: "专辑",
  album_artist: "专辑歌手",
  date: "发行日期",
  track_number: "曲序",
  disc_number: "碟号",
  genre: "流派",
  composer: "作曲",
  comment: "备注",
  lyricist: "作词",
  language: "语言",
  copyright: "版权",
  publisher: "发行商",
  grouping: "分组",
  bpm: "BPM",
  isrc: "ISRC",
};
export const processingLabels: Record<string, string> = {
  queued: "等待处理",
  identifying: "识别与匹配",
  tagging: "写入与整理",
  organizing: "整理目录",
  indexing: "更新曲库",
  complete: "已完成",
  ready: "等待应用",
  needs_review: "待确认",
  failed: "处理失败",
  partial: "部分完成",
  paused: "已暂停",
  cancelled: "已取消",
  restoring: "正在恢复",
  restored: "已恢复",
};

export function MetadataSources({
  config,
  change,
  disabled = false,
}: {
  config: LibraryConfig;
  change: (sources: string[]) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset className="library-fieldset metadata-sources">
      <legend>刮削资料来源</legend>
      <p className="setting-help">
        下载来源信息优先保留，再从所选来源查找候选。下载音源开关与刮削来源独立；每首歌可获得的字段以候选实际返回为准。
      </p>
      <div className="metadata-source-list">
        {config.metadata_sources?.map((source) => (
          <div className="metadata-source" key={source.id}>
            <label className="check-label">
              <input
                type="checkbox"
                disabled={disabled}
                checked={config.sources.includes(source.id)}
                onChange={(e) =>
                  change(
                    e.target.checked
                      ? [...config.sources, source.id]
                      : config.sources.filter((id) => id !== source.id),
                  )
                }
              />
              <strong>{source.label}</strong>
            </label>
            <div>
              <p>{source.description}</p>
              <small>
                {source.fields
                  .map((field) =>
                    field === "cover"
                      ? "封面"
                      : field === "lyrics"
                        ? "歌词"
                        : tagLabels[field] || field,
                  )
                  .join(" · ")}
              </small>
              <small>
                {source.note}{" "}
                <a href={source.url} target="_blank" rel="noreferrer">
                  来源网站
                </a>
              </small>
            </div>
          </div>
        ))}
      </div>
    </fieldset>
  );
}

export function LibrarySettings({
  openSources,
  section,
}: {
  openSources?: () => void;
  section: "library" | "navidrome";
}) {
  const [config, setConfig] = useState<LibraryConfig | null>(null);
  const [password, setPassword] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [clearCredentials, setClearCredentials] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [navMessage, setNavMessage] = useState("");
  const [acoustidKey, setAcoustidKey] = useState("");
  const [watchStatus, setWatchStatus] = useState("");
  const load = () =>
    api<LibraryConfig>("/library/settings")
      .then(setConfig)
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
  }, []);
  if (!config)
    return (
      <section className="settings-section">
        <h2>
          {section === "navidrome" ? "Navidrome 连接" : "刮削与归档默认规则"}
        </h2>
        <p role={error ? "alert" : "status"}>{error || "正在读取曲库设置…"}</p>
        {error && (
          <button className="secondary" onClick={() => void load()}>
            重新加载
          </button>
        )}
      </section>
    );
  const update = <K extends keyof LibraryConfig>(
    key: K,
    value: LibraryConfig[K],
  ) => setConfig({ ...config, [key]: value });
  async function saveLibrary(event: React.FormEvent) {
    event.preventDefault();
    if (!config) return;
    setBusy("library");
    setError("");
    setMessage("");
    try {
      const {
        navidrome: _nav,
        file_root: _root,
        metadata_sources: _sources,
        ...settings
      } = config;
      const saved = await api<LibraryConfig>(
        "/library/settings",
        "PUT",
        settings,
      );
      setConfig(saved);
      setMessage("曲库设置已保存，后续新建任务将使用这些默认规则。");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function saveNav(test = false) {
    if (!config) return;
    setBusy(test ? "test" : "nav");
    setError("");
    setNavMessage("");
    try {
      const {
        has_password: _password,
        has_api_key: _key,
        ...nav
      } = config.navidrome;
      const saved = await api<LibraryConfig["navidrome"]>(
        "/library/navidrome",
        "PUT",
        {
          ...nav,
          password: password || (clearCredentials ? "" : null),
          api_key: apiKey || (clearCredentials ? "" : null),
        },
      );
      setConfig({ ...config, navidrome: saved });
      setPassword("");
      setApiKey("");
      setClearCredentials(false);
      if (test) {
        const result = await api<{ version: string }>(
          "/navidrome/test",
          "POST",
        );
        setNavMessage(
          `连接成功${result.version ? `，服务器版本 ${result.version}` : ""}。可在音乐库的 Navidrome 页浏览。`,
        );
      } else setNavMessage("Navidrome 连接设置已保存。");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  return (
    <div className="engine-settings library-settings">
      {section === "library" && (
        <>
          <form onSubmit={saveLibrary} className="settings-section">
            <div className="library-section-title">
              <div>
                <h2>刮削与归档默认规则</h2>
                <p>
                  设置默认刮削来源、字段与归档规则，供自动下载处理和手动任务使用。
                </p>
              </div>
            </div>
            <div className="library-switches">
              <label className="library-switch">
                <input
                  type="checkbox"
                  checked={config.auto_scrape}
                  onChange={(e) => update("auto_scrape", e.target.checked)}
                />
                <span>
                  <strong>下载后自动刮削</strong>
                  <small>
                    补全标签、歌词与封面，无法确定版本时等待人工确认。
                  </small>
                </span>
              </label>
              <label className="library-switch">
                <input
                  type="checkbox"
                  checked={config.auto_organize}
                  onChange={(e) => update("auto_organize", e.target.checked)}
                />
                <span>
                  <strong>下载后自动整理入库</strong>
                  <small>
                    按最终标签归档到音乐库目录，歌词和封面随音频一起整理。
                  </small>
                </span>
              </label>
            </div>
            <div className="settings-grid">
              <label>
                整理后的音乐库目录
                <input
                  required
                  value={config.library_dir}
                  onChange={(e) => update("library_dir", e.target.value)}
                />
                <small>
                  相对目录位于 {config.file_root}{" "}
                  内；已有文件请在“刮削整理”中处理。
                </small>
              </label>
              <label>
                原文件恢复期限（天）
                <input
                  type="number"
                  min="1"
                  max="365"
                  value={config.backup_days}
                  onChange={(e) =>
                    update("backup_days", Number(e.target.value))
                  }
                />
                <small>
                  整理历史可恢复原标签和目录；过期备份在服务启动时清理。
                </small>
              </label>
              <label>
                目录模板
                <input
                  required
                  aria-label="目录模板"
                  aria-describedby="folder-template-help"
                  value={config.folder_template}
                  onChange={(e) => update("folder_template", e.target.value)}
                />
                <small id="folder-template-help">
                  决定音乐库内的子文件夹，用 / 分隔层级。
                  {
                    "例如 {album_artist}/{album} 会生成“专辑歌手/专辑”两层目录，不要填写完整路径。"
                  }
                </small>
              </label>
              <label>
                文件名模板
                <input
                  required
                  aria-label="文件名模板"
                  aria-describedby="filename-template-help"
                  value={config.filename_template}
                  onChange={(e) => update("filename_template", e.target.value)}
                />
                <small id="filename-template-help">
                  只决定文件的名称，不含目录和扩展名。
                  {
                    "例如 {track_number} - {title} 会生成“03 - 晴天.flac”；曲序自动补零，扩展名自动保留。"
                  }
                </small>
              </label>
              <label>
                歌词保存方式
                <select
                  value={config.lyrics_mode}
                  onChange={(e) => update("lyrics_mode", e.target.value)}
                >
                  <option value="both">内嵌标签和同名 LRC</option>
                  <option value="embed">仅内嵌标签</option>
                  <option value="lrc">仅同名 LRC</option>
                  <option value="none">不补全歌词</option>
                </select>
              </label>
              <label>
                封面保存方式
                <select
                  value={config.cover_mode}
                  onChange={(e) => update("cover_mode", e.target.value)}
                >
                  <option value="both">内嵌封面和同名图片</option>
                  <option value="embed">仅内嵌封面</option>
                  <option value="file">仅同名图片</option>
                  <option value="none">不补全封面</option>
                </select>
              </label>
            </div>
            <section
              className="template-help"
              aria-labelledby="template-help-title"
            >
              <h3 id="template-help-title">整理模板怎么填写</h3>
              <p>
                花括号中的英文是变量，整理时会替换成歌曲最终的标签内容；
                花括号外的空格、横线等文字会保留。修改英文变量之间的顺序和分隔符即可，
                不要把变量名翻译成中文。整理路径由“音乐库目录＋目录模板＋文件名模板＋原扩展名”组成。
              </p>
              <p>
                <strong>完整示例：</strong>
                假设歌曲为周杰伦《叶惠美》中的《晴天》，曲序为 3，发行年份为
                2003， 原文件格式为 FLAC。按照下面的设置整理：
              </p>
              <dl className="template-example">
                <dt>音乐库目录</dt>
                <dd>
                  <code>/music/library</code>
                </dd>
                <dt>目录模板</dt>
                <dd>
                  <code>{"{album_artist}/{album}"}</code>
                </dd>
                <dt>文件名模板</dt>
                <dd>
                  <code>{"{track_number} - {title}"}</code>
                </dd>
                <dt>最终文件路径</dt>
                <dd>
                  <code>/music/library/周杰伦/叶惠美/03 - 晴天.flac</code>
                </dd>
              </dl>
              <details className="library-advanced">
                <summary>查看常用变量、更多写法与缺失标签的处理</summary>
                <table className="template-variables">
                  <thead>
                    <tr>
                      <th>变量</th>
                      <th>含义</th>
                      <th>示例</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ["album_artist", "专辑歌手；未填写时使用歌手", "周杰伦"],
                      ["artist", "歌曲的歌手", "周杰伦"],
                      ["album", "专辑名称", "叶惠美"],
                      ["title", "歌曲标题", "晴天"],
                      ["track_number", "曲序，自动补足至少两位", "03"],
                      ["disc_number", "碟号", "1"],
                      ["year", "发行日期的前四位", "2003"],
                      ["date", "完整发行日期，以歌曲标签为准", "2003-07-31"],
                      ["genre", "流派", "流行"],
                      ["first_artist", "合作歌曲中的第一位歌手", "周杰伦"],
                      [
                        "first_artist_letter",
                        "第一位歌手的拼音或名称首字母",
                        "Z",
                      ],
                      [
                        "file_song_name",
                        "原文件名，不含扩展名",
                        "原始下载文件",
                      ],
                    ].map(([variable, meaning, example]) => (
                      <tr key={variable}>
                        <td>
                          <code>{`{${variable}}`}</code>
                        </td>
                        <td>{meaning}</td>
                        <td>{example}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p>
                  <strong>想把年份放到专辑前：</strong>
                  {
                    "目录模板改为 {album_artist}/{year} - {album}，文件名模板不变，结果为 "
                  }
                  <code>
                    /music/library/周杰伦/2003 - 叶惠美/03 - 晴天.flac
                  </code>
                  。
                </p>
                <p>
                  <strong>想按歌手归档，并在文件名中显示歌手：</strong>
                  {
                    "目录模板填 {artist}，文件名模板填 {artist} - {title}，结果为 "
                  }
                  <code>/music/library/周杰伦/周杰伦 - 晴天.flac</code>。
                </p>
                <p>
                  歌手缺失时使用“未知歌手”，专辑缺失时使用“未知专辑”，
                  标题缺失时使用原文件名；默认文件名模板缺少曲序时会生成“晴天.flac”。
                  其他缺失变量会替换为空文本。文件名中不要填写 /
                  或反斜线，也不要手动加 .flac、.mp3。
                  修改设置并保存后，对之后的整理任务生效；已有文件可在“刮削整理”中先预览目标路径再应用。
                </p>
              </details>
            </section>
            <MetadataSources
              config={config}
              change={(sources) => update("sources", sources)}
              disabled={!!busy}
            />
            <details className="library-advanced">
              <summary>目录监控与预处理</summary>
              <p className="setting-help">
                持续检查新文件，等待文件稳定后生成刮削任务。处理规则使用已保存的设置；音乐库目录与监控目录需分开。
              </p>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={config.watch_enabled || false}
                  onChange={(e) => update("watch_enabled", e.target.checked)}
                />
                启用目录监控
              </label>
              <div className="settings-grid">
                <label>
                  监控目录（每行一个）
                  <textarea
                    rows={3}
                    aria-label="监控目录（每行一个）"
                    value={(config.watch_dirs || ["incoming"]).join("\n")}
                    onChange={(e) =>
                      update("watch_dirs", e.target.value.split("\n"))
                    }
                  />
                  <small>
                    相对路径位于音乐根目录内，也可填写已挂载目录的绝对路径。
                  </small>
                </label>
                <label>
                  检查间隔（秒）
                  <input
                    type="number"
                    min={10}
                    max={86400}
                    value={config.watch_interval ?? 180}
                    onChange={(e) =>
                      update("watch_interval", Number(e.target.value))
                    }
                  />
                </label>
                <label>
                  未匹配/失败文件目录（可选）
                  <input
                    value={config.watch_failure_dir || ""}
                    aria-label="未匹配/失败文件目录（可选）"
                    onChange={(e) =>
                      update("watch_failure_dir", e.target.value)
                    }
                    placeholder="例如 review；留空保留原处"
                  />
                  <small>
                    须与监控目录、最终音乐库分开。转移也保留恢复记录。
                  </small>
                </label>
                <label>
                  文件稳定等待（秒）
                  <input
                    type="number"
                    min={2}
                    max={3600}
                    value={config.watch_stable_seconds ?? 30}
                    onChange={(e) =>
                      update("watch_stable_seconds", Number(e.target.value))
                    }
                  />
                </label>
                <label>
                  监控处理方式
                  <select
                    value={config.watch_action || "both"}
                    onChange={(e) => update("watch_action", e.target.value)}
                  >
                    <option value="both">刮削并整理入库</option>
                    <option value="scrape">只刮削资料</option>
                    <option value="organize">只整理目录</option>
                  </select>
                </label>
                <label>
                  中文预处理
                  <select
                    value={config.chinese || "none"}
                    onChange={(e) => update("chinese", e.target.value)}
                  >
                    <option value="none">保留原文</option>
                    <option value="simplified">繁体转简体</option>
                    <option value="traditional">简体转繁体</option>
                  </select>
                </label>
              </div>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={config.repair_encoding || false}
                  onChange={(e) => update("repair_encoding", e.target.checked)}
                />
                修复 UTF-8 被按 Latin1 误读的乱码
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={config.watch_apply ?? true}
                  onChange={(e) => update("watch_apply", e.target.checked)}
                />
                自动应用可靠匹配；关闭时所有监控任务先等待审核
              </label>
              <div className="management-toolbar">
                <button
                  type="button"
                  className="secondary"
                  disabled={!!busy}
                  onClick={async () => {
                    setBusy("watch");
                    setError("");
                    try {
                      const result = await api<{ detail: string }>(
                        "/library/watch/scan",
                        "POST",
                      );
                      setWatchStatus(result.detail);
                    } catch (e) {
                      setError((e as Error).message);
                    } finally {
                      setBusy("");
                    }
                  }}
                >
                  检查已保存的监控目录
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={async () => {
                    try {
                      const result = await api<{
                        detail?: string;
                        error?: string;
                        checked_at?: number;
                      }>("/library/watch");
                      setWatchStatus(
                        `${result.checked_at ? new Date(result.checked_at * 1000).toLocaleString("zh-CN") + " · " : ""}${result.error || result.detail || "尚未检查"}`,
                      );
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  查看监控状态
                </button>
              </div>
              {watchStatus && <p role="status">{watchStatus}</p>}
            </details>
            {openSources && (
              <button className="secondary" type="button" onClick={openSources}>
                配置平台 Cookie 与代理
              </button>
            )}
            <details className="library-advanced">
              <summary>字段与覆盖规则</summary>
              <fieldset className="library-fieldset">
                <legend>允许自动补全的标签</legend>
                <div className="library-checks">
                  {Object.entries(tagLabels).map(([key, label]) => (
                    <label key={key} className="check-label">
                      <input
                        type="checkbox"
                        checked={config.fields.includes(key)}
                        onChange={(e) =>
                          update(
                            "fields",
                            e.target.checked
                              ? [...config.fields, key]
                              : config.fields.filter((v) => v !== key),
                          )
                        }
                      />
                      {label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={config.overwrite}
                  onChange={(e) => update("overwrite", e.target.checked)}
                />
                覆盖已有标签（关闭时只补空值，手动锁定的字段始终保留）
              </label>
              <p className="setting-help">
                支持的目录变量：
                {Object.keys(tagLabels)
                  .map((key) => `{${key}}`)
                  .join("、")}
                {
                  "。同时支持 ${albumartist}、${first_artist}、${first_artist_letter}、${year}、${counter} 和条件、zfill、replace、split 等表达式。相同文件名保留双方。"
                }
              </p>
            </details>
            <div className="management-toolbar">
              <button
                className="primary"
                disabled={
                  !!busy || (config.auto_scrape && !config.sources.length)
                }
              >
                <Check />
                {busy === "library" ? "正在保存…" : "保存曲库设置"}
              </button>
              {config.auto_scrape && !config.sources.length && (
                <span role="status">请选择至少一个刮削来源。</span>
              )}
              {message && <span role="status">{message}</span>}
            </div>
          </form>
          <form
            className="settings-section"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy("acoustid");
              setError("");
              try {
                const saved = await api<{ has_acoustid_key: boolean }>(
                  "/library/credentials",
                  "PUT",
                  { acoustid_key: acoustidKey },
                );
                setConfig({ ...config, ...saved });
                setAcoustidKey("");
                setMessage("AcoustID 配置已保存。");
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy("");
              }
            }}
          >
            <h2>音频指纹识别</h2>
            <p>
              文件名或标签缺失时，可在刮削来源中选择
              AcoustID。识别后仍需核对具体发行版本。
            </p>
            <label>
              AcoustID 应用 Key
              <input
                type="password"
                autoComplete="new-password"
                value={acoustidKey}
                onChange={(e) => setAcoustidKey(e.target.value)}
                placeholder={
                  config.has_acoustid_key
                    ? "已配置；输入新 Key 可替换"
                    : "填写 acoustid.org 申请的应用 Key"
                }
              />
            </label>
            <p className="setting-help">
              需要服务器安装 fpcalc；Docker
              镜像已包含。只发送指纹和时长，不上传音频。
              <a
                href="https://acoustid.org/new-application"
                target="_blank"
                rel="noreferrer"
              >
                申请应用 Key
              </a>
            </p>
            <div className="management-toolbar">
              <button className="primary" disabled={!!busy || !acoustidKey}>
                保存指纹配置
              </button>
              <span>
                {config.has_acoustid_key ? "Key 已配置" : "Key 未配置"} ·{" "}
                {config.tools?.fpcalc ? "fpcalc 已找到" : "fpcalc 未找到"}
              </span>
            </div>
          </form>
        </>
      )}
      {section === "navidrome" && (
        <form
          className="settings-section"
          onSubmit={(e) => {
            e.preventDefault();
            void saveNav();
          }}
        >
          <h2>Navidrome 连接</h2>
          <p>
            在 MeloKeep 浏览远程专辑、歌手与歌曲，并可在整理后通知 Navidrome
            扫描。
          </p>
          <label className="library-switch">
            <input
              type="checkbox"
              checked={config.navidrome.enabled}
              onChange={(e) =>
                update("navidrome", {
                  ...config.navidrome,
                  enabled: e.target.checked,
                })
              }
            />
            <span>
              <strong>启用 Navidrome</strong>
              <small>
                需要已有的 Navidrome 服务。MeloKeep 自身的刮削和整理可独立使用。
              </small>
            </span>
          </label>
          <div className="settings-grid">
            <label>
              服务地址
              <input
                placeholder="http://服务器IP:4533"
                value={config.navidrome.url}
                onChange={(e) =>
                  update("navidrome", {
                    ...config.navidrome,
                    url: e.target.value,
                  })
                }
              />
              <small>填写服务地址，可包含反向代理的路径前缀。</small>
            </label>
            <label>
              用户名
              <input
                autoComplete="off"
                value={config.navidrome.username}
                onChange={(e) =>
                  update("navidrome", {
                    ...config.navidrome,
                    username: e.target.value,
                  })
                }
              />
            </label>
            <label>
              密码
              <input
                type="password"
                autoComplete="new-password"
                placeholder={
                  config.navidrome.has_password
                    ? "已保存，留空保留"
                    : "Navidrome 密码"
                }
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <label>
              API Key（可选）
              <input
                type="password"
                autoComplete="new-password"
                placeholder={
                  config.navidrome.has_api_key
                    ? "已保存，留空保留"
                    : "服务支持时可代替用户名和密码"
                }
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </label>
          </div>
          <label className="check-label">
            <input
              type="checkbox"
              checked={config.navidrome.auto_scan}
              onChange={(e) =>
                update("navidrome", {
                  ...config.navidrome,
                  auto_scan: e.target.checked,
                })
              }
            />
            本地整理完成后自动触发 Navidrome 扫描
          </label>
          <p className="setting-help">
            Navidrome
            需要能访问整理后的同一音乐库目录；扫描接口需要相应权限，扫描完成前歌曲可能尚未出现。
          </p>
          {(config.navidrome.has_password || config.navidrome.has_api_key) && (
            <label className="check-label">
              <input
                type="checkbox"
                checked={clearCredentials}
                onChange={(e) => setClearCredentials(e.target.checked)}
              />
              清除原有认证信息（新填写的值会被保留）
            </label>
          )}
          <div className="management-toolbar">
            <button className="primary" disabled={!!busy}>
              {busy === "nav" ? "正在保存…" : "保存 Navidrome"}
            </button>
            <button
              className="secondary"
              type="button"
              disabled={!!busy || !config.navidrome.enabled}
              onClick={() => void saveNav(true)}
            >
              <PlugZap />
              {busy === "test" ? "正在连接…" : "保存并测试连接"}
            </button>
          </div>
          {navMessage && <p role="status">{navMessage}</p>}
        </form>
      )}
      {error && (
        <p className="library-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
