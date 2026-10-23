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

export function LibrarySettings() {
  const [config, setConfig] = useState<LibraryConfig | null>(null);
  const [password, setPassword] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [clearCredentials, setClearCredentials] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [navMessage, setNavMessage] = useState("");
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
        <h2>刮削、整理与入库</h2>
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
      const { navidrome: _nav, file_root: _root, ...settings } = config;
      const saved = await api<LibraryConfig>(
        "/library/settings",
        "PUT",
        settings,
      );
      setConfig(saved);
      setMessage("曲库设置已保存，新下载任务将按此规则处理。");
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
      <form onSubmit={saveLibrary} className="settings-section">
        <div className="library-section-title">
          <div>
            <h2>刮削、整理与入库</h2>
            <p>下载完成后按规则补全资料、整理文件，并加入本地音乐库。</p>
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
              <small>补全标签、歌词与封面，无法确定版本时等待人工确认。</small>
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
              相对目录位于 {config.file_root} 内；已有文件需从音乐库手动整理。
            </small>
          </label>
          <label>
            原文件恢复期限（天）
            <input
              type="number"
              min="1"
              max="365"
              value={config.backup_days}
              onChange={(e) => update("backup_days", Number(e.target.value))}
            />
            <small>
              整理历史可恢复原标签和目录；过期备份在服务启动时清理。
            </small>
          </label>
          <label>
            目录模板
            <input
              required
              value={config.folder_template}
              onChange={(e) => update("folder_template", e.target.value)}
            />
            <small>{"示例：{album_artist}/{album}"}</small>
          </label>
          <label>
            文件名模板
            <input
              required
              value={config.filename_template}
              onChange={(e) => update("filename_template", e.target.value)}
            />
            <small>
              {
                "示例：{track_number} - {title}，扩展名自动保留。缺少曲序时省略序号。"
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
        <fieldset className="library-fieldset">
          <legend>刮削来源</legend>
          <div className="library-checks">
            {[
              ["netease", "网易云"],
              ["qq", "QQ音乐"],
            ].map(([id, label]) => (
              <label className="check-label" key={id}>
                <input
                  type="checkbox"
                  checked={config.sources.includes(id)}
                  onChange={(e) =>
                    update(
                      "sources",
                      e.target.checked
                        ? [...config.sources, id]
                        : config.sources.filter((v) => v !== id),
                    )
                  }
                />
                {label}
              </label>
            ))}
          </div>
          <p className="setting-help">
            复用下方音源的
            Cookie、代理与请求设置。下载来源已明确时优先使用原始信息。
          </p>
        </fieldset>
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
            。相同文件名保留双方。
          </p>
        </details>
        <div className="management-toolbar">
          <button
            className="primary"
            disabled={!!busy || (config.auto_scrape && !config.sources.length)}
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
        onSubmit={(e) => {
          e.preventDefault();
          void saveNav();
        }}
      >
        <h2>Navidrome 连接</h2>
        <p>
          在 musicdl 浏览远程专辑、歌手与歌曲，并可在整理后通知 Navidrome 扫描。
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
              需要已有的 Navidrome 服务。musicdl 自身的刮削和整理可独立使用。
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
      {error && (
        <p className="library-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
