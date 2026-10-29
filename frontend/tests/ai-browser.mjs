import assert from "node:assert/strict";
import { chromium, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";

const base = "http://127.0.0.1:18767";
const server = spawn(
  process.execPath,
  [
    "node_modules/vite/bin/vite.js",
    "preview",
    "--host",
    "127.0.0.1",
    "--port",
    "18767",
  ],
  { stdio: "ignore" },
);
let browser;
try {
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(base)).ok) break;
    } catch {
      /* Server is starting. */
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.MELOKEEP_BROWSER_EXECUTABLE || undefined,
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let settings = {
    enabled: false,
    base_url: "",
    model: "",
    key_configured: false,
    api_type: "chat_completions",
    proxy_mode: "direct",
    project_proxy_configured: true,
  };
  let session = null;
  let botSettings = {
    public_url: "",
    link_ttl_seconds: 86400,
    bot_sources: "",
    tg_enabled: false,
    tg_ai_enabled: false,
    wecom_ai_enabled: false,
    bot_ai_allow_actions: true,
    tg_api_url: "https://api.telegram.org",
    tg_local_enabled: false,
    tg_local_api_id: "",
    tg_proxy_mode: "direct",
    tg_allowed_users: "",
    wecom_enabled: false,
    wecom_corp_id: "",
    wecom_agent_id: "",
    wecom_allowed_users: "",
    discord_enabled: false,
    feishu_enabled: false,
    dingtalk_enabled: false,
    configured: {},
    status: { tg: false, wecom: false },
    callback_url: "",
    local_api_status: { available: false, running: false, detail: "" },
  };
  let submitted = null;
  let finish = true;
  let getCount = 0;
  let registrations = 0;
  let testedSettings = null;
  let modelDraft = null;
  let modelRequests = 0;
  let failModels = false;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api", "");
    const method = route.request().method();
    let result = [];
    if (path === "/auth/status")
      result = { authenticated: true, required: false };
    if (path === "/config")
      result = {
        engine: "test",
        sources: ["netease"],
        available_sources: [{ id: "netease", label: "网易云" }],
        source_settings: {},
      };
    if (path === "/agent/settings") {
      if (method === "PUT") {
        const { api_key, clear_key, ...value } = route.request().postDataJSON();
        settings = {
          ...settings,
          ...value,
          key_configured: !clear_key && (!!api_key || settings.key_configured),
        };
      }
      result = settings;
    }
    if (path === "/agent/settings/test") {
      testedSettings = route.request().postDataJSON();
      result = { detail: "基础连接成功" };
    }
    if (path === "/agent/settings/models") {
      modelRequests++;
      modelDraft = route.request().postDataJSON();
      if (failModels) {
        await route.fulfill({
          status: 502,
          json: { detail: "模型列表暂不可用" },
        });
        return;
      }
      result = {
        models: ["test-vision-model", "other-model"],
        detail: "服务商返回 2 个模型，工具和图片能力需验证。",
      };
    }
    if (path === "/bots/config") {
      if (method === "PUT")
        botSettings = { ...botSettings, ...route.request().postDataJSON() };
      result = botSettings;
    }
    if (path === "/bots/discord/commands") {
      registrations++;
      result = { detail: "已注册 /melokeep 命令" };
    }
    if (path === "/agent/sessions") {
      if (method === "POST")
        session = {
          id: "test-session",
          title: "新对话",
          status: "idle",
          detail: "",
          messages: [],
          events: [],
        };
      result = method === "POST" ? session : session ? [session] : [];
    }
    if (path === "/agent/sessions/test-session/messages") {
      submitted = route.request().postDataJSON();
      session.title = submitted.message;
      session.messages.push({
        role: "user",
        content: submitted.message,
        has_image: !!submitted.image,
      });
      session.status = "running";
      session.detail = "正在搜索音乐…";
      getCount = 0;
      result = session;
    }
    if (path === "/agent/sessions/test-session") {
      if (method === "DELETE") {
        session = null;
        result = { deleted: true };
      } else {
        if (session.status === "running" && ++getCount >= 2 && finish) {
          session.status = "complete";
          session.detail = "本轮对话已完成";
          session.messages.push({
            role: "assistant",
            content: "已识别《晴天》— 周杰伦，并加入歌单「截图收藏」。",
          });
          session.events = [
            {
              tool: "search_music",
              status: "complete",
              detail: "找到 1 个候选",
              result: { tracks: [{ title: "晴天", artist: "周杰伦" }] },
            },
            {
              tool: "add_to_playlist",
              status: "complete",
              detail: "已向截图收藏加入 1 首歌曲",
            },
            {
              tool: "query_project",
              operation: "GET /api/engine/config",
              status: "complete",
              detail: "已读取项目配置",
              result: { data: { proxy_mode: "project", cookies: "[已隐藏]" } },
            },
          ];
        }
        result = session;
      }
    }
    if (path === "/agent/sessions/test-session/stop") {
      session.status = "stopped";
      session.detail = "本轮已停止";
      result = session;
    }
    await route.fulfill({ json: result });
  });
  await page.goto(base);
  const nav = page.getByRole("navigation", { name: "主导航" });
  await nav.getByRole("button", { name: "AI 助手", exact: true }).click();
  await expect(page.getByText("先连接你的 AI 模型")).toBeVisible();
  await page.getByRole("button", { name: "配置 AI 助手" }).click();
  await page.getByLabel("启用 AI 助手", { exact: true }).check();
  await page.getByRole("button", { name: "保存配置", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("补全 API 地址和模型");
  await page
    .getByLabel("API 基础地址")
    .fill("https://example.test/v1/responses");
  await page.getByLabel("接口类型", { exact: true }).selectOption("responses");
  await page.getByLabel("AI 请求代理", { exact: true }).selectOption("project");
  await page.getByLabel("API Key", { exact: true }).fill("browser-test-secret");
  await expect(page.getByLabel("选择可用模型", { exact: true })).toBeVisible();
  assert.equal(modelRequests, 1, "connection edits should be debounced");
  assert.equal(settings.base_url, "");
  assert.equal(modelDraft.api_key, "browser-test-secret");
  assert.equal(modelDraft.proxy_mode, "project");
  await page
    .getByLabel("选择可用模型", { exact: true })
    .selectOption("test-vision-model");
  await page.getByRole("button", { name: "测试当前配置", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("基础连接成功");
  assert.equal(testedSettings.base_url, "https://example.test/v1/responses");
  assert.equal(testedSettings.model, "test-vision-model");
  assert.equal(testedSettings.api_type, "responses");
  assert.equal(testedSettings.proxy_mode, "project");
  assert.equal(testedSettings.api_key, "browser-test-secret");
  assert.equal(settings.base_url, "");
  failModels = true;
  await page.getByRole("button", { name: "获取模型列表", exact: true }).click();
  await expect(
    page.getByText("模型列表暂不可用；也可手动填写模型 ID。", { exact: true }),
  ).toBeVisible();
  failModels = false;
  await page.getByRole("button", { name: "获取模型列表", exact: true }).click();
  await expect(
    page.getByText("服务商返回 2 个模型，工具和图片能力需验证。", {
      exact: true,
    }),
  ).toBeVisible();
  // Reproduce autofill without an input event: saving must read the actual form value.
  await page.getByLabel("模型名称", { exact: true }).evaluate((input) => {
    input.value = "autofill-vision-model";
  });
  await page.getByRole("button", { name: "保存配置", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("AI 配置已保存");
  assert.equal(settings.model, "autofill-vision-model");
  assert.equal(settings.api_type, "responses");
  assert.equal(settings.proxy_mode, "project");
  await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "测试当前配置", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("基础连接成功");
  const requestsAfterSave = modelRequests;
  await page.waitForTimeout(1100);
  assert.equal(
    modelRequests,
    requestsAfterSave,
    "saving must not fetch models",
  );
  for (let i = 0; i < 2; i++) {
    await page.getByRole("tab", { name: "通知与机器人", exact: true }).click();
    await page.getByRole("tab", { name: "AI 助手", exact: true }).click();
    await expect(page.getByLabel("API 基础地址")).toHaveValue(
      settings.base_url,
    );
    await page.waitForTimeout(1100);
    assert.equal(
      modelRequests,
      requestsAfterSave,
      "reopening must not fetch models",
    );
  }
  await page.getByRole("button", { name: "获取模型列表", exact: true }).click();
  await expect(page.getByLabel("选择可用模型", { exact: true })).toBeVisible();
  assert.equal(
    modelRequests,
    requestsAfterSave + 1,
    "manual fetching still works",
  );
  await mkdir("../output", { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1800 });
    await page.evaluate(() => window.scrollTo(0, 0));
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await page
      .locator(".ai-settings")
      .screenshot({ path: `../output/ai-model-settings-${width}.png` });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await nav.getByRole("button", { name: "AI 助手", exact: true }).click();
  await page
    .getByRole("button", {
      name: "把图片上的歌曲加入歌单「截图收藏」",
      exact: true,
    })
    .click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "playlist.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1kAAAAASUVORK5CYII=",
      "base64",
    ),
  });
  await expect(page.getByAltText("待发送的歌单截图")).toBeVisible();
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("button", { name: "停止本轮" })).toBeVisible();
  await expect(page.getByLabel("告诉助手你想做什么")).toBeDisabled();
  await expect(
    page.getByText("已识别《晴天》— 周杰伦，并加入歌单「截图收藏」。"),
  ).toBeVisible();
  assert.equal(submitted.allow_actions, true);
  assert.ok(submitted.image.startsWith("data:image/png;base64,"));
  await page.locator(".ai-event").first().locator("summary").click();
  await expect(
    page.locator(".ai-result-list").getByText("晴天", { exact: true }),
  ).toBeVisible();
  await page
    .locator(".ai-event")
    .filter({ hasText: "查询项目" })
    .locator("summary")
    .click();
  await expect(
    page.getByText("GET /api/engine/config", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".ai-event pre")).toContainText("proxy_mode");
  await mkdir("../output", { recursive: true });
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    for (const width of [1440, 390]) {
      await page.setViewportSize({
        width,
        height: width === 1440 ? 1000 : 844,
      });
      assert.ok(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        `horizontal overflow at ${width}`,
      );
      await page.screenshot({
        path: `../output/ai-assistant-${theme}-${width}.png`,
        fullPage: true,
      });
    }
  }
  await page.reload();
  await nav.getByRole("button", { name: "AI 助手", exact: true }).click();
  await expect(
    page.getByText("已识别《晴天》— 周杰伦，并加入歌单「截图收藏」。"),
  ).toBeVisible();
  finish = false;
  await page.getByLabel("允许本轮执行项目操作").uncheck();
  await page.getByLabel("告诉助手你想做什么").fill("只查询任务状态");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("button", { name: "停止本轮" })).toBeVisible();
  assert.equal(submitted.allow_actions, false);
  await page.getByRole("button", { name: "停止本轮" }).click();
  await expect(page.getByText("本轮已停止", { exact: true })).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "删除当前 AI 对话" }).click();
  await expect(page.getByText("从一句话或一张歌单截图开始")).toBeVisible();
  await page.getByRole("button", { name: "模型设置", exact: true }).click();
  await page.getByRole("tab", { name: "通知与机器人", exact: true }).click();
  await page.getByLabel("Telegram 使用 AI 对话", { exact: true }).check();
  await page.getByLabel("企业微信使用 AI 对话", { exact: true }).check();
  for (const label of ["飞书 / Lark", "钉钉", "Discord"]) {
    await expect(
      page.getByLabel(`${label} 使用 AI 对话`, { exact: true }),
    ).not.toBeChecked();
    await page.getByLabel(`${label} 使用 AI 对话`, { exact: true }).check();
  }
  await page.getByLabel("允许渠道 AI 执行操作", { exact: true }).uncheck();
  await page.getByRole("button", { name: "保存通知配置", exact: true }).click();
  await expect(
    page.getByText("通知渠道已保存并立即生效，无需重启服务"),
  ).toBeVisible();
  assert.equal(botSettings.tg_ai_enabled, true);
  assert.equal(botSettings.wecom_ai_enabled, true);
  assert.equal(botSettings.bot_ai_allow_actions, false);
  assert.equal(botSettings.feishu_ai_enabled, true);
  assert.equal(botSettings.dingtalk_ai_enabled, true);
  assert.equal(botSettings.discord_ai_enabled, true);
  assert.equal(botSettings.feishu_enabled, false);
  assert.equal(botSettings.dingtalk_enabled, false);
  assert.equal(botSettings.discord_enabled, false);
  assert.equal(registrations, 0);
  const channelSettings = page.locator(".settings-section").filter({
    has: page.getByRole("heading", { name: "渠道 AI 对话", exact: true }),
  });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await channelSettings.scrollIntoViewIfNeeded();
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await channelSettings.screenshot({
      path: `../output/ai-channel-settings-${width}.png`,
    });
  }
  await page
    .getByLabel("公网访问地址", { exact: true })
    .fill("https://music.example.com");
  const appBots = page.locator(".settings-section").filter({
    has: page.getByRole("heading", { name: "更多对话机器人", exact: true }),
  });
  for (const label of ["飞书 / Lark", "钉钉", "Discord"]) {
    await appBots
      .locator("summary")
      .getByText(`${label} 对话机器人`, { exact: true })
      .click();
    await page.getByLabel(`启用 ${label} 对话机器人`, { exact: true }).check();
  }
  await page.getByLabel("飞书 App ID", { exact: true }).fill("cli_test");
  await page
    .getByLabel("飞书 App Secret", { exact: true })
    .fill("feishu-app-secret");
  await page
    .getByLabel("飞书 Verification Token", { exact: true })
    .fill("verify-token");
  await page
    .getByLabel("飞书 Encrypt Key", { exact: true })
    .fill("encrypt-key");
  await page
    .getByLabel("飞书 / Lark 对话用户白名单（必填）", { exact: true })
    .fill("ou_alice");
  await page
    .getByLabel("钉钉 Client ID / AppKey", { exact: true })
    .fill("ding-client");
  await page
    .getByLabel("钉钉 Client Secret / AppSecret", { exact: true })
    .fill("ding-secret");
  await page.getByLabel("钉钉 Robot Code", { exact: true }).fill("ding-robot");
  await page
    .getByLabel("钉钉 对话用户白名单（必填）", { exact: true })
    .fill("alice");
  await page.getByLabel("Discord Application ID", { exact: true }).fill("100");
  await page
    .getByLabel("Discord Public Key", { exact: true })
    .fill("a".repeat(64));
  await page
    .getByLabel("Discord Bot Token", { exact: true })
    .fill("discord-bot-secret");
  await page
    .getByLabel("Discord 对话用户白名单（必填）", { exact: true })
    .fill("123");
  await expect(
    page.getByLabel("飞书 / Lark 消息回调地址", { exact: true }),
  ).toHaveValue("https://music.example.com/bot/feishu");
  await expect(
    page.getByRole("button", {
      name: "注册 Discord /melokeep 命令",
      exact: true,
    }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "保存通知配置", exact: true }).click();
  await expect(
    page.getByText("通知渠道已保存并立即生效，无需重启服务"),
  ).toBeVisible();
  assert.equal(botSettings.feishu_bot_enabled, true);
  assert.equal(botSettings.dingtalk_bot_enabled, true);
  assert.equal(botSettings.discord_bot_enabled, true);
  assert.equal(botSettings.feishu_enabled, false);
  assert.equal(botSettings.feishu_app_secret, "feishu-app-secret");
  assert.equal(registrations, 0);
  await page
    .getByRole("button", { name: "注册 Discord /melokeep 命令", exact: true })
    .click();
  await expect(
    page.getByText("已注册 /melokeep 命令", { exact: true }),
  ).toBeVisible();
  assert.equal(registrations, 1);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await appBots.screenshot({
      path: `../output/app-bot-settings-${width}.png`,
    });
  }
  assert.deepEqual(errors, []);
  console.log(
    "AI browser checks passed: model/channel configuration, screenshot, tool results, read-only mode, stop, history, delete, desktop/mobile light/dark layouts.",
  );
} finally {
  await browser?.close();
  server.kill();
}
