import { useEffect, useRef, useState } from "react";
import { api } from "./api";

type Settings = {
  enabled: boolean;
  base_url: string;
  model: string;
  api_type: "chat_completions" | "responses";
  proxy_mode: "direct" | "project";
  key_configured: boolean;
  project_proxy_configured: boolean;
};
type Draft = Pick<
  Settings,
  "enabled" | "base_url" | "model" | "api_type" | "proxy_mode"
> & {
  api_key: string;
  clear_key: boolean;
};

export function AISettings() {
  const [config, setConfig] = useState<Settings | null>(null);
  const [key, setKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [modelsBusy, setModelsBusy] = useState(false);
  const [modelsNotice, setModelsNotice] = useState("");
  const form = useRef<HTMLFormElement>(null);
  const modelRequest = useRef<AbortController | null>(null);
  const modelTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );

  async function load() {
    try {
      const value = await api<Settings>("/agent/settings");
      setConfig({
        ...value,
        api_type: value.api_type || "chat_completions",
        proxy_mode: value.proxy_mode || "direct",
      });
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void load();
  }, []);

  function draft(): Draft {
    // Read the form before disabling it, including browser autofill that did not fire onChange.
    const data = new FormData(form.current!);
    return {
      enabled: data.has("enabled"),
      base_url: String(data.get("base_url") || "").trim(),
      model: String(data.get("model") || "").trim(),
      api_type: data.get("api_type") as Settings["api_type"],
      proxy_mode: data.get("proxy_mode") as Settings["proxy_mode"],
      api_key: String(data.get("api_key") || "").trim(),
      clear_key: data.has("clear_key"),
    };
  }
  function update<K extends keyof Settings>(name: K, value: Settings[K]) {
    setConfig((current) => current && { ...current, [name]: value });
    setError("");
    setNotice("");
  }
  async function fetchModels(value: Draft) {
    clearTimeout(modelTimer.current);
    modelRequest.current?.abort();
    const controller = new AbortController();
    modelRequest.current = controller;
    if (!value.base_url) {
      setModelsBusy(false);
      setModelsNotice("请先填写 API 地址，无需保存或选择模型。");
      return;
    }
    setModelsBusy(true);
    setModelsNotice("");
    try {
      const result = await api<{ models: string[]; detail: string }>(
        "/agent/settings/models",
        "POST",
        value,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setModels(result.models);
        setModelsNotice(
          result.models.length
            ? result.detail
            : "服务商返回的模型列表为空，可以手动填写模型 ID。",
        );
      }
    } catch (e) {
      if (!controller.signal.aborted)
        setModelsNotice(`${(e as Error).message}；也可手动填写模型 ID。`);
    } finally {
      if (modelRequest.current === controller) setModelsBusy(false);
    }
  }
  useEffect(
    () => () => {
      clearTimeout(modelTimer.current);
      modelRequest.current?.abort();
    },
    [],
  );

  return (
    <section className="settings-section ai-settings">
      <h2>AI 助手</h2>
      <p>
        连接支持工具调用的 OpenAI
        兼容服务，识别歌单图片还需模型支持图片输入。配置可先保存，测试和获取模型直接使用当前填写内容。
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
          ref={form}
          onChange={(e) => {
            const target = e.target;
            if (
              !(target instanceof HTMLInputElement) &&
              !(target instanceof HTMLSelectElement)
            )
              return;
            const { name } = target;
            if (
              ![
                "base_url",
                "api_type",
                "proxy_mode",
                "api_key",
                "clear_key",
              ].includes(name)
            )
              return;
            clearTimeout(modelTimer.current);
            modelRequest.current?.abort();
            setModelsBusy(false);
            setModels([]);
            setModelsNotice("");
            const value = draft();
            if (!value.base_url || value.clear_key) return;
            try {
              new URL(value.base_url);
            } catch {
              return;
            }
            modelTimer.current = setTimeout(() => void fetchModels(value), 800);
          }}
          onSubmit={async (e) => {
            e.preventDefault();
            const value = draft();
            setBusy(true);
            setError("");
            setNotice("");
            try {
              const saved = await api<Settings>(
                "/agent/settings",
                "PUT",
                value,
              );
              setConfig(saved);
              setKey("");
              setClearKey(false);
              setNotice(
                saved.base_url && saved.model
                  ? "AI 配置已保存"
                  : "AI 配置已保存；补全 API 地址和模型后即可使用。",
              );
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
                name="enabled"
                type="checkbox"
                checked={config.enabled}
                onChange={(e) => update("enabled", e.target.checked)}
              />
              启用 AI 助手
            </label>
            <label>
              API 基础地址
              <input
                name="base_url"
                type="url"
                placeholder="https://api.example.com/v1"
                value={config.base_url}
                onChange={(e) => update("base_url", e.target.value)}
              />
            </label>
            <small>
              支持带自定义路径的基础地址，也可粘贴完整的 /chat/completions 或
              /responses 地址；请求按下方接口类型发送。
            </small>
            <div className="settings-grid">
              <label>
                接口类型
                <select
                  name="api_type"
                  aria-label="接口类型"
                  value={config.api_type}
                  onChange={(e) =>
                    update("api_type", e.target.value as Settings["api_type"])
                  }
                >
                  <option value="chat_completions">Chat Completions</option>
                  <option value="responses">Responses</option>
                </select>
              </label>
              <label>
                AI 请求代理
                <select
                  name="proxy_mode"
                  aria-label="AI 请求代理"
                  value={config.proxy_mode}
                  onChange={(e) =>
                    update(
                      "proxy_mode",
                      e.target.value as Settings["proxy_mode"],
                    )
                  }
                >
                  <option value="direct">直连</option>
                  <option value="project">使用项目代理</option>
                </select>
              </label>
            </div>
            <small>
              {config.proxy_mode === "project"
                ? config.project_proxy_configured
                  ? "使用「音源与下载」已配置的项目代理，获取模型、测试和对话均生效。"
                  : "项目代理尚未配置，请先在「音源与下载」填写代理地址。"
                : "由运行 MeloKeep 的服务器直接连接模型服务。"}
            </small>
            <label>
              API Key
              <input
                name="api_key"
                type="password"
                autoComplete="new-password"
                value={key}
                disabled={clearKey}
                placeholder={
                  config.key_configured
                    ? "已配置，留空保留"
                    : "本地无鉴权服务可留空"
                }
                onChange={(e) => {
                  setKey(e.target.value);
                  setError("");
                  setNotice("");
                }}
              />
            </label>
            {config.key_configured && (
              <label className="ready-filter">
                <input
                  name="clear_key"
                  type="checkbox"
                  checked={clearKey}
                  onChange={(e) => setClearKey(e.target.checked)}
                />
                清除已保存的密钥
              </label>
            )}
            <div className="ai-actions">
              <button
                type="button"
                className="secondary"
                disabled={modelsBusy}
                onClick={() => void fetchModels(draft())}
              >
                {modelsBusy ? "正在获取模型…" : "获取模型列表"}
              </button>
              <small>
                点击获取；修改地址、密钥、接口或代理后自动刷新，切换页面不会请求。不支持模型列表的服务可手动填写。
              </small>
            </div>
            {modelsNotice && (
              <p className="muted" aria-live="polite">
                {modelsNotice}
              </p>
            )}
            {models.length > 0 && (
              <label>
                选择可用模型
                <select
                  aria-label="选择可用模型"
                  value={models.includes(config.model) ? config.model : ""}
                  onChange={(e) => {
                    if (e.target.value) update("model", e.target.value);
                  }}
                >
                  <option value="">请选择模型，或在下方手动填写</option>
                  {models.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              模型名称
              <input
                name="model"
                placeholder="选择模型或手动填写模型 ID"
                value={config.model}
                maxLength={200}
                onChange={(e) => update("model", e.target.value)}
              />
            </label>
            <p>
              文字、图片和执行所需的歌曲资料会发送给配置的模型服务。API Key
              仅保存在服务器；测试和模型获取不会保存草稿或修改音乐。
            </p>
            <div className="ai-actions">
              <button className="primary" type="submit">
                {busy ? "正在处理…" : "保存配置"}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={async () => {
                  const value = draft();
                  if (!value.base_url || !value.model) {
                    setError("请填写 API 地址并选择或填写模型，无需先保存。");
                    return;
                  }
                  setBusy(true);
                  setError("");
                  setNotice("");
                  try {
                    setNotice(
                      (
                        await api<{ detail: string }>(
                          "/agent/settings/test",
                          "POST",
                          value,
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
                测试当前配置
              </button>
            </div>
          </fieldset>
        </form>
      )}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
