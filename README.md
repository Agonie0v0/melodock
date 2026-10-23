# musicdl

**面向 NAS 与自托管场景的音乐搜索、在线试听、歌单管理与批量下载中心。**  
支持桌面端与移动端自适应界面，支持在线播放、同步歌词、断点续传下载与本地曲库管理，原生集成 **Telegram 2000 MB 本地大文件直传** 与企业微信交互式下载。

[NAS / Docker 部署](#nas--docker-快速部署) · [网页配置指南](#网页配置指南) · [Telegram 2000MB 大文件直传](#telegram-local-bot-api-server2000-mb-大文件直传) · [环境变量与权限](#环境变量与-nas-目录权限) · [进阶文档](docs/configuration.md)

---

## 核心特性

- **音乐搜索与沉浸式试听**
  - 采用双栏清爽工作台布局（支持浅色 / 深色主题及移动端适配）。
  - 支持按音质筛选搜索结果、在线试听、实时时间轴同步歌词（LRC 滚动高亮与点击跳转）以及多音质版本切换。
- **歌单、收藏与待播队列**
  - 内置**待播列表**、**我的收藏**与**我的歌单**，支持导入外部歌单链接，或将搜索结果与当前播放曲目一键加入自定义歌单。
- **断点续传下载与本地曲库管理**
  - 支持单曲与批量勾选下载、暂停/继续（HTTP Range 断点续传）、同名自动去重保护及同步保存 `.lrc` 歌词。
  - 内置**本地曲库**管理面板，支持在线回放已下载音频、查看音频参数、编辑元数据标签（ID3 / Vorbis Comment）及清理磁盘文件。
- **Telegram / 企业微信交互式机器人 & 群通知**
  - 私聊发送关键词即可搜索、翻页、点选编号下载，下载完成后直接推送音频原文件（`MP3` / `M4A` / `FLAC`）或签名下载链接。
  - Docker 镜像已**内置官方 `telegram-bot-api`（`--local` 模式）**，单文件直传上限从 50 MB 提升至 **2000 MB**。
  - 支持 **飞书、钉钉、Discord** 群 Webhook 下载完成/失败通知（支持加签校验）。
- **统一代理路由**
  - 在网页配置一次 HTTP / HTTPS 代理地址，即可分别控制搜索请求与 Telegram 机器人是否使用代理。
- **下载后刮削、整理与 Navidrome**
  - 设置中独立启用自动刮削及整理入库，补全标签、歌词与封面，按模板归档；歧义候选进入人工确认。
  - 已有音乐支持批量编辑、差异预览、文件名提取、文本清理、重复文件检查和历史恢复。
  - 浏览、搜索与播放 Navidrome 的专辑和歌曲，整理后可触发服务器扫描。无需部署 Music Tag 服务，见 [音乐库使用说明](docs/music-library.md)。

---

## NAS / Docker 快速部署

镜像托管于 GitHub Container Registry（`ghcr.io/agonie0v0/musicdl:latest`），原生支持 **`linux/amd64`**（群晖、威联通、飞牛 fnOS、Unraid、软路由、x86 服务器）与 **`linux/arm64`**（ARM NAS、树莓派、Apple Silicon），已内置 `FFmpeg` 与官方 `telegram-bot-api`。

### 1. 创建 `docker-compose.yml`

在 NAS 或服务器上新建部署目录（例如 `/volume1/docker/musicdl` 或 `/opt/musicdl`），保存以下 `docker-compose.yml` 并修改 `MUSICDL_PASS` 登录密码：

```yaml
services:
  musicdl-webui:
    container_name: musicdl
    image: ghcr.io/agonie0v0/musicdl:latest
    restart: unless-stopped
    init: true
    ports:
      - "8765:8765"
    volumes:
      - ./music:/music
      - ./data:/data
    environment:
      MUSICDL_USER: admin
      MUSICDL_PASS: '请改成你自己的强密码'
      # 如 NAS 共享目录要求指定读写用户的 UID/GID，取消下方注释并修改（可在 SSH 执行 id 用户名 查看）：
      # PUID: '1000'
      # PGID: '1000'
```

> **提示**：若密码中包含 `$` 字符，在 `docker-compose.yml` 中请写成 `$$` 防止被 Compose 变量替换。

### 2. 启动与更新容器

```sh
mkdir -p music data
docker compose up -d
```

启动后浏览器访问 **`http://NAS或服务器IP:8765`**，使用配置的账号密码登录即可（无需配置可信域名白名单，支持局域网 IP、DDNS 域名或反向代理直接访问）。

| 挂载目录 | 容器内路径 | 持久化内容（升级镜像时请保留） |
| --- | --- | --- |
| `./music` | `/music` | 下载完成的音频文件与同名 `.lrc` 歌词 |
| `./data` | `/data` | `config.json` 配置、`musicdl.db` 数据库（歌单/收藏/下载队列）、Telegram 本地服务数据 |

**日常拉取最新镜像并平滑升级：**

```sh
docker compose pull
docker compose up -d
docker compose logs -f --tail 100
```

---

## 网页配置指南

### 1. 搜索、下载与代理设置
1. 点击顶部导航栏 **设置**，可调整下载目录、返回数量、请求超时与下载偏好。
2. **统一项目代理**：在 **项目代理** 中填写一次 HTTP / HTTPS 代理地址（如 `http://192.168.1.2:7890`），可按需设置代理作用范围，并在机器人设置中勾选是否让 Telegram 复用该代理。
   > 注意：Docker 容器内的 `127.0.0.1` 指向容器自身，代理地址请填写宿主机局域网 IP 或旁路由 IP。

### 2. 机器人与下载通知（Telegram / 企业微信 / 飞书 / 钉钉 / Discord）
1. 打开顶部 **通知与机器人**，填写手机或群成员可访问的 **外部访问地址**（如 `http://192.168.1.20:8765` 或 `https://music.example.com`，用于大文件超限回退签名下载链接）。
2. **Telegram 机器人**：填写 [@BotFather](https://t.me/BotFather) 颁发的 `Bot Token` 与允许使用的**数字用户 ID 白名单**（多个用逗号分隔），支持未保存状态下一键测试连接。
3. **企业微信自建应用**：填写 `CorpID`、`AgentID`、`Secret`、回调 `Token` 与 `EncodingAESKey`，并将企业微信后台接收消息地址设为 `https://你的域名/bot/wecom`（详见[进阶配置指南](docs/configuration.md#企业微信)）。
4. **群 Webhook 通知**：在「更多下载通知渠道」中填写飞书、钉钉或 Discord 群 Webhook 地址（飞书/钉钉支持加签密钥），自动推送下载完成、失败及签名下载链接。

---

## Telegram Local Bot API Server（2000 MB 大文件直传）

Telegram 官方云端 Bot API 的单文件上传上限为 **50 MB**。  
本项目的 Docker 镜像已**内置官方编译的 `telegram-bot-api` 程序**，开启 `--local` 模式后可将单文件直传上限提升至 **2000 MB**，无需额外部署容器或映射 `8081` 端口。

### 第一步：获取 Telegram API ID 与 API Hash
1. 使用你的 Telegram 账号登录 [https://my.telegram.org](https://my.telegram.org)。
2. 点击 **API development tools**（首次进入按提示填写应用名称即可创建）。
3. 复制页面中的 **`api_id`**（纯数字正整数）和 **`api_hash`**（32 位十六进制字符串）。

### 第二步：在网页中一键开启内置大文件服务
1. 打开 **通知与机器人 → Telegram**，填好 `Bot Token`、数字用户 ID 白名单并勾选启用 Telegram。
2. 勾选 **使用内置 Telegram 本地服务（大文件上传）**，填入刚才获取的 **Telegram API ID** 和 **Telegram API Hash**。
3. 点击 **保存配置**。保存后，容器会在后台自动拉起官方 `telegram-bot-api --local` 进程并监听容器回环 `127.0.0.1:8081`（数据持久化在 `./data/telegram-bot-api`）。
4. 保存完成后再次点击 **测试连接**，验证 `getMe` 成功后即可直接向机器人发送关键词搜歌并接收大文件音频。

---

## 环境变量与 NAS 目录权限

### 常用环境变量一览

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MUSICDL_USER` / `MUSICDL_PASS` | 无（Docker 必填） | Web 登录账号与密码，非本机回环访问时必须同时设置 |
| `PUID` / `PGID` | `10001` / `10001` | 容器内运行进程的 UID / GID，适配群晖、威联通、飞牛等 NAS 共享目录权限 |
| `MUSICDL_COOKIE_SECURE` | `0` | HTTP 访问保持 `0`；若仅通过 HTTPS 反向代理访问可设为 `1` |
| `MUSICDL_MAX_DOWNLOAD_TASKS` | `2` | 同时进行的下载任务并发数（`1` ~ `4`） |
| `MUSICDL_SEARCH_WORKERS` | `4` | 并行搜索子进程上限（`1` ~ `6`，低内存 NAS 可设为 `2`） |
| `MUSICDL_SEARCH_BUDGET` | `120` | 单次搜索总超时预算（秒） |

### NAS 目录权限排障（`Permission denied`）
- 容器启动脚本 [`docker-entrypoint.py`](docker-entrypoint.py) 默认以 root 初始化 `/data` 与 `/music` 目录权限后，自动降权切换至 `PUID:PGID`（默认 `10001:10001`）运行服务。
- 若你在 NAS 上挂载的是已有 SMB/NFS 共享媒体库且限制了特定用户读写，请在 NAS 终端执行 `id 你的NAS用户名` 查出实际 `UID` 和 `GID`，填入 `docker-compose.yml` 的 `PUID` 和 `PGID` 后执行 `docker compose up -d` 即可。

---

## 本机源码运行与开发检查

本机直接从源码运行需要 **Python 3.11+** 与 **Node.js 24+**（建议安装 `ffmpeg`）：

- **Windows**：双击 `start.bat`（或执行 `python app.py`）
- **Linux / macOS**：执行 `sh start.sh`

启动后默认访问 `http://127.0.0.1:8765`。完整开发与自动化测试命令见 [docs/configuration.md](docs/configuration.md#开发检查)。

## 致谢与许可

- 核心搜索与下载基于上游开源引擎 [CharlesPikachu/musicdl](https://github.com/CharlesPikachu/musicdl)（采用 **PolyForm Noncommercial 1.0.0** 许可）。
- 完整许可声明请参阅 [NOTICE.md](NOTICE.md)、[LICENSE-musicdl-reference](LICENSE-musicdl-reference) 与 [LICENSE-musicsquare](LICENSE-musicsquare)。
