import { useEffect, useState } from "react";
import { api } from "./api";

type Settings = {
  enabled: boolean;
  base_url: string;
  model: string;
  key_configured: boolean;
};

export function AISettings() {
  const [config, setConfig] = useState<Settings | null>(null);
  const [key, setKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function load() {
    try {
      setConfig(await api<Settings>("/agent/settings"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  return (
    <section className="settings-section ai-settings">
      <h2>AI 助手</h2>
      <p>
        连接支持工具调用的 OpenAI 兼容接口。识别歌单截图还需要模型支持图片输入。
      </p>
      {error && (
        <p role="alert" className="ai-error">
          {error}
        </p>
      )}
      {!config ? (
        <button className="secondary" onClick={() => void load()}>
          重新读取配置
        </button>
      ) : (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            setNotice("");
            try {
              const saved = await api<Settings>("/agent/settings", "PUT", {
                enabled: config.enabled,
                base_url: config.base_url,
                model: config.model,
                api_key: key,
                clear_key: clearKey,
              });
              setConfig(saved);
              setKey("");
              setClearKey(false);
              setNotice("AI 配置已保存");
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <fieldset disabled={busy}>
            <label className="ready-filter">
              <input
                type="checkbox"
                checked={config.enabled}
                onChange={(e) =>
                  setConfig({ ...config, enabled: e.target.checked })
                }
              />
              启用 AI 助手
            </label>
            <label>
              API 基础地址
              <input
                type="url"
                placeholder="https://api.example.com/v1"
                value={config.base_url}
                onChange={(e) =>
                  setConfig({ ...config, base_url: e.target.value })
                }
              />
            </label>
            <small>
              填写服务商提供的基础地址，包含 /v1 等前缀；系统会追加
              /chat/completions。
            </small>
            <label>
              模型名称
              <input
                placeholder="填写服务商提供的模型 ID"
                value={config.model}
                maxLength={200}
                onChange={(e) =>
                  setConfig({ ...config, model: e.target.value })
                }
              />
            </label>
            <label>
              API Key
              <input
                type="password"
                autoComplete="new-password"
                value={key}
                disabled={clearKey}
                placeholder={
                  config.key_configured
                    ? "已配置，留空保留"
                    : "本地无鉴权服务可留空"
                }
                onChange={(e) => setKey(e.target.value)}
              />
            </label>
            {config.key_configured && (
              <label className="ready-filter">
                <input
                  type="checkbox"
                  checked={clearKey}
                  onChange={(e) => setClearKey(e.target.checked)}
                />
                清除已保存的密钥
              </label>
            )}
            <p>
              发送的文字、图片及执行所需的歌曲资料会交给所配置的模型服务。API
              Key 仅保存在服务器，图片不写入对话历史。
            </p>
            <div className="ai-actions">
              <button className="primary" type="submit">
                {busy ? "正在处理…" : "保存配置"}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  setNotice("");
                  try {
                    setNotice(
                      (
                        await api<{ detail: string }>(
                          "/agent/settings/test",
                          "POST",
                        )
                      ).detail,
                    );
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                测试已保存的连接
              </button>
            </div>
          </fieldset>
        </form>
      )}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
