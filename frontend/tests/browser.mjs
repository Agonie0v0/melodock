import assert from "node:assert/strict";
import { chromium, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
const base = "http://127.0.0.1:18766";
const server = spawn(
  process.execPath,
  [
    "node_modules/vite/bin/vite.js",
    "preview",
    "--host",
    "127.0.0.1",
    "--port",
    "18766",
  ],
  { stdio: "ignore" },
);
let browser;
try {
  for (let i = 0; i < 50; i++) {
    try {
      if ((await fetch(base)).ok) break;
    } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.MELOKEEP_BROWSER_EXECUTABLE || undefined,
  });
  const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
      timezoneId: "Asia/Shanghai",
    }),
    errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("**/test-cover-missing.png", (route) =>
    route.fulfill({ status: 404, body: "" }),
  );
  await page.route("**/test-cover.svg", (route) =>
    route.fulfill({
      status: 200,
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="480"><rect width="480" height="480" fill="#4b477b"/><circle cx="240" cy="220" r="145" fill="#c4b2e3"/><circle cx="240" cy="220" r="90" fill="#68628e"/><circle cx="240" cy="220" r="12" fill="#4b477b"/><text x="40" y="420" fill="#fff" font-family="sans-serif" font-size="32">测试专辑 / TEST FIXTURE</text></svg>',
    }),
  );
  const track = {
    id: "test-1",
    source: "netease",
    source_id: "1",
    title: "测试曲目",
    artist: "测试歌手",
    album: "测试专辑",
    duration: 8,
    size_bytes: 31457280,
    cover: `${base}/test-cover-missing.png`,
    qualities: [
      {
        id: "lossless",
        label: "FLAC 无损",
        codec: "flac",
        bitrate: null,
        lossless: true,
        availability: "advertised",
        evidence: "source",
      },
      {
        id: "standard",
        label: "MP3 128",
        codec: "mp3",
        bitrate: 128,
        lossless: false,
        availability: "advertised",
        evidence: "source",
      },
    ],
    playback: {
      state: "ready",
      url: "/api/stream/test-1",
      codec: "wav",
      bitrate: null,
      detail: null,
      preview_only: false,
    },
  };
  const cfg = {
    engine: "MeloKeep test fixture",
    available_sources: [
      { id: "netease", label: "网易云" },
      { id: "migu", label: "咪咕" },
      { id: "qq", label: "QQ音乐" },
      { id: "kuwo", label: "酷我" },
      { id: "qianqian", label: "千千" },
      { id: "GDStudioMusicClient", label: "GDStudio" },
      { id: "YouTubeMusicClient", label: "YouTube", proxy_recommended: true },
      { id: "SpotifyMusicClient", label: "Spotify", proxy_recommended: true },
    ],
    sources: ["netease", "migu", "qq", "kuwo", "qianqian"],
    results_per_source: 3,
    search_timeout_seconds: 15,
    playback_timeout_seconds: 6,
    download_concurrency: 2,
    download_layout: "artist_album",
    lyrics_mode: "both",
    embed_metadata: true,
    source_settings: {},
  };
  let engineConfig = {
    music_sources: [
      "NeteaseMusicClient",
      "MiguMusicClient",
      "QQMusicClient",
      "KuwoMusicClient",
      "QianqianMusicClient",
    ],
    global_client_cfg: {
      work_dir: "/music",
      search_size_per_source: 3,
      search_size_per_page: 10,
      max_retries: 3,
      strict_limit_search_size_per_page: true,
      enable_search_curl_cffi: false,
      enable_parse_curl_cffi: false,
      enable_download_curl_cffi: false,
      random_update_ua: false,
      auto_set_proxies: false,
      maintain_session: false,
      default_parse_cookies: { preserve: "yes" },
    },
    proxy_url: "",
    proxy_scope: "all",
    proxy_sources: [],
    request_timeout: 15,
    lazy_search: false,
    default_threads: 10,
    download_layout: "artist_album",
    lyrics_mode: "both",
    cookies: { MiguMusicClient: { fixture: "keep" } },
    init_music_clients_cfg: { MiguMusicClient: { maintain_session: true } },
    clients_threadings: { MiguMusicClient: 7 },
    requests_overrides: {
      MiguMusicClient: { headers: { "X-Custom": "keep" } },
    },
    search_rules: { MiguMusicClient: { quality: "keep" } },
  };
  let engineSaves = 0;
  let engineSourceErrors = {};
  let logFetches = 0;
  const logEntries = [
    {
      id: 1,
      time: "2026-10-10T06:00:00+00:00",
      level: "info",
      category: "search",
      task_id: "search-fixture",
      message: "网易云搜索完成，5 个结果",
    },
    {
      id: 2,
      time: "2026-10-10T06:00:01+00:00",
      level: "error",
      category: "download",
      task_id: "download-fixture",
      message:
        "HTTP 403：下载被音源拒绝\nTraceback: provider.py line 42\n请检查音源配置",
    },
  ];
  let favorites = [],
    playlist = [],
    jobs = [],
    savedPlaylists = [];
  let localTrack = {
    ...track,
    id: "local-fixture",
    source: "local",
    title: "本地测试音乐",
    artist: "本地歌手",
    album: "本地专辑",
    cover: null,
    qualities: [],
    playback: { ...track.playback, url: "/api/files/audio?path=fixture-a.wav" },
  };
  let libraryFiles = [
    {
      path: "fixture-a.wav",
      name: "测试音乐.wav",
      size: 1024,
      root: "/music",
      folder: "通勤",
      track: localTrack,
      editable: true,
    },
    {
      path: "fixture-b.lrc",
      name: "测试歌词.lrc",
      size: 128,
      root: "/music",
      folder: "通勤",
    },
  ];
  const wav = Buffer.alloc(44 + 8000 * 2 * 8);
  wav.write("RIFF");
  wav.writeUInt32LE(wav.length - 8, 4);
  wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20);
  wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(8000, 24);
  wav.writeUInt32LE(16000, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write("data", 36);
  wav.writeUInt32LE(wav.length - 44, 40);
  const playbackReports = [];
  let versionRequests = 0;
  let brokenAudio = false;
  let botConfig = {
    public_url: "",
    link_ttl_seconds: 86400,
    bot_sources: "",
    tg_enabled: false,
    tg_api_url: "https://api.telegram.org",
    tg_proxy_mode: "direct",
    wecom_enabled: false,
    tg_allowed_users: "",
    wecom_corp_id: "",
    wecom_agent_id: "",
    wecom_allowed_users: "",
    configured: {},
    status: { tg: false, wecom: false },
    callback_url: "",
  };
  let botSaves = 0;
  let libraryConfig = {
    metadata_sources: [
      {
        id: "netease",
        label: "网易云",
        description: "中文歌曲与歌词",
        fields: ["title", "lyrics"],
        note: "复用 Cookie 与代理",
        url: "https://music.163.com/",
      },
      {
        id: "qq",
        label: "QQ音乐",
        description: "中文专辑与歌词",
        fields: ["title", "lyrics"],
        note: "复用 Cookie 与代理",
        url: "https://y.qq.com/",
      },
      {
        id: "musicbrainz",
        label: "MusicBrainz",
        description: "国际音乐与发行版本",
        fields: ["album_artist", "cover"],
        note: "封面来自 Cover Art Archive，不提供歌词",
        url: "https://musicbrainz.org/",
      },
      ...[
        ["migu", "咪咕音乐"],
        ["kugou", "酷狗音乐"],
        ["kuwo", "酷我音乐"],
        ["acoustid", "AcoustID 指纹"],
      ].map(([id, label]) => ({
        id,
        label,
        description: "额外元数据来源",
        fields: ["title", "album"],
        note: "依来源实际返回为准",
        url: "https://example.com/",
      })),
    ],
    auto_scrape: false,
    auto_organize: false,
    library_dir: "library",
    file_root: "/music",
    folder_template: "{album_artist}/{album}",
    filename_template: "{track_number} - {title}",
    sources: ["netease", "qq"],
    overwrite: false,
    lyrics_mode: "both",
    cover_mode: "both",
    fields: [
      "title",
      "artist",
      "album",
      "album_artist",
      "date",
      "track_number",
      "disc_number",
      "genre",
      "composer",
      "comment",
    ],
    backup_days: 7,
    watch_enabled: false,
    watch_dirs: ["incoming"],
    watch_failure_dir: "",
    watch_interval: 180,
    watch_stable_seconds: 30,
    watch_action: "both",
    watch_apply: true,
    chinese: "none",
    repair_encoding: false,
    tools: { ffmpeg: true, fpcalc: true },
    has_acoustid_key: false,
    navidrome: {
      enabled: false,
      url: "",
      username: "",
      auto_scan: false,
      has_password: false,
      has_api_key: false,
    },
  };
  const libraryJobs = [];
  let lastLibraryBody;
  const remoteTrack = {
    ...localTrack,
    id: "navidrome-s",
    source: "navidrome",
    source_id: "s",
    title: "远程歌曲",
    cover: `${base}/test-cover.svg`,
    playback: { ...localTrack.playback, url: "/api/navidrome/stream/s" },
  };
  let remotePlaylistTracks = [remoteTrack];
  let remoteLyrics =
    "[00:00.000]音乐库歌词第一句\n[00:02.250]音乐库歌词第二句\n[00:05.001]音乐库歌词第三句";
  const remoteAlbum = {
    id: "album-a",
    name: "远程专辑",
    artist: "远程歌手",
    year: 2026,
    song_count: 1,
    cover: `${base}/test-cover.svg`,
  };
  const botTests = [];
  const searchRequests = [],
    cancelledSearches = [],
    searchKeywords = new Map(),
    heldSearches = new Map();
  let remoteSyncEnabled = false;
  let remoteSyncFails = false;
  let remotePlaylistName = "Navidrome 测试歌单";
  let songOffsets = [];
  let remoteWritable = false;
  let navDeleteEnabled = false;
  let navDeletes = 0;
  const remoteWrites = [];
  const remoteRevision = "a".repeat(64);
  const remoteDetail = () => ({
    id: "navidrome:p1",
    name: remotePlaylistName,
    source: "navidrome",
    read_only: !remoteWritable,
    can_manage: remoteWritable,
    revision: remoteRevision,
    source_url: "",
    created_at: 1792700000,
    tracks: remotePlaylistTracks.map((track, playlist_index) => ({
      ...track,
      playlist_index,
    })),
    issues: [],
    detail: "自动同步",
    task_id: "",
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request(),
      p = new URL(request.url()).pathname.replace("/api", ""),
      method = request.method();
    let result;
    if (p === "/auth/status") result = { authenticated: true, required: false };
    else if (p === "/auth/logout") result = { success: true };
    else if (p === "/navidrome/capabilities")
      result = { delete_songs: navDeleteEnabled };
    else if (p === "/navidrome/songs/s/deletion")
      result = {
        path: "/music/library/远程歌手/远程歌曲.wav",
        revision: remoteRevision,
      };
    else if (p === "/navidrome/songs/s" && method === "DELETE") {
      assert.equal(
        new URL(request.url()).searchParams.get("revision"),
        remoteRevision,
      );
      navDeletes++;
      result = {
        deleted: true,
        track_ids: [remoteTrack.id],
        warning: "音乐文件已删除，但扫描未启动，请手动扫描",
      };
    } else if (p === "/navidrome/playlists" && method === "POST") {
      const body = request.postDataJSON();
      remoteWrites.push({ method, body });
      remotePlaylistName = body.name;
      remotePlaylistTracks = body.song_ids.map(() => remoteTrack);
      remoteSyncEnabled = true;
      result = remoteDetail();
    } else if (p === "/navidrome/playlists") {
      if (remoteSyncFails) {
        await route.fulfill({
          status: 502,
          json: { detail: "远程连接暂时失败" },
        });
        return;
      }
      result = remoteSyncEnabled
        ? [
            {
              id: "navidrome:p1",
              name: remotePlaylistName,
              source: "navidrome",
              read_only: !remoteWritable,
              can_manage: remoteWritable,
              source_url: "",
              created_at: 1792700000,
              track_count: remotePlaylistTracks.length,
              issue_count: 0,
              cover: remoteTrack.cover,
              detail: "自动同步",
              task_id: "",
            },
          ]
        : [];
    } else if (p.startsWith("/navidrome/playlists/p1")) {
      const body =
        method === "POST" || method === "PATCH" ? request.postDataJSON() : {};
      if (method !== "GET") remoteWrites.push({ method, path: p, body });
      if (method === "DELETE") remoteSyncEnabled = false;
      if (method === "PATCH") remotePlaylistName = body.name;
      if (p.endsWith("/tracks/remove")) {
        assert.equal(body.revision, remoteRevision);
        for (const index of [...body.indexes].sort((a, b) => b - a))
          remotePlaylistTracks.splice(index, 1);
      } else if (p.endsWith("/tracks"))
        remotePlaylistTracks.push(...body.song_ids.map(() => remoteTrack));
      result = remoteDetail();
    } else if (p === "/navidrome/songs") {
      const offset = Number(new URL(request.url()).searchParams.get("offset"));
      songOffsets.push(offset);
      result = { tracks: [remoteTrack], has_more: offset === 0 };
    } else if (p === "/library/settings") {
      if (method === "PUT")
        libraryConfig = { ...libraryConfig, ...request.postDataJSON() };
      result = libraryConfig;
    } else if (p === "/library/watch/scan") {
      result = { queued: 0, detail: "已检查监控目录，正在等待文件稳定" };
    } else if (p === "/library/watch") {
      result = { checked_at: 1792700000, detail: "目录检查成功" };
    } else if (p === "/library/credentials") {
      libraryConfig.has_acoustid_key = !!request.postDataJSON().acoustid_key;
      result = { has_acoustid_key: libraryConfig.has_acoustid_key };
    } else if (p === "/library/versions") {
      result = { versions: [] };
    } else if (p === "/library/navidrome") {
      const { password, api_key, ...settings } = request.postDataJSON();
      libraryConfig.navidrome = {
        ...libraryConfig.navidrome,
        ...settings,
        has_password: !!password,
        has_api_key: !!api_key,
      };
      result = libraryConfig.navidrome;
    } else if (p === "/library/jobs") {
      if (method === "POST") {
        const body = request.postDataJSON();
        lastLibraryBody = body;
        const before = {
          title: localTrack.title,
          artist: localTrack.artist,
          album: localTrack.album,
        };
        result = {
          id: `library-${libraryJobs.length}`,
          action: body.action,
          settings: {
            sources: body.sources || libraryConfig.sources,
            overwrite: body.overwrite ?? libraryConfig.overwrite,
            fields: libraryConfig.fields,
          },
          status: "ready",
          detail: "检查完成，请预览修改后应用",
          created_at: 1792700000,
          total: 1,
          warnings: [],
          items: [
            {
              id: "local-fixture",
              name: "测试音乐.wav",
              path: "fixture-a.wav",
              original_path: "/music/通勤/测试音乐.wav",
              target:
                body.action === "edit"
                  ? "/music/通勤/测试音乐.wav"
                  : "/music/library/本地歌手/本地专辑/修改后的本地歌曲.wav",
              before,
              after: { ...before, ...body.changes },
              status: "ready",
              candidates: (body.sources || libraryConfig.sources).includes(
                "musicbrainz",
              )
                ? [
                    {
                      id: "mb-fixture",
                      source: "musicbrainz",
                      title: localTrack.title,
                      artist: localTrack.artist,
                      album: localTrack.album,
                      score: 100,
                      reasons: ["标题一致", "歌手一致", "专辑一致"],
                      conflicts: [],
                      field_sources: { lyrics: "qq" },
                    },
                  ]
                : [],
              chosen: (body.sources || libraryConfig.sources).includes(
                "musicbrainz",
              )
                ? "mb-fixture"
                : null,
              locks: [],
              warnings: [],
              ...(["convert", "split"].includes(body.action)
                ? {
                    outputs: [
                      {
                        path: "/music/通勤/测试音乐 - converted/测试音乐.flac",
                      },
                    ],
                  }
                : {}),
            },
          ],
        };
        libraryJobs.unshift(result);
      } else result = { jobs: libraryJobs, has_more: false };
    } else if (p.startsWith("/library/jobs/")) {
      const job = libraryJobs.find((job) => job.id === p.split("/")[3]);
      if (p.endsWith("/apply")) {
        job.status = "complete";
        job.detail = "已入库 1 首";
        job.items[0].status = "complete";
        job.items[0].operation_id = "op";
      }
      if (p.endsWith("/restore")) {
        job.status = "restored";
        job.detail = "已恢复原文件、标签和目录";
        job.items[0].status = "restored";
      }
      result = job;
    } else if (p === "/navidrome/albums" || p === "/navidrome/artists/artist-a")
      result = { albums: [remoteAlbum], has_more: false };
    else if (p === "/navidrome/albums/album-a")
      result = { ...remoteAlbum, tracks: [remoteTrack] };
    else if (p === "/navidrome/artists")
      result = [{ id: "artist-a", name: "远程歌手", album_count: 1 }];
    else if (p === "/navidrome/search")
      result = {
        albums: [remoteAlbum],
        tracks: [remoteTrack],
        has_more: false,
      };
    else if (p === "/navidrome/test") result = { ok: true, version: "0.60.0" };
    else if (p === "/navidrome/scan") result = { scanning: false, count: 1 };
    else if (p === "/bots/config") {
      if (method === "PUT") {
        botSaves++;
        const { clear_secrets, ...draft } = request.postDataJSON();
        if (draft.public_url && !draft.public_url.includes("://"))
          draft.public_url = "http://" + draft.public_url;
        const secretKeys = [
          "tg_token",
          "tg_proxy",
          "wecom_secret",
          "wecom_token",
          "wecom_aes_key",
        ];
        for (const key of secretKeys) {
          if (draft[key]) botConfig.configured[key] = true;
          if (clear_secrets.includes(key)) botConfig.configured[key] = false;
          delete draft[key];
        }
        botConfig = {
          ...botConfig,
          ...draft,
          status: { tg: draft.tg_enabled, wecom: draft.wecom_enabled },
          callback_url: draft.public_url + "/bot/wecom",
        };
      }
      result = botConfig;
    } else if (p === "/bots/test") {
      botTests.push(request.postDataJSON());
      result = { detail: "连接测试成功；未发送消息。" };
    } else if (p === "/playback/events") {
      const report = request.postDataJSON();
      playbackReports.push(report);
      logEntries.push({
        id: logEntries.length + 100,
        time: "2026-10-12 12:00:00",
        level: report.event === "failed" ? "error" : "info",
        category: "playback",
        task_id: report.track_id,
        message: `测试曲目 · ${report.stage} · ${report.detail} · MediaError=${report.code}`,
      });
      result = { recorded: true };
    } else if (p === "/logs") {
      logFetches++;
      result = { logs: logEntries };
    } else if (p === "/config")
      result =
        method === "PUT" ? { saved: true, restart_required: false } : cfg;
    else if (p === "/engine/config") {
      if (method === "PUT") {
        engineConfig = request.postDataJSON();
        engineSaves++;
      }
      result =
        method === "PUT"
          ? { saved: true, source_errors: engineSourceErrors }
          : engineConfig;
    } else if (p === "/favorites") result = favorites;
    else if (p.startsWith("/favorites/")) {
      favorites = method === "PUT" ? [track] : [];
      result = { saved: true };
    } else if (p === "/playlist") {
      if (method === "PUT")
        playlist = request
          .postDataJSON()
          .map((id) =>
            id === localTrack.id
              ? localTrack
              : id === remoteTrack.id
                ? remoteTrack
                : track,
          );
      result = method === "PUT" ? { saved: true } : playlist;
    } else if (p === "/playlist/import") {
      const input = request.postDataJSON();
      const list = {
        id: "collection-1",
        name: input.name || "测试歌单",
        source: "netease",
        source_url: input.id,
        created_at: 1791623400,
        tracks: [track],
        issues: [
          {
            title: "可能",
            artist: "程响",
            source_id: "1950343972",
            reason: "未获得可用音频地址，音源提示：其它版本可播。",
          },
        ],
        detail: "成功导入 1 首，1 首未获取到可用资源。",
        task_id: "collection-1",
      };
      savedPlaylists = [list];
      result = { playlist: list, tracks: list.tracks, detail: list.detail };
    } else if (p === "/playlists") {
      if (method === "POST") {
        const input = request.postDataJSON();
        const created = {
          id: `collection-custom-${savedPlaylists.length + 1}`,
          name: input.name,
          source: "custom",
          source_url: "",
          created_at: 1791623400,
          tracks: [track],
          issues: [],
          detail: `已创建歌单“${input.name}”，共 1 首曲目。`,
          task_id: "collection-custom-1",
        };
        savedPlaylists = [created, ...savedPlaylists];
        result = created;
      } else {
        result = savedPlaylists.map(({ tracks, issues, ...list }) => ({
          ...list,
          track_count: tracks.length,
          issue_count: issues.length,
          cover: tracks[0]?.cover || null,
        }));
      }
    } else if (p.startsWith("/playlists/")) {
      const list = savedPlaylists[0];
      if (p.endsWith("/tracks") && method === "POST") {
        if (!list.tracks.some((t) => t.id === track.id))
          list.tracks = [...list.tracks, track];
        list.detail = `已向歌单“${list.name}”加入 1 首曲目，共 ${list.tracks.length} 首。`;
        result = list;
      } else if (p.includes("/tracks/")) {
        list.tracks = [];
        result = list;
      } else if (method === "DELETE") {
        savedPlaylists = [];
        result = { deleted: true };
      } else if (method === "PATCH") {
        list.name = request.postDataJSON().name;
        result = list;
      } else result = list;
    } else if (p === "/downloads") {
      if (method === "POST") {
        const item = request.postDataJSON()[0];
        jobs = [
          {
            id: "job-1",
            track,
            quality_id: item.quality_id,
            quality_label: "FLAC 无损",
            status: "downloading",
            bytes: 4096,
            total_bytes: 16384,
            detail: "",
            file: null,
          },
        ];
      }
      result = jobs;
    } else if (p === "/downloads/job-1" && method === "DELETE") {
      jobs = [];
      result = { removed: true };
    } else if (p.startsWith("/downloads/job-1/")) {
      jobs[0].status = p.endsWith("/pause")
        ? "paused"
        : p.endsWith("/retry") || p.endsWith("/resume")
          ? "downloading"
          : "cancelled";
      result = jobs[0];
    } else if (p === "/search/jobs") {
      const keyword = request.postDataJSON().keyword;
      searchRequests.push(keyword);
      const id = `search-${searchRequests.length}`;
      searchKeywords.set(id, keyword);
      result = { id };
    } else if (p.endsWith("/events")) {
      const id = p.split("/")[3];
      const keyword = searchKeywords.get(id);
      if (keyword === "连接失败") {
        await route.abort();
        return;
      }
      if (keyword === "慢搜索") {
        await new Promise((resolve) => heldSearches.set(id, resolve));
      }
      const body = [
        ["source", { id: "netease", status: { state: "complete", count: 1 } }],
        [
          "candidate",
          {
            ...track,
            qualities: keyword === "候选测试" ? [] : track.qualities,
            playback: { ...track.playback, state: "pending", url: null },
          },
        ],
        ["track", track],
        ["done", { cancelled: false }],
      ]
        .filter(([kind]) => keyword !== "候选测试" || kind !== "track")
        .map(
          ([kind, data], i) =>
            `id: ${i + 1}\nevent: ${kind}\ndata: ${JSON.stringify(data)}\n\n`,
        )
        .join("");
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body,
      });
      return;
    } else if (p.endsWith("/lyrics"))
      result = {
        text: p.includes("navidrome-s")
          ? remoteLyrics
          : p.includes("local-fixture")
            ? "[00:00.000]本地歌词第一句\r[00:02.250]本地歌词第二句\r[00:05.001]本地歌词第三句"
            : "[00:00.00]测试歌词第一句\n[00:02.00]测试歌词第二句\n[00:05.00]测试歌词第三句",
      };
    else if (p.endsWith("/playback") || p.endsWith("/versions")) {
      if (p.endsWith("/versions")) versionRequests++;
      result = p.includes("local-fixture")
        ? localTrack
        : p.includes("navidrome-s")
          ? remoteTrack
          : track;
    } else if (
      p.startsWith("/stream/") ||
      p.startsWith("/navidrome/stream/") ||
      p === "/files/audio"
    ) {
      await route.fulfill({
        status: 200,
        contentType: "audio/wav",
        body: brokenAudio ? Buffer.from("invalid audio") : wav,
      });
      return;
    } else if (p === "/files/tags") {
      const tags = request.postDataJSON();
      localTrack = { ...localTrack, ...tags };
      libraryFiles[0] = { ...libraryFiles[0], track: localTrack };
      result = libraryFiles[0];
    } else if (p === "/files") {
      if (method === "DELETE") {
        const path = new URL(request.url()).searchParams.get("path");
        libraryFiles = libraryFiles.filter((file) => file.path !== path);
        result = { deleted: true };
      } else result = libraryFiles;
    } else if (p.startsWith("/search/jobs/")) {
      const id = p.split("/")[3];
      cancelledSearches.push(id);
      heldSearches.get(id)?.();
      heldSearches.delete(id);
      result = { cancelled: true };
    } else throw new Error(`Unhandled test API ${p}`);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(result),
    });
  });
  const openSettings = async (tab = "音源与下载") => {
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "设置", exact: true })
      .click();
    await page.getByRole("tab", { name: tab, exact: true }).click();
  };
  const changeTheme = async (theme) => {
    await page.getByRole("button", { name: "切换主题", exact: true }).click();
    const options = page.getByRole("group", { name: "界面主题", exact: true });
    await options
      .getByRole("button", {
        name: { system: "跟随系统", light: "浅色", dark: "深色" }[theme],
        exact: true,
      })
      .click();
    await expect(options).toBeHidden();
  };
  await page.addInitScript(() => {
    if (sessionStorage.getItem("rebrand-migration-seeded")) return;
    localStorage.setItem("musicdl-theme", "dark");
    localStorage.setItem("melodock-theme", "system");
    localStorage.setItem("musicdl-navidrome-layout", "list");
    localStorage.setItem("melodock-navidrome-mode", "artists");
    localStorage.setItem("melokeep-navidrome-mode", "songs");
    sessionStorage.setItem("rebrand-migration-seeded", "1");
  });
  await page.goto(base);
  await expect(page).toHaveTitle("MeloKeep");
  assert.deepEqual(
    await page.evaluate(() => [
      localStorage.getItem("melokeep-theme"),
      localStorage.getItem("musicdl-theme"),
      localStorage.getItem("melokeep-navidrome-layout"),
      localStorage.getItem("melodock-theme"),
      localStorage.getItem("musicdl-navidrome-layout"),
      localStorage.getItem("melodock-navidrome-mode"),
      localStorage.getItem("melokeep-navidrome-mode"),
      localStorage.getItem("melokeep-naming-version"),
    ]),
    ["system", null, "list", null, null, null, "songs", "1"],
  );
  await page.evaluate(() => {
    localStorage.removeItem("melokeep-theme");
    localStorage.setItem("musicdl-theme", "dark");
  });
  await page.reload();
  await expect(page).toHaveTitle("MeloKeep");
  await page.waitForFunction(
    () => localStorage.getItem("melokeep-theme") === "system",
  );
  await page.evaluate(() => localStorage.removeItem("musicdl-theme"));
  await page.emulateMedia({ colorScheme: "dark" });
  await page.waitForFunction(
    () => document.documentElement.dataset.theme === "dark",
  );
  await changeTheme("light");
  await page.waitForFunction(
    () => document.documentElement.dataset.theme === "light",
  );
  await mkdir("../output", { recursive: true });
  const sidebar = page.locator(".sidebar");
  await page.getByRole("button", { name: "调整导航顺序", exact: true }).click();
  await page.getByRole("button", { name: "前移音乐库", exact: true }).click();
  await expect(
    page.locator('nav[aria-label="主导航"] .nav-item').nth(3),
  ).toHaveText("音乐库");
  await page.getByRole("button", { name: "关闭导航排序", exact: true }).click();
  await page.reload();
  await expect(
    page.locator('nav[aria-label="主导航"] .nav-item').nth(3),
  ).toHaveText("音乐库");
  await page
    .getByRole("button", { name: "音乐库", exact: true })
    .dragTo(page.getByRole("button", { name: "搜索音乐", exact: true }));
  await expect(
    page.locator('nav[aria-label="主导航"] .nav-item').first(),
  ).toHaveText("音乐库");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "调整导航顺序", exact: true }).click();
  await page.getByRole("button", { name: "后移音乐库", exact: true }).click();
  await page.screenshot({
    path: "../output/test-ui-navigation-order-mobile.png",
  });
  await page.getByRole("button", { name: "恢复默认顺序", exact: true }).click();
  await page.getByRole("button", { name: "关闭导航排序", exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });

  await expect(
    sidebar.getByRole("button", { name: "歌单导入", exact: true }),
  ).toHaveCount(0);
  await expect(
    sidebar.getByRole("button", { name: "通知与机器人", exact: true }),
  ).toHaveCount(0);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await sidebar.getByRole("button", { name: "歌单", exact: true }).click();
    await expect(page.locator(".collection-tabs button")).toHaveText([
      "我的歌单 · 0",
      "我的收藏 · 0",
      "歌单导入",
    ]);
    await page.getByRole("button", { name: "歌单导入", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("歌单");
    await expect(sidebar.locator(".nav-item.active")).toHaveText("歌单");
    await expect(
      page.getByRole("heading", { name: "导入平台歌单" }),
    ).toBeVisible();
    await page.screenshot({
      path: `../output/test-ui-grouped-playlists-${width}.png`,
    });
    await sidebar.getByRole("button", { name: "音乐库", exact: true }).click();
    await expect(page.getByRole("tab")).toHaveText(["本地音乐", "Navidrome"]);
    await expect(page.getByLabel("更多音乐管理操作")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "保存曲库设置", exact: true }),
    ).toHaveCount(0);
    await page.screenshot({
      path: `../output/test-ui-grouped-library-${width}.png`,
    });
    await sidebar
      .getByRole("button", { name: "刮削整理", exact: true })
      .click();
    await expect(page.getByRole("tab")).toHaveText([
      "选择与处理",
      "任务与审核",
    ]);
    await expect(
      page.getByRole("button", { name: "保存曲库设置", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("tab", { name: "选择与处理", exact: true }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(
      page.getByRole("tab", { name: "任务与审核", exact: true }),
    ).toBeFocused();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "刮削整理",
    );
    await sidebar.getByRole("button", { name: "音乐库", exact: true }).click();
    await expect(
      page.getByRole("tab", { name: "本地音乐", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await sidebar
      .getByRole("button", { name: "刮削整理", exact: true })
      .click();
    await expect(
      page.getByRole("tab", { name: "任务与审核", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await page.getByRole("tab", { name: "选择与处理", exact: true }).click();
    await page.screenshot({
      path: `../output/test-ui-grouped-processing-${width}.png`,
    });
    await page
      .getByRole("button", { name: "前往规则设置", exact: true })
      .click();
    await expect(page.getByRole("tab")).toHaveText([
      "音源与下载",
      "刮削与归档",
      "Navidrome 连接",
      "通知与机器人",
    ]);
    await expect(page.getByRole("tab", { selected: true })).toHaveText(
      "刮削与归档",
    );
    await expect(sidebar.locator(".nav-item.active")).toHaveText("设置");
    await expect(page.getByText("启用 Navidrome", { exact: true })).toHaveCount(
      0,
    );
    await expect(page.locator(".music-table")).toHaveCount(0);
    await page.screenshot({
      path: `../output/test-ui-grouped-settings-${width}.png`,
    });
    await expect(
      page.getByRole("tab", { name: "外观", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "切换主题", exact: true }).click();
    await expect(
      page.getByRole("group", { name: "界面主题", exact: true }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      `grouped navigation overflows at ${width}`,
    );
    await sidebar
      .getByRole("button", { name: "搜索音乐", exact: true })
      .click();
    await expect(
      page.getByRole("group", { name: "界面主题", exact: true }),
    ).toBeHidden();
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: "../output/test-ui-home.png" });
  await page.getByLabel("搜索音乐", { exact: true }).fill("测试");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await page
    .getByRole("button", { name: "播放 测试曲目", exact: true })
    .waitFor();
  assert.equal(await page.locator("tbody tr").count(), 1);
  const submitSearch = async (keyword) => {
    await page.getByLabel("搜索音乐", { exact: true }).fill(keyword);
    await page.getByRole("button", { name: "搜索", exact: true }).click();
  };
  await expect(
    page.getByRole("button", { name: "停止搜索", exact: true }),
  ).toHaveCount(0);
  await submitSearch("再次搜索");
  await expect(
    page.getByRole("button", { name: "播放 测试曲目", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "停止搜索", exact: true }),
  ).toHaveCount(0);
  await submitSearch("慢搜索");
  await expect.poll(() => heldSearches.size).toBe(1);
  await submitSearch("替换搜索");
  await expect(
    page.getByRole("button", { name: "播放 测试曲目", exact: true }),
  ).toBeVisible();
  assert.ok(cancelledSearches.includes("search-3"));
  await expect(
    page.getByRole("button", { name: "停止搜索", exact: true }),
  ).toHaveCount(0);
  await submitSearch("连接失败");
  await expect(
    page.getByText("搜索连接已断开，请重新搜索", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "停止搜索", exact: true }),
  ).toHaveCount(0);
  await submitSearch("测试");
  await expect(
    page.getByRole("button", { name: "播放 测试曲目", exact: true }),
  ).toBeVisible();
  assert.deepEqual(searchRequests, [
    "测试",
    "再次搜索",
    "慢搜索",
    "替换搜索",
    "连接失败",
    "测试",
  ]);
  const beforeResolve = versionRequests;
  await submitSearch("候选测试");
  await expect(page.getByText("音质待确认", { exact: true })).toBeVisible();
  assert.equal(
    versionRequests,
    beforeResolve,
    "candidate search should not resolve audio automatically",
  );
  await page
    .getByRole("button", { name: "下载 测试曲目", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  assert.equal(versionRequests, beforeResolve + 1);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "取消", exact: true })
    .click();
  await expect(page.getByText("音质待确认", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "仅无损", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "仅无损", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("仅可试听", { exact: true })).toHaveCount(0);
  await expect(page.locator(".readiness")).toHaveCount(0);
  assert.equal(await page.locator("tbody tr").count(), 1);
  await page.getByRole("button", { name: "音质未知", exact: true }).click();
  assert.equal(await page.locator("tbody tr").count(), 0);
  await page.getByRole("button", { name: "全部", exact: true }).click();
  for (const sort of [
    "size-desc",
    "size-asc",
    "quality-desc",
    "quality-asc",
    "artist",
    "source",
    "duration-desc",
  ]) {
    await page.getByLabel("结果排序").selectOption(sort);
    assert.equal(await page.locator("tbody tr").count(), 1);
  }
  await page.getByLabel("结果排序").selectOption("relevance");
  for (const label of [
    "收藏 测试曲目",
    "播放 测试曲目",
    "下载 测试曲目",
    "加入播放列表 测试曲目",
  ])
    await expect(page.getByLabel(label, { exact: true })).toBeVisible();
  await expect(page.getByText("30.0 MB", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "播放封面 测试曲目", exact: true })
    .click();
  await expect
    .poll(() => page.locator("audio").evaluate((audio) => !audio.paused))
    .toBe(true);
  await expect(
    page.getByRole("checkbox", { name: "选择 测试曲目", exact: true }),
  ).not.toBeChecked();
  await page.locator("audio").evaluate((audio) => audio.pause());
  await page
    .getByRole("button", { name: "播放歌名 测试曲目", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  await expect
    .poll(() => page.locator("audio").evaluate((audio) => !audio.paused))
    .toBe(true);

  await page
    .getByRole("button", { name: "播放 测试曲目", exact: true })
    .click();
  await page.waitForFunction(
    () => document.querySelector("audio").currentTime > 0.05,
  );
  assert.equal(await page.locator("audio").evaluate((a) => a.error), null);
  await page.waitForFunction(
    () => document.querySelector(".mini-track img")?.style.display === "none",
  );
  track.cover = `${base}/test-cover.svg`;
  await page
    .getByRole("button", { name: "播放 测试曲目", exact: true })
    .click();
  await page.waitForFunction(() => {
    const image = document.querySelector(".mini-track img");
    return image?.naturalWidth > 0 && image.style.display !== "none";
  });
  await page.getByRole("button", { name: "正在播放", exact: true }).click();
  const fullVolume = page
    .locator(".full-player-controls")
    .getByRole("slider", { name: "音量", exact: true });
  await expect(fullVolume).toBeVisible();
  await fullVolume.fill("0.32");
  await expect
    .poll(() => page.locator("audio").evaluate((a) => a.volume))
    .toBe(0.32);
  await page
    .locator(".full-player-controls")
    .getByLabel("静音", { exact: true })
    .click();
  await expect
    .poll(() => page.locator("audio").evaluate((a) => a.volume))
    .toBe(0);
  await page
    .locator(".full-player-controls")
    .getByLabel("取消静音", { exact: true })
    .click();
  await expect
    .poll(() => page.locator("audio").evaluate((a) => a.volume))
    .toBe(0.65);
  const controlsBox = await page.locator(".full-player-controls").boundingBox();
  for (const width of [320, 390, 680, 800, 801, 1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: 1000 });
    const controls = page.locator(".full-player-controls");
    // Read one layout snapshot; viewport changes can reflow between CDP calls.
    const { panel, transport, volume } = await controls.evaluate((element) => ({
      panel: element.getBoundingClientRect().toJSON(),
      transport: element
        .querySelector(".transport")
        .getBoundingClientRect()
        .toJSON(),
      volume: element
        .querySelector(".player-extras")
        .getBoundingClientRect()
        .toJSON(),
    }));
    assert.ok(
      Math.abs(
        transport.y + transport.height / 2 - volume.y - volume.height / 2,
      ) < 2,
      `volume and playback share a row at ${width}`,
    );
    assert.ok(
      transport.x >= panel.x &&
        volume.x + volume.width <= panel.x + panel.width &&
        transport.x + transport.width <= volume.x,
      `playback controls fit without overlap at ${width}`,
    );
    assert.ok(
      volume.x - transport.x - transport.width <= 12.5 &&
        Math.abs(
          (transport.x + volume.x + volume.width) / 2 -
            panel.x -
            panel.width / 2,
        ) < 1,
      `playback and volume form a compact centered group at ${width}`,
    );
    if (width === 680)
      await controls.screenshot({
        path: "../output/test-ui-player-controls.png",
      });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  const actionBoxes = await Promise.all(
    (await page.locator(".album-actions button").all()).map((b) =>
      b.boundingBox(),
    ),
  );
  assert.ok(
    Math.abs(actionBoxes[0].x - controlsBox.x) < 1 &&
      Math.abs(
        actionBoxes[2].x +
          actionBoxes[2].width -
          controlsBox.x -
          controlsBox.width,
      ) < 1,
    "player actions align with both edges of the controls",
  );
  assert.ok(
    actionBoxes.every(
      (box) =>
        Math.abs(box.width - actionBoxes[0].width) < 1 &&
        Math.abs(box.y - actionBoxes[0].y) < 1,
    ),
    "player actions form one row of equal-width buttons",
  );
  await page.getByLabel("切换随机播放", { exact: true }).click();
  assert.ok(
    await page
      .getByLabel("切换随机播放", { exact: true })
      .evaluate((e) => e.classList.contains("active")),
  );
  await page.getByLabel("切换列表循环", { exact: true }).click();
  assert.ok(
    await page
      .getByLabel("切换列表循环", { exact: true })
      .evaluate((e) => !e.classList.contains("active")),
  );
  await page.locator(".full-lyrics button").nth(1).click();
  await page
    .waitForFunction(
      () => document.querySelector("audio").currentTime >= 1.95,
      null,
      { timeout: 3000 },
    )
    .catch(async (e) => {
      console.log(
        await page.locator("audio").evaluate((a) => ({
          time: a.currentTime,
          duration: a.duration,
          ready: a.readyState,
          error: a.error?.code,
        })),
      );
      throw e;
    });
  await page.getByLabel("调整歌词字号").click();
  assert.equal(await page.locator(".full-lyrics.large").count(), 1);
  await page.setViewportSize({ width: 2534, height: 1106 });
  const lyricColumn = await page.locator(".lyrics-column").boundingBox();
  const lineText = await page
    .locator(".full-lyrics button span")
    .nth(1)
    .boundingBox();
  assert.ok(
    Math.abs(
      lineText.x + lineText.width / 2 - (lyricColumn.x + lyricColumn.width / 2),
    ) < 12,
    "wide lyrics centered within their column",
  );
  const albumSide = await page.locator(".album-column").boundingBox();
  const fullStage = await page.locator(".playback-grid").boundingBox();
  assert.ok(
    albumSide.x > fullStage.x + 100,
    "wide album is balanced within its column",
  );
  await page.screenshot({ path: "../output/test-ui-player-ultrawide.png" });
  await page.setViewportSize({ width: 1440, height: 1000 });
  assert.equal(
    await page.getByText("点击歌词可跳转到对应位置", { exact: true }).count(),
    0,
  );
  await mkdir("../output", { recursive: true });
  await page.screenshot({ path: "../output/test-ui-player.png" });
  await changeTheme("dark");
  await page.screenshot({
    path: "../output/test-ui-player-dark.png",
    style: "#toast { visibility: hidden; }",
  });
  await changeTheme("light");
  await page.getByRole("button", { name: "收藏当前曲目", exact: true }).click();
  assert.equal(favorites.length, 1);
  await page.getByRole("button", { name: "加入播放列表", exact: true }).click();
  assert.equal(playlist.length, 1);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.screenshot({ path: "../output/test-ui-player-wide.png" });
  const stage = await page.locator(".playback-grid").boundingBox();
  const container = await page.locator(".full-player").boundingBox();
  assert.ok(
    stage.width >= container.width - 80,
    "player should use the available width",
  );
  const album = await page.locator(".album-column").boundingBox();
  const lyrics = await page.locator(".lyrics-column").boundingBox();
  const queue = await page.locator(".album-queue").boundingBox();
  assert.ok(
    album.x + album.width <= lyrics.x && lyrics.x + lyrics.width <= queue.x,
    "wide player has three aligned columns",
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "选择下载音质", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "加入下载队列", exact: true })
    .click();
  assert.equal(jobs[0].quality_id, "lossless");
  await page
    .getByRole("button", { name: /下载队列/ })
    .first()
    .click();
  const statusFixtures = ["complete", "failed", "paused"].map((status) => ({
    ...jobs[0],
    id: `filter-${status}`,
    track: { ...track, title: `筛选测试 ${status}` },
    status,
  }));
  jobs.push(...statusFixtures);
  await page.getByRole("button", { name: "刷新进度", exact: true }).click();
  await expect(page.locator(".download-row")).toHaveCount(4);
  const queueStatus = page.getByLabel("筛选下载状态");
  await queueStatus.selectOption("failed");
  await expect(page.locator(".download-row")).toHaveCount(1);
  await expect(page.locator(".download-row")).toContainText("筛选测试 failed");
  await page.getByLabel("全选下载任务").check();
  await expect(page.getByText("已选 1 项", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "继续选中", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "清理已结束记录", exact: true }),
  ).toBeDisabled();
  await queueStatus.selectOption("paused");
  await expect(page.locator(".download-row")).toHaveCount(1);
  await expect(page.getByLabel("全选下载任务")).not.toBeChecked();
  await queueStatus.selectOption("complete");
  await expect(page.locator(".download-row")).toContainText(
    "筛选测试 complete",
  );
  await page.getByLabel("全选下载任务").check();
  await expect(page.getByText("已选 1 项", { exact: true })).toBeVisible();
  await page.screenshot({ path: "../output/test-ui-queue-filter.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({ path: "../output/test-ui-queue-filter-mobile.png" });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await queueStatus.selectOption("cancelled");
  await expect(page.locator(".download-row")).toHaveCount(0);
  await expect(page.getByText(/当前没有“已取消”的任务/)).toBeVisible();
  await queueStatus.selectOption("all");
  await expect(page.getByLabel("全选下载任务")).not.toBeChecked();
  jobs.splice(1);
  await page.getByRole("button", { name: "刷新进度", exact: true }).click();
  await expect(page.locator(".download-row")).toHaveCount(1);
  await page.getByLabel("暂停下载").click();
  await page.getByRole("button", { name: "继续下载", exact: true }).waitFor();
  assert.equal(jobs[0].status, "paused");
  await page.getByRole("button", { name: "继续下载", exact: true }).click();
  assert.equal(jobs[0].status, "downloading");
  await page.getByLabel("播放封面 测试曲目", { exact: true }).click();
  await expect(
    page.getByLabel("选择下载任务 测试曲目", { exact: true }),
  ).not.toBeChecked();
  await page.locator("audio").evaluate((audio) => audio.pause());
  await page.getByLabel("播放歌名 测试曲目", { exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect
    .poll(() => page.locator("audio").evaluate((audio) => !audio.paused))
    .toBe(true);
  await page.getByLabel("全选下载任务").check();
  await page.getByRole("button", { name: "暂停选中", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "继续选中", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "继续选中", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "暂停选中", exact: true }),
  ).toBeEnabled();
  assert.equal(jobs[0].status, "downloading");
  await page.getByLabel("全选下载任务").check();
  await page.getByRole("button", { name: "取消选中", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "清理已结束记录", exact: true }),
  ).toBeEnabled();
  await page.screenshot({ path: "../output/test-ui-queue-management.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({
    path: "../output/test-ui-queue-management-mobile.png",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .getByRole("button", { name: "清理已结束记录", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("音乐文件会保留");
  await page.getByRole("button", { name: "确认操作", exact: true }).click();
  await expect(page.locator(".download-row")).toHaveCount(0);
  await page.getByRole("button", { name: "音乐库", exact: true }).click();
  await expect(page.locator(".music-table tbody tr")).toHaveCount(1);
  await expect(page.getByText("本地测试音乐", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "通勤", exact: true }).click();
  await page.getByLabel("播放本地歌曲 本地测试音乐", { exact: true }).click();
  await page.waitForFunction(
    () => document.querySelector("audio").currentTime > 0.05,
  );
  assert.ok(
    await page
      .locator("audio")
      .evaluate((audio) => audio.src.includes("/files/audio")),
  );
  await page.getByRole("button", { name: "正在播放", exact: true }).click();
  await expect(page.locator(".full-lyrics button")).toHaveCount(3);
  await page.locator(".full-lyrics button").nth(1).click();
  await expect(page.locator(".full-lyrics button.active")).toContainText(
    "本地歌词第二句",
  );
  await page.screenshot({ path: "../output/test-ui-player-local-lyrics.png" });
  await page.getByRole("button", { name: "音乐库", exact: true }).click();
  await expect(page.getByRole("tab")).toHaveText(["本地音乐", "Navidrome"]);
  await expect(page.getByLabel("更多音乐管理操作")).toHaveCount(0);
  await expect(
    page.getByLabel("编辑歌曲 本地测试音乐", { exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("整理歌曲 本地测试音乐", { exact: true }).click();
  await expect(page.locator(".sidebar .nav-item.active")).toHaveText(
    "刮削整理",
  );
  await expect(page.getByRole("tab")).toHaveText(["选择与处理", "任务与审核"]);
  await expect(page.locator(".workbench-submit")).toContainText(
    "已选 1 首歌曲",
  );
  await page.getByLabel("编辑歌曲 本地测试音乐", { exact: true }).click();
  await page.getByLabel("歌曲标题", { exact: true }).fill("修改后的本地歌曲");
  await page.getByRole("button", { name: "保存歌曲信息", exact: true }).click();
  await expect(page.locator(".music-table")).toContainText("修改后的本地歌曲");
  await page.getByRole("button", { name: "音乐库", exact: true }).click();
  await page.getByRole("button", { name: "播放选中", exact: true }).click();
  await page.waitForFunction(() => !document.querySelector("audio").paused);
  assert.equal(playlist[0].id, "local-fixture");
  await page.getByLabel("搜索音乐文件").fill("音乐");
  await expect(page.locator(".music-table tbody tr")).toHaveCount(1);
  await page.getByLabel("全选音乐文件").check();
  const clearNotice = async () => {
    const close = page.getByLabel("关闭提示", { exact: true });
    if (await close.count()) await close.click();
  };
  await clearNotice();
  await page.screenshot({ path: "../output/test-ui-file-management.png" });
  const localDuration = await page
    .locator(".music-table tbody .library-duration")
    .boundingBox();
  const localActions = await page.locator(".library-actions").boundingBox();
  assert.ok(
    localDuration.x + localDuration.width <= localActions.x,
    "local song actions do not overlap duration",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({
    path: "../output/test-ui-file-management-mobile.png",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "送往刮削整理", exact: true }).click();
  await expect(page.locator(".workbench-submit")).toContainText(
    "已选 1 首歌曲",
  );
  await page.getByLabel("更多音乐管理操作").selectOption("edit");
  await expect(
    page.getByRole("dialog", { name: "编辑选中歌曲" }),
  ).toBeVisible();
  await page.getByText("修改曲序", { exact: true }).click();
  await page.getByLabel("批量曲序", { exact: true }).fill("03");
  await page.getByText("修改发行日期", { exact: true }).click();
  await page.getByLabel("批量发行日期", { exact: true }).fill("2026-10-23");
  const batchCheckbox = await page
    .locator('.library-batch-edit input[type="checkbox"]')
    .first()
    .boundingBox();
  assert.ok(
    batchCheckbox.width <= 20,
    "batch checkboxes retain compact sizing",
  );
  await page.screenshot({ path: "../output/test-ui-library-batch-editor.png" });
  await page.getByRole("button", { name: "预览修改", exact: true }).click();
  await expect(page.locator(".tag-diff")).toContainText("2026-10-23");
  assert.equal(libraryJobs[0].status, "ready");
  await page.screenshot({ path: "../output/test-ui-library-tag-diff.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "../output/test-ui-library-tag-diff-mobile.png",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("tab", { name: "选择与处理", exact: true }).click();
  await page.getByLabel("本次处理", { exact: true }).selectOption("organize");
  await page.getByRole("button", { name: "生成修改预览", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "应用已确认的更改", exact: true }),
  ).toBeVisible();
  assert.equal(
    libraryJobs[0].status,
    "ready",
    "preview does not auto apply manual operations",
  );
  await expect(page.locator(".processing-paths")).toContainText(
    "/music/library/",
  );
  await page.screenshot({ path: "../output/test-ui-library-preview.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({
    path: "../output/test-ui-library-preview-mobile.png",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .getByRole("button", { name: "应用已确认的更改", exact: true })
    .click();
  await expect(page.locator(".processing-heading")).toContainText("已完成");
  await page.locator(".restore-confirm summary").click();
  await page
    .getByRole("button", { name: "确认恢复本次修改", exact: true })
    .click();
  await expect(page.locator(".processing-heading")).toContainText("已恢复");
  await page.getByRole("button", { name: "刮削整理", exact: true }).click();
  await page.getByRole("tab", { name: "选择与处理", exact: true }).click();
  await expect(page.locator(".workbench-submit")).toContainText(
    "已选 1 首歌曲",
  );
  await page.getByLabel("搜索音乐文件", { exact: true }).fill("没有这首歌");
  await expect(
    page.getByRole("button", { name: "生成修改预览", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("搜索音乐文件", { exact: true }).fill("");
  await page.getByLabel("全选音乐文件").check();
  await page.getByRole("button", { name: "前往规则设置", exact: true }).click();
  await page.getByLabel("MusicBrainz", { exact: true }).check();
  await page
    .locator(".metadata-source")
    .filter({ hasText: "网易云" })
    .getByRole("checkbox")
    .uncheck();
  await page
    .locator(".metadata-source")
    .filter({ hasText: "QQ音乐" })
    .getByRole("checkbox")
    .uncheck();
  await page.getByText("字段与覆盖规则", { exact: true }).click();
  await page
    .getByLabel("覆盖已有标签（关闭时只补空值，手动锁定的字段始终保留）", {
      exact: true,
    })
    .check();
  await page.getByRole("button", { name: "保存曲库设置", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "曲库设置已保存" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "刮削整理", exact: true }).click();
  await expect(
    page.locator(".library-workbench .metadata-sources"),
  ).toHaveCount(0);
  await expect(
    page.locator(".library-workbench input[type=checkbox]"),
  ).toHaveCount(0);
  await expect(page.getByLabel("当前处理规则")).toContainText("MusicBrainz");
  const controls = await page
    .locator(".workbench-options select")
    .evaluateAll((items) =>
      items.map((item) => {
        const r = item.getBoundingClientRect();
        return { top: r.top, height: r.height };
      }),
    );
  assert.equal(controls.length, 2);
  assert.ok(
    Math.abs(controls[0].top - controls[1].top) <= 1 &&
      Math.abs(controls[0].height - controls[1].height) <= 1,
    "workbench controls align",
  );
  await page.screenshot({
    path: "../output/test-ui-workbench.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({
    path: "../output/test-ui-workbench-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "生成修改预览", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "应用已确认的更改", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".processing-rules")).toContainText("MusicBrainz");
  await expect(page.locator(".processing-rules")).toContainText(
    "覆盖未锁定标签",
  );
  await expect(page.getByText(/补充资料来源：/)).toContainText(
    "歌词（QQ音乐）",
  );
  assert.equal(lastLibraryBody.sources, undefined);
  assert.deepEqual(lastLibraryBody.paths, ["fixture-a.wav"]);
  assert.equal(lastLibraryBody.overwrite, undefined);
  assert.equal(libraryJobs[0].status, "ready");
  assert.deepEqual(libraryConfig.sources, ["musicbrainz"]);
  await page.getByRole("button", { name: "全部任务", exact: true }).click();
  await page.getByRole("button", { name: "待确认", exact: true }).click();
  await expect(
    page.getByText("没有符合条件的任务", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "待应用", exact: true }).click();
  await expect(page.locator(".processing-list-row")).toHaveCount(2);
  await page.getByRole("tab", { name: "选择与处理", exact: true }).click();
  await page.getByLabel("全选音乐文件").check();
  await page.getByLabel("更多音乐管理操作").selectOption("rename");
  await page
    .getByLabel("文件名模板", { exact: true })
    .fill("${counter.zfill(2)} - ${title}");
  await page.getByRole("button", { name: "预览修改", exact: true }).click();
  await expect(page.locator(".processing-heading")).toContainText("批量重命名");
  assert.equal(
    lastLibraryBody.filename_template,
    "${counter.zfill(2)} - ${title}",
  );
  await expect(page.getByRole("link", { name: "导出处理报告" })).toBeVisible();
  await page.getByRole("tab", { name: "选择与处理", exact: true }).click();
  await page.getByLabel("更多音乐管理操作").selectOption("duplicates");
  await page.getByLabel("检查方式", { exact: true }).selectOption("audio");
  await page.getByRole("button", { name: "预览修改", exact: true }).click();
  await expect(page.locator(".processing-heading")).toContainText(
    "重复文件检查",
  );
  assert.equal(lastLibraryBody.duplicate_mode, "audio");
  await page.getByRole("tab", { name: "选择与处理", exact: true }).click();
  await page.getByLabel("更多音乐管理操作").selectOption("convert");
  await page.getByLabel("输出格式", { exact: true }).selectOption("opus");
  await page.getByLabel("采样率", { exact: true }).selectOption("48000");
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({ path: "../output/test-ui-convert-mobile.png" });
  await page.getByRole("button", { name: "预览修改", exact: true }).click();
  await expect(page.locator(".processing-heading")).toContainText("格式转换");
  assert.equal(lastLibraryBody.output_format, "opus");
  assert.equal(lastLibraryBody.sample_rate, 48000);
  await expect(
    page.getByText("输出文件（原件保留）", { exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("tab", { name: "选择与处理", exact: true }).click();
  await page.getByLabel("更多音乐管理操作").selectOption("split");
  await page
    .getByLabel("CUE 文本（可选）", { exact: true })
    .fill('FILE "测试音乐.wav" WAVE\nTRACK 01 AUDIO\nINDEX 01 00:00:00');
  await page.getByRole("button", { name: "预览修改", exact: true }).click();
  await expect(page.locator(".processing-heading")).toContainText("CUE 分轨");
  assert.match(lastLibraryBody.cue, /INDEX 01/);
  await page.getByRole("tab", { name: "选择与处理", exact: true }).click();
  await page.getByLabel("更多音乐管理操作").selectOption("clean");
  await page.getByLabel("中文转换", { exact: true }).selectOption("simplified");
  await page
    .getByLabel("修复 UTF-8 被按 Latin1 误读的乱码", { exact: true })
    .check();
  await page.getByRole("button", { name: "预览修改", exact: true }).click();
  await expect(page.locator(".processing-heading")).toContainText("清理标签");
  assert.equal(lastLibraryBody.chinese, "simplified");
  assert.equal(lastLibraryBody.repair_encoding, true);
  await page.getByRole("tab", { name: "选择与处理", exact: true }).click();
  await page.getByLabel("处理范围", { exact: true }).selectOption("directory");
  await page.getByLabel("目录路径", { exact: true }).fill("incoming");
  await page.getByRole("button", { name: "生成修改预览", exact: true }).click();
  await expect(page.locator(".processing-heading")).toBeVisible();
  assert.equal(lastLibraryBody.scope_dir, "incoming");
  assert.deepEqual(lastLibraryBody.paths, []);
  await openSettings("刮削与归档");
  await page.getByText("目录监控与预处理", { exact: true }).click();
  await page.getByLabel("启用目录监控", { exact: true }).check();
  await page
    .getByLabel("监控目录（每行一个）", { exact: true })
    .fill("incoming\nimports");
  await page
    .getByLabel("未匹配/失败文件目录（可选）", { exact: true })
    .fill("review");
  await page.getByRole("button", { name: "保存曲库设置", exact: true }).click();
  await expect(
    page.getByText("曲库设置已保存，后续新建任务将使用这些默认规则。", {
      exact: true,
    }),
  ).toBeVisible();
  assert.deepEqual(libraryConfig.watch_dirs, ["incoming", "imports"]);
  assert.equal(libraryConfig.watch_failure_dir, "review");
  assert.equal(libraryConfig.watch_enabled, true);
  await page
    .getByRole("button", { name: "检查已保存的监控目录", exact: true })
    .click();
  await expect(
    page.getByText("已检查监控目录，正在等待文件稳定", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("AcoustID 应用 Key", { exact: true })
    .fill("fixture-key");
  await page.getByRole("button", { name: "保存指纹配置", exact: true }).click();
  await expect(
    page.getByText("Key 已配置 · fpcalc 已找到", { exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({ path: "../output/test-ui-library-watch-mobile.png" });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "音乐库", exact: true }).click();
  await page.getByRole("tab", { name: "Navidrome", exact: true }).click();
  await page.getByRole("button", { name: "全部歌曲", exact: true }).click();
  await expect(page.locator(".navidrome-library .music-table")).toContainText(
    "远程歌曲",
  );
  await expect(
    page.getByLabel("删除原文件 远程歌曲", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "播放封面 远程歌曲", exact: true })
    .click();
  await expect
    .poll(() => page.locator("audio").evaluate((audio) => !audio.paused))
    .toBe(true);
  navDeleteEnabled = true;
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await page.getByLabel("删除原文件 远程歌曲", { exact: true }).click();
  const deletionDialog = page.getByRole("dialog", {
    name: "删除 Navidrome 原文件",
    exact: true,
  });
  await expect(deletionDialog).toContainText(
    "/music/library/远程歌手/远程歌曲.wav",
  );
  assert.equal(navDeletes, 0);
  await deletionDialog
    .getByRole("button", { name: "取消", exact: true })
    .click();
  assert.equal(navDeletes, 0);
  await page.getByLabel("删除原文件 远程歌曲", { exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await deletionDialog.screenshot({
    path: "../output/test-ui-navidrome-delete-confirm-mobile.png",
  });
  await deletionDialog
    .getByRole("button", { name: "确认永久删除", exact: true })
    .click();
  await expect(deletionDialog).toHaveCount(0);
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "音乐文件已删除，但扫描未启动" }),
  ).toBeVisible();
  await expect.poll(() => navDeletes).toBe(1);
  await expect
    .poll(() => page.locator("audio").evaluate((audio) => audio.paused))
    .toBe(true);
  navDeleteEnabled = false;
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByText("第 2 页", { exact: true })).toBeVisible();
  assert.ok(songOffsets.includes(50));
  await page.getByRole("button", { name: "上一页", exact: true }).click();
  await page.getByRole("button", { name: "卡片显示", exact: true }).click();
  await expect(page.locator(".nav-song-card")).toHaveCount(1);
  await page.screenshot({
    path: "../output/test-ui-navidrome-songs-cards.png",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  const songCover = await page
    .locator(".nav-song-card > .album-art")
    .boundingBox();
  assert.ok(
    songCover.width >= 120 && Math.abs(songCover.width - songCover.height) <= 1,
    "mobile song cards keep full square covers",
  );
  await page.screenshot({
    path: "../output/test-ui-navidrome-songs-cards-mobile.png",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "专辑", exact: true }).click();
  await page.getByRole("button", { name: "列表显示", exact: true }).click();
  await expect(page.locator(".nav-album-row")).toHaveCount(1);
  await page.getByRole("button", { name: "卡片显示", exact: true }).click();

  await expect(
    page.getByRole("button", { name: "远程专辑", exact: false }),
  ).toBeVisible();
  await page.screenshot({ path: "../output/test-ui-navidrome-albums.png" });
  await page.getByRole("button", { name: "远程专辑", exact: false }).click();
  await expect(page.locator(".nav-album-heading")).toContainText("远程专辑");
  await page.getByLabel("播放 远程歌曲", { exact: true }).click();
  await page.getByRole("button", { name: "正在播放", exact: true }).click();
  await expect(page.locator(".full-player .album-info")).toContainText(
    "远程歌曲",
  );
  await expect(page.locator(".full-lyrics button")).toHaveCount(3);
  await page.locator(".full-lyrics button").nth(1).click();
  await expect(page.locator(".full-lyrics button.active")).toContainText(
    "音乐库歌词第二句",
  );
  await page.waitForFunction(() => {
    const container = document
      .querySelector(".full-lyrics")
      .getBoundingClientRect();
    const active = document
      .querySelector(".full-lyrics button.active")
      .getBoundingClientRect();
    return (
      Math.abs(
        active.y + active.height / 2 - container.y - container.height / 2,
      ) < 12
    );
  });
  await page.screenshot({
    path: "../output/test-ui-player-navidrome-lyrics.png",
  });
  await page.getByRole("button", { name: "音乐库", exact: true }).click();
  remoteLyrics = Array.from(
    { length: 16 },
    (_, i) => `没有时间轴的歌词 第 ${i + 1} 行`,
  ).join("\n");
  await page.getByRole("button", { name: "远程专辑", exact: false }).click();
  await page.getByLabel("播放 远程歌曲", { exact: true }).click();
  await page.getByRole("button", { name: "正在播放", exact: true }).click();
  const plainLyrics = page.locator(".full-lyrics .lyric-empty");
  await expect(plainLyrics).toContainText("没有时间轴的歌词");
  await expect(
    page.getByRole("button", { name: "跟随进度", exact: true }),
  ).toBeDisabled();
  const plainSize = await plainLyrics.evaluate((e) =>
    parseFloat(getComputedStyle(e).fontSize),
  );
  assert.ok(plainSize >= 21);
  await page.getByLabel("调整歌词字号").click();
  assert.notEqual(
    await plainLyrics.evaluate((e) => parseFloat(getComputedStyle(e).fontSize)),
    plainSize,
  );
  assert.equal(
    await page.locator(".full-lyrics").evaluate((e) => e.scrollTop),
    0,
  );
  await page.screenshot({ path: "../output/test-ui-player-plain-lyrics.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page
      .locator(".full-player-controls")
      .getByRole("slider", { name: "音量", exact: true }),
  ).toBeVisible();
  assert.ok(
    (await plainLyrics.evaluate((e) =>
      parseFloat(getComputedStyle(e).fontSize),
    )) >= 17,
  );
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({
    path: "../output/test-ui-player-plain-lyrics-mobile.png",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  remoteLyrics = "[00:00]音乐库歌词第一句\n[00:02]音乐库歌词第二句";
  await page.getByRole("button", { name: "音乐库", exact: true }).click();
  await page.getByRole("button", { name: "远程专辑", exact: false }).click();
  await page.getByLabel("加入待播 远程歌曲", { exact: true }).click();
  await expect
    .poll(() => playlist.some((item) => item.id === "navidrome-s"))
    .toBe(true);
  await clearNotice();
  await page.screenshot({ path: "../output/test-ui-navidrome.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({ path: "../output/test-ui-navidrome-mobile.png" });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("tab", { name: "本地音乐", exact: true }).click();
  await page.getByLabel("全选音乐文件").check();
  await page.getByRole("button", { name: "删除选中文件", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("永久删除 1 个文件");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  assert.equal(libraryFiles.length, 2);
  await page.getByRole("button", { name: "删除选中文件", exact: true }).click();
  await page.getByRole("button", { name: "确认操作", exact: true }).click();
  await expect(page.locator(".music-table tbody tr")).toHaveCount(0);
  await page.getByLabel("搜索音乐文件").fill("");
  await page.getByRole("button", { name: "附属文件", exact: true }).click();
  await expect(page.locator(".music-table tbody tr")).toHaveCount(1);
  await page.getByRole("button", { name: "搜索音乐", exact: true }).click();
  await page.getByLabel("播放 测试曲目", { exact: true }).click();
  await page.getByLabel("加入播放列表 测试曲目", { exact: true }).click();
  if (await page.getByLabel("关闭提示", { exact: true }).count())
    await page.getByLabel("关闭提示", { exact: true }).click();
  await page.screenshot({ path: "../output/test-ui-search.png" });
  await page.getByLabel("选择 测试曲目", { exact: true }).check();
  await expect(page.locator(".selection-bar")).toBeVisible();
  const selBox = await page.locator(".selection-bar").boundingBox();
  const resBox = await page.locator(".result-column").boundingBox();
  assert.ok(
    Math.abs(selBox.x + selBox.width / 2 - (resBox.x + resBox.width / 2)) <= 3,
    "selection-bar is horizontally centered inside result-column",
  );
  await expect(
    page.locator(".selection-bar").getByRole("button", { name: "加入歌单" }),
  ).toBeVisible();
  await page.screenshot({ path: "../output/test-ui-selection-light.png" });
  await page.getByLabel("选择 测试曲目", { exact: true }).uncheck();
  await expect(
    page.locator(".now-panel").getByText("正在试听", { exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".source-errors")).toHaveCount(0);
  for (const label of [
    "收藏当前曲目",
    "选择版本并下载",
    "加入播放列表",
    "加入歌单",
  ])
    await expect(
      page
        .locator(".now-panel")
        .getByRole("button", { name: label, exact: true }),
    ).toBeVisible();
  await page
    .locator(".now-panel")
    .getByRole("button", { name: "选择版本并下载", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "取消", exact: true })
    .click();
  await page
    .locator(".now-panel")
    .getByRole("button", { name: "加入歌单", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "加入歌单", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "取消", exact: true })
    .click();
  await changeTheme("dark");
  await page.screenshot({ path: "../output/test-ui-search-dark.png" });
  await changeTheme("light");
  await page.keyboard.press("Control+k");
  await expect(page.getByLabel("搜索音乐", { exact: true })).toBeFocused();
  for (const width of [390, 768, 900, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      `overflow at ${width}`,
    );
    if (width <= 900) {
      const titleBox = await page.locator(".song-name").boundingBox();
      assert.ok(titleBox.width >= 80, `title squeezed at ${width}`);
      const actionBox = await page
        .getByLabel("下载 测试曲目", { exact: true })
        .boundingBox();
      assert.ok(actionBox.height >= 44, `small touch target at ${width}`);
      const checkBox = await page
        .getByLabel("选择 测试曲目", { exact: true })
        .boundingBox();
      const coverBox = await page
        .locator(".track-table .track .cover")
        .first()
        .boundingBox();
      assert.ok(
        checkBox.x + checkBox.width <= coverBox.x,
        `checkbox overlaps cover at ${width}`,
      );
      const sourceBoxes = await Promise.all(
        (await page.locator(".sources .source").all()).map((el) =>
          el.boundingBox(),
        ),
      );
      assert.ok(
        sourceBoxes.every((b) => Math.abs(b.y - sourceBoxes[0].y) <= 2),
        `sources wrapped into multiple rows at ${width}`,
      );
      const filterBox = await page.locator(".filter-group").boundingBox();
      const sortBox = await page.getByLabel("结果排序").boundingBox();
      assert.ok(
        Math.abs(filterBox.y - sortBox.y) <= 2 &&
          Math.abs(filterBox.height - sortBox.height) <= 2,
        `filter-group and sort select misaligned at ${width}`,
      );
      const nowBox = await page.locator(".now-panel").boundingBox();
      assert.ok(
        nowBox.y >= 680 && nowBox.y + nowBox.height <= 844,
        `now-panel not docked at bottom of viewport at ${width}`,
      );
      const playColors = await page
        .getByLabel("播放 测试曲目", { exact: true })
        .evaluate((btn) => {
          const style = getComputedStyle(btn);
          return { bg: style.backgroundColor, fg: style.color };
        });
      assert.notEqual(
        playColors.bg,
        playColors.fg,
        `play button text blends into background at ${width}`,
      );
    }
    if (width === 768)
      await page.screenshot({ path: "../output/test-ui-tablet.png" });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("播放列表", { exact: true }).click();
  await page.getByRole("dialog").getByLabel("移除 测试曲目").waitFor();
  await page.getByRole("dialog").getByLabel("关闭", { exact: true }).click();
  await page.getByRole("button", { name: "正在播放", exact: true }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  const mobileArtBox = await page
    .locator(".full-player .album-art")
    .boundingBox();
  const mobileLyricsBox = await page.locator(".lyrics-column").boundingBox();
  const mobileControlsBox = await page
    .locator(".full-player-controls")
    .boundingBox();
  const mobileActionBoxes = await Promise.all(
    (await page.locator(".album-actions button").all()).map((b) =>
      b.boundingBox(),
    ),
  );
  assert.ok(
    mobileArtBox.y >= 0 &&
      mobileLyricsBox.y >= mobileArtBox.y + mobileArtBox.height - 2 &&
      mobileLyricsBox.y + mobileLyricsBox.height <= mobileControlsBox.y + 4 &&
      mobileActionBoxes[0].y + mobileActionBoxes[0].height <= 844 &&
      mobileActionBoxes.every(
        (b) => Math.abs(b.y - mobileActionBoxes[0].y) <= 2,
      ),
    "mobile player shows compact header, central lyrics, controls, and single-row actions in one viewport",
  );
  await page.locator(".full-lyrics button").nth(2).click();
  await expect(page.getByLabel("切换随机播放", { exact: true })).toBeVisible();
  await expect(page.getByLabel("切换列表循环", { exact: true })).toBeVisible();
  await page.waitForFunction(() =>
    document
      .querySelector(".full-lyrics button.active")
      ?.textContent.includes("第三句"),
  );
  await page.waitForFunction(() => {
    const container = document.querySelector(".full-lyrics");
    const active = container?.querySelector("button.active");
    if (!container || !active) return false;
    const c = container.getBoundingClientRect(),
      a = active.getBoundingClientRect();
    return Math.abs(a.top + a.height / 2 - (c.top + c.height / 2)) < 80;
  });
  await page.screenshot({ path: "../output/test-ui-player-mobile.png" });
  await page.getByRole("button", { name: "搜索音乐", exact: true }).click();
  if (await page.getByLabel("关闭提示", { exact: true }).count())
    await page.getByLabel("关闭提示", { exact: true }).click();
  await page.screenshot({ path: "../output/test-ui-mobile.png" });
  for (const label of [
    "收藏 测试曲目",
    "播放 测试曲目",
    "下载 测试曲目",
    "加入播放列表 测试曲目",
  ])
    await expect(page.getByLabel(label, { exact: true })).toBeVisible();
  await page.getByLabel("加入播放列表 测试曲目", { exact: true }).click();
  await page.getByLabel("下载 测试曲目", { exact: true }).click();
  await page.getByRole("dialog").getByLabel("关闭", { exact: true }).click();
  await openSettings();
  await page.getByRole("button", { name: "刮削整理", exact: true }).click();
  await page.getByRole("tab", { name: "选择与处理", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "生成修改预览", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "前往规则设置", exact: true }).click();
  await expect(page.locator(".sidebar .nav-item.active")).toHaveText("设置");
  await expect(page.getByRole("tab", { selected: true })).toHaveText(
    "刮削与归档",
  );
  await expect(page.getByText("MusicBrainz", { exact: true })).toBeVisible();
  await page.getByText("下载后自动刮削", { exact: true }).click();
  await page.getByText("下载后自动整理入库", { exact: true }).click();
  await page.getByRole("button", { name: "保存曲库设置", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "曲库设置已保存" }),
  ).toBeVisible();
  assert.ok(libraryConfig.auto_scrape && libraryConfig.auto_organize);
  await page.locator(".template-help details summary").click();
  await page.locator(".template-help").screenshot({
    path: "../output/test-ui-template-help-mobile.png",
    style: ".sidebar, #toast { visibility: hidden; }",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator(".template-help").screenshot({
    path: "../output/test-ui-template-help-desktop.png",
    style: ".sidebar, #toast { visibility: hidden; }",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText("启用 Navidrome", { exact: true })).toHaveCount(
    0,
  );
  await page.getByRole("tab", { name: "Navidrome 连接", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "保存曲库设置", exact: true }),
  ).toHaveCount(0);
  const optionalDelete = page.getByRole("checkbox", {
    name: "允许删除 Navidrome 曲库原文件（可选）",
    exact: true,
  });
  await expect(optionalDelete).not.toBeChecked();
  await expect(
    page.getByPlaceholder("/music/library", { exact: true }),
  ).toHaveCount(0);
  await optionalDelete.check();
  await page
    .getByPlaceholder("/music/library", { exact: true })
    .fill("/music/library");
  await page.getByPlaceholder("/music", { exact: true }).fill("/music");
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.locator(".library-settings").screenshot({
    path: "../output/test-ui-navidrome-delete-settings-mobile.png",
  });
  await optionalDelete.uncheck();
  await page.getByText("启用 Navidrome", { exact: true }).click();
  await page.getByLabel(/^服务地址/).fill("http://navidrome:4533");
  await page
    .locator(".library-settings")
    .getByLabel("用户名", { exact: true })
    .fill("admin");
  await page
    .locator(".library-settings")
    .getByLabel("密码", { exact: true })
    .fill("fixture-secret");
  await page
    .getByRole("button", { name: "保存并测试连接", exact: true })
    .click();
  await expect(
    page.getByRole("status").filter({ hasText: "连接成功，服务器版本" }),
  ).toBeVisible();
  await page
    .locator(".library-settings")
    .screenshot({ path: "../output/test-ui-library-settings.png" });
  await clearNotice();
  await page.locator(".library-settings > form").first().screenshot({
    path: "../output/test-ui-library-settings-mobile.png",
    style: ".sidebar { visibility: hidden !important; }",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator(".library-settings > form").first().screenshot({
    path: "../output/test-ui-library-settings-desktop.png",
    style: ".sidebar { visibility: hidden !important; }",
  });
  await page.locator(".library-settings > form").first().screenshot({
    path: "../output/test-ui-navidrome-settings.png",
    style: ".sidebar { visibility: hidden !important; }",
  });
  await changeTheme("dark");
  await page.locator(".library-settings > form").first().screenshot({
    path: "../output/test-ui-library-settings-desktop-dark.png",
    style: ".sidebar { visibility: hidden !important; }",
  });
  await changeTheme("light");
  await page.setViewportSize({ width: 390, height: 844 });
  await openSettings();
  await page.locator(".source-setting").first().waitFor({ state: "attached" });
  assert.equal(await page.locator(".source-setting").count(), 8);
  const sourceDisclosure = page.locator(".settings-sources .source-disclosure");
  await expect(sourceDisclosure).not.toHaveAttribute("open");
  await sourceDisclosure.locator("summary").first().click();
  await expect(page.locator(".settings-advanced")).not.toHaveAttribute("open");
  await page.getByRole("button", { name: "取消全选", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "保存设置", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "全选", exact: true }).click();
  assert.equal(
    await page.locator(".source-setting input[type=checkbox]:checked").count(),
    8,
  );
  await page.getByLabel("启用 GDStudio", { exact: true }).uncheck();
  await page.locator(".settings-advanced > summary").click();
  assert.ok(await page.getByText("GDStudio", { exact: true }).isVisible());
  await page.getByLabel("每页大小", { exact: true }).fill("25");
  await page.getByLabel("最大重试次数", { exact: true }).fill("5");
  await page.getByLabel("默认下载线程数", { exact: true }).fill("12");
  await page
    .getByLabel("请求超时（秒，0 表示不限）", { exact: true })
    .fill("0");
  await page.getByLabel("搜索使用浏览器指纹", { exact: false }).check();
  await page
    .getByLabel("音源代理作用范围", { exact: true })
    .selectOption("selected");
  const proxyDisclosure = page.locator(".settings-proxy .source-disclosure");
  await expect(proxyDisclosure).not.toHaveAttribute("open");
  await proxyDisclosure.locator("summary").click();
  await page.getByRole("button", { name: "选择推荐音源", exact: true }).click();
  await expect(
    page.locator(".source-picker").getByLabel("YouTube", { exact: false }),
  ).toBeChecked();
  await expect(
    page.locator(".source-picker").getByLabel("Spotify", { exact: false }),
  ).toBeChecked();
  await expect(
    page.locator(".source-picker").getByLabel("网易云", { exact: true }),
  ).not.toBeChecked();
  await page.getByRole("button", { name: "清空代理选择", exact: true }).click();
  await page
    .locator(".source-picker")
    .getByLabel("GDStudio", { exact: true })
    .check();
  await page
    .getByLabel("项目 HTTP / HTTPS 代理", { exact: true })
    .fill("http://localhost:7890");
  const neteaseSettings = page.locator(".source-setting").first();
  await neteaseSettings.locator("summary").click();
  await neteaseSettings
    .getByLabel("Cookie", { exact: true })
    .fill("fixture=netease");
  await neteaseSettings.getByLabel("分源下载线程数", { exact: true }).fill("9");
  await neteaseSettings
    .getByLabel("音源代理", { exact: true })
    .selectOption("project");
  await page
    .getByLabel("分源搜索规则（search_rules）", { exact: false })
    .fill("{");
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("JSON 格式无效");
  assert.equal(engineSaves, 0);
  await page
    .getByLabel("分源搜索规则（search_rules）", { exact: false })
    .fill('{"MiguMusicClient":{"quality":"keep"}}');
  const lazySearch = page.getByRole("checkbox", {
    name: /按需解析音源（QQ \/ 网易云）/,
  });
  await expect(lazySearch).not.toBeChecked();
  await lazySearch.check();
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(
    page.locator(".settings-save").getByRole("status"),
  ).toContainText("全部设置已保存并生效");
  assert.equal(engineConfig.global_client_cfg.search_size_per_page, 25);
  assert.equal(engineConfig.global_client_cfg.max_retries, 5);
  assert.equal(engineConfig.global_client_cfg.enable_search_curl_cffi, true);
  assert.deepEqual(engineConfig.global_client_cfg.default_parse_cookies, {
    preserve: "yes",
  });
  assert.equal(engineConfig.default_threads, 12);
  assert.equal(engineConfig.request_timeout, 0);
  assert.equal(engineConfig.lazy_search, true);
  await expect(lazySearch).toBeChecked();
  assert.deepEqual(engineConfig.proxy_sources, [
    "GDStudioMusicClient",
    "NeteaseMusicClient",
  ]);
  assert.deepEqual(engineConfig.cookies.MiguMusicClient, { fixture: "keep" });
  assert.deepEqual(engineConfig.init_music_clients_cfg.MiguMusicClient, {
    maintain_session: true,
  });
  assert.equal(engineConfig.clients_threadings.MiguMusicClient, 7);
  assert.equal(engineConfig.clients_threadings.NeteaseMusicClient, 9);
  assert.equal(engineConfig.cookies.NeteaseMusicClient, "fixture=netease");
  assert.equal(
    engineConfig.requests_overrides.NeteaseMusicClient.proxies,
    undefined,
  );
  assert.deepEqual(engineConfig.requests_overrides.MiguMusicClient.headers, {
    "X-Custom": "keep",
  });
  engineSourceErrors = { GDStudioMusicClient: "需要补全分源配置" };
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(
    page.locator(".settings-save").getByRole("status"),
  ).toContainText("设置已保存，1 个音源暂不可用，其他音源已生效");
  await expect(
    page.locator(".settings-save").getByRole("status"),
  ).toContainText("GDStudio：需要补全分源配置");
  engineSourceErrors = {};
  await lazySearch.uncheck();
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(
    page.locator(".settings-save").getByRole("status"),
  ).toContainText("全部设置已保存并生效");
  assert.equal(engineConfig.lazy_search, false);
  await expect(lazySearch).not.toBeChecked();
  await page.locator(".settings-advanced > summary").click();
  await sourceDisclosure
    .getByRole("button", { name: "完成选择，收起" })
    .click();
  await proxyDisclosure.getByRole("button", { name: "完成选择，收起" }).click();
  await expect(sourceDisclosure).not.toHaveAttribute("open");
  await expect(proxyDisclosure).not.toHaveAttribute("open");
  await expect(proxyDisclosure.locator("summary")).toContainText("已选 2 个");
  const numberWidth = await page
    .getByLabel("每页大小", { exact: true })
    .evaluate((el) => el.getBoundingClientRect().width);
  assert.ok(numberWidth <= 216, "numeric settings remain compact");
  await expect(page.locator("footer.player")).toHaveCount(0);
  await changeTheme("light");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => scrollTo(0, 0));
  for (const width of [768, 1200, 1440, 1920, 2560]) {
    await page.setViewportSize({ width, height: 1000 });
    const form = await page.locator(".settings-form").boundingBox();
    const view = await page.locator(".view").boundingBox();
    assert.ok(
      Math.abs(form.width - view.width) < 1,
      "settings use available space",
    );
    const basics = await page.locator(".settings-basics").boundingBox();
    const proxy = await page.locator(".settings-proxy").boundingBox();
    if (width > 1200) {
      assert.equal(basics.y, proxy.y, "basic and proxy settings share a row");
      assert.ok(
        basics.x + basics.width < proxy.x,
        "settings columns do not overlap",
      );
    } else {
      assert.ok(
        proxy.y >= basics.y + basics.height,
        "settings stack on smaller screens",
      );
    }
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      `settings overflow at ${width}`,
    );
  }
  await page.setViewportSize({ width: 1920, height: 1000 });
  await page.screenshot({ path: "../output/test-ui-settings-wide.png" });
  await page.locator(".engine-switches").screenshot({
    path: "../output/test-ui-engine-checkboxes.png",
  });
  await changeTheme("dark");
  await page.screenshot({ path: "../output/test-ui-settings-dark.png" });
  await changeTheme("light");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: "../output/test-ui-settings.png",
    fullPage: true,
    style: ".player, #toast { visibility: hidden; }",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "../output/test-ui-settings-mobile.png",
    fullPage: true,
    style: ".player, #toast { visibility: hidden; }",
  });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.reload();
  await page.waitForFunction(
    () => document.documentElement.dataset.theme === "light",
  );
  assert.ok(await page.getByText("最近搜索", { exact: true }).isVisible());
  await changeTheme("system");
  await page.waitForFunction(
    () => document.documentElement.dataset.theme === "dark",
  );
  await page.emulateMedia({ colorScheme: "light" });
  await page.waitForFunction(
    () => document.documentElement.dataset.theme === "light",
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "运行日志", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("HTTP 403");
  await expect(page.locator(".log-row time").first()).toHaveText(
    "2026-10-10 14:00:00",
  );
  await page.getByLabel("日志级别").selectOption("error");
  await expect(page.locator(".log-row")).toHaveCount(
    logEntries.filter((entry) => entry.level === "error").length,
  );
  await page.getByLabel("日志类别").selectOption("search");
  await expect(page.locator(".log-row")).toHaveCount(0);
  await page.getByLabel("日志类别").selectOption("all");
  await page.getByLabel("搜索日志").fill("download-fixture");
  await expect(page.locator(".log-row")).toHaveCount(1);
  const exported = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出当前日志", exact: true }).click();
  const download = await exported;
  assert.ok(download.suggestedFilename().endsWith(".log"));
  assert.ok(
    (await readFile(await download.path(), "utf8")).includes(
      "[2026-10-10 14:00:01]",
    ),
  );
  await page.getByRole("button", { name: "暂停更新", exact: true }).click();
  const frozen = logFetches;
  await page.waitForTimeout(1100);
  assert.equal(logFetches, frozen);
  await page.getByLabel("搜索日志").fill("");
  await page.getByLabel("日志级别").selectOption("all");
  logEntries.push({
    id: 3,
    time: "2026-10-10 14:00:02",
    level: "warning",
    category: "download",
    task_id: "download-fixture",
    message: "网络重试，已保留下载进度",
  });
  await page.getByRole("button", { name: "继续更新", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("网络重试");
  await page.screenshot({ path: "../output/test-ui-logs.png" });
  await changeTheme("dark");
  await page.screenshot({ path: "../output/test-ui-logs-dark.png" });
  await changeTheme("light");
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({ path: "../output/test-ui-logs-mobile.png" });
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.locator(".sidebar").getByRole("button", { name: /^歌单/ }).click();
  await page.getByRole("button", { name: "歌单导入", exact: true }).click();
  await page.getByLabel("歌单名称（可选）").fill("通勤歌单");
  await page.getByLabel("歌单链接 / ID").fill("1234");
  await page
    .getByRole("button", { name: "导入并保存歌单", exact: true })
    .click();
  await expect(page.locator(".playlist-heading h2")).toHaveText("通勤歌单");
  await expect(page.locator(".playlist-issues")).toContainText("可能");
  await expect(page.locator(".playlist-issues")).toContainText("其它版本可播");
  assert.equal(await page.locator(".track-table tbody tr").count(), 1);
  await expect(
    page.getByRole("button", { name: "移出歌单 测试曲目", exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: "../output/test-ui-playlist-detail.png" });
  await page.getByRole("button", { name: "重命名", exact: true }).click();
  await page.getByLabel("歌单名称", { exact: true }).fill("晚间歌单");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.locator(".playlist-heading h2")).toHaveText("晚间歌单");
  await page.getByRole("button", { name: "所有歌单", exact: true }).click();
  await expect(page.locator(".saved-playlist")).toContainText("晚间歌单");
  await page.screenshot({ path: "../output/test-ui-playlist-library.png" });
  await page.reload();
  await page.getByRole("button", { name: /^歌单/ }).click();
  await page
    .locator(".collection-tabs")
    .getByRole("button", { name: /^我的收藏/ })
    .click();
  await expect(page.locator(".track-table tbody tr")).toHaveCount(1);
  await expect(
    page.locator('nav[aria-label="主导航"] button.active'),
  ).toContainText("歌单");
  await page
    .locator(".collection-tabs")
    .getByRole("button", { name: /^我的歌单/ })
    .click();
  await expect(page.locator(".saved-playlist")).toContainText("晚间歌单");
  await page.locator(".saved-playlist").click();
  await expect(page.locator(".playlist-heading h2")).toHaveText("晚间歌单");
  await page.getByRole("button", { name: "播放全部", exact: true }).click();
  await page.waitForFunction(() => !document.querySelector("audio").paused);
  await expect(page.locator(".playlist-heading h2")).toHaveText("晚间歌单");
  await changeTheme("dark");
  await page.screenshot({ path: "../output/test-ui-playlist-dark.png" });
  await changeTheme("light");
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({
    path: "../output/test-ui-playlist-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.getByRole("button", { name: "下载全部", exact: true }).click();
  await page.getByRole("button", { name: "加入下载队列", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByRole("button", { name: "移出歌单 测试曲目", exact: true })
    .click();
  await expect(page.locator(".track-table tbody tr")).toHaveCount(0);
  await page.getByRole("button", { name: "删除歌单", exact: true }).click();
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(page.locator(".saved-playlist")).toHaveCount(0);
  await expect(page.locator(".library-empty")).toBeVisible();
  remoteSyncEnabled = true;
  await page.getByRole("button", { name: "歌单", exact: true }).click();
  await expect(
    page.locator(".saved-playlist").filter({ hasText: remotePlaylistName }),
  ).toBeVisible();
  for (const width of [320, 390, 600, 768, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    const cover = page.locator(".saved-playlist .album-art");
    const box = await cover.boundingBox();
    assert.ok(
      Math.abs(box.width - box.height) < 1,
      `Navidrome playlist thumbnail stays square at ${width}`,
    );
    await expect(cover.locator("img")).toBeVisible();
    if (width === 390)
      await page.screenshot({
        path: "../output/test-ui-navidrome-playlists-mobile.png",
      });
  }
  await page
    .locator(".saved-playlist")
    .filter({ hasText: remotePlaylistName })
    .click();
  await expect(page.locator(".playlist-heading h2")).toHaveText(
    remotePlaylistName,
  );
  await expect(
    page.getByRole("link", { name: "下载 远程歌曲", exact: true }),
  ).toHaveAttribute("href", "/api/navidrome/stream/s");
  await page.screenshot({ path: "../output/test-ui-navidrome-playlist.png" });
  for (const width of [320, 390, 600, 768, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    const cover = page.locator(".playlist-heading > .album-art");
    const box = await cover.boundingBox();
    assert.ok(
      Math.abs(box.width - box.height) < 1,
      `Navidrome playlist detail cover stays square at ${width}`,
    );
    const image = await cover.locator("img").boundingBox();
    assert.ok(
      Math.abs(image.width - box.width) < 1 &&
        Math.abs(image.height - box.height) < 1,
      `playlist image fills its square cover at ${width}`,
    );
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      `Navidrome playlist detail fits at ${width}`,
    );
    if (width === 390)
      await page.screenshot({
        path: "../output/test-ui-navidrome-playlist-mobile.png",
        style: "#toast { visibility: hidden; }",
      });
  }
  await page.setViewportSize({ width: 1920, height: 1080 });

  remotePlaylistTracks = ["mp3", "", "flac", "aac"].map((codec) => ({
    ...remoteTrack,
    id: `navidrome-quality-${codec || "unknown"}`,
    title: `筛选测试 ${codec || "unknown"}`,
    playback: {
      ...remoteTrack.playback,
      codec,
      bitrate: codec === "flac" ? 900 : codec === "mp3" ? 320 : 128,
    },
  }));
  await page.getByRole("button", { name: "同步歌单", exact: true }).click();
  await expect(page.locator(".track-table tbody tr")).toHaveCount(4);
  const qualityFilters = page.getByRole("group", {
    name: "音质筛选",
    exact: true,
  });
  for (const [label, formats] of [
    ["仅无损", ["flac"]],
    ["MP3", ["mp3"]],
    ["普通音质", ["mp3", "aac"]],
    ["音质未知", ["unknown"]],
  ]) {
    await qualityFilters
      .getByRole("button", { name: label, exact: true })
      .click();
    await expect(page.locator(".track-table tbody tr .song-name")).toHaveText(
      formats.map((codec) => `筛选测试 ${codec}`),
    );
  }
  await qualityFilters
    .getByRole("button", { name: "全部", exact: true })
    .click();
  await page.getByLabel("结果排序").selectOption("quality-desc");
  await expect(page.locator(".track-table tbody tr .song-name")).toHaveText([
    "筛选测试 flac",
    "筛选测试 mp3",
    "筛选测试 aac",
    "筛选测试 unknown",
  ]);
  await page.getByLabel("结果排序").selectOption("relevance");
  remotePlaylistTracks = [remoteTrack];
  await page.getByRole("button", { name: "同步歌单", exact: true }).click();
  await expect(page.locator(".track-table tbody tr .song-name")).toHaveText([
    remoteTrack.title,
  ]);

  await expect(
    page.getByRole("button", { name: "删除歌单", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByLabel("移出歌单 远程歌曲", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "播放全部", exact: true }).click();
  await expect.poll(() => playlist[0]?.id).toBe("navidrome-s");
  remotePlaylistName = "服务器已更新的歌单";
  await page.getByRole("button", { name: "同步歌单", exact: true }).click();
  await expect(page.locator(".playlist-heading h2")).toHaveText(
    remotePlaylistName,
  );
  await page.getByRole("button", { name: "所有歌单", exact: true }).click();
  remoteSyncFails = true;
  await page.getByRole("button", { name: "同步歌单", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("远程连接暂时失败");
  await expect(
    page.locator(".saved-playlist").filter({ hasText: remotePlaylistName }),
  ).toBeVisible();
  remoteSyncFails = false;
  await page.getByRole("button", { name: "同步歌单", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);

  remoteWritable = true;
  remotePlaylistTracks = [remoteTrack, remoteTrack];
  await page.getByRole("button", { name: "同步歌单", exact: true }).click();
  await page
    .locator(".saved-playlist")
    .filter({ hasText: remotePlaylistName })
    .click();
  await expect(page.locator(".track-table tbody tr")).toHaveCount(2);
  await page
    .getByRole("button", { name: "移出歌单 远程歌曲", exact: true })
    .nth(1)
    .click();
  const removeDialog = page.getByRole("dialog", {
    name: "从 Navidrome 歌单移除歌曲",
    exact: true,
  });
  await expect(removeDialog).toContainText("音乐文件会保留");
  await removeDialog
    .getByRole("button", { name: "确认操作", exact: true })
    .click();
  await expect(page.locator(".track-table tbody tr")).toHaveCount(1);
  assert.deepEqual(remoteWrites.at(-1).body.indexes, [1]);
  await page.getByRole("button", { name: "重命名", exact: true }).click();
  const renameDialog = page.getByRole("dialog");
  await renameDialog.locator("input").fill("管理后的远程歌单");
  await renameDialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.locator(".playlist-heading h2")).toHaveText(
    "管理后的远程歌单",
  );
  await page.getByRole("button", { name: "删除歌单", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("音乐文件");
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(page.locator(".saved-playlist")).toHaveCount(0);
  await page.getByRole("button", { name: "新建歌单", exact: true }).click();
  const createDialog = page.getByRole("dialog", {
    name: "新建歌单",
    exact: true,
  });
  await createDialog
    .getByRole("radio", { name: "新建 Navidrome 歌单", exact: false })
    .check();
  await createDialog
    .getByLabel("新歌单名称", { exact: true })
    .fill("新建远程歌单");
  await createDialog
    .getByRole("button", { name: "创建歌单", exact: true })
    .click();
  await expect(page.locator(".playlist-heading h2")).toHaveText("新建远程歌单");
  assert.deepEqual(remoteWrites.at(-1).body.song_ids, []);
  await page.getByRole("button", { name: "音乐库", exact: true }).click();
  await page.getByRole("tab", { name: "Navidrome", exact: true }).click();
  await page.getByRole("button", { name: "全部歌曲", exact: true }).click();
  await page.getByLabel("加入歌单 远程歌曲", { exact: true }).click();
  const addDialog = page.getByRole("dialog", { name: "加入歌单", exact: true });
  await addDialog
    .getByRole("radio", { name: "新建远程歌单", exact: false })
    .check();
  await addDialog
    .getByRole("button", { name: "确定加入", exact: true })
    .click();
  await expect(addDialog).toHaveCount(0);
  assert.deepEqual(remoteWrites.at(-1).body.song_ids, ["s"]);
  await page.getByRole("button", { name: "歌单", exact: true }).click();
  await expect(page.locator(".track-table tbody tr")).toHaveCount(1);
  await openSettings("通知与机器人");
  await expect(
    page.locator('.channel-status[data-enabled="false"]'),
  ).toHaveCount(2);
  await page.locator(".bot-settings .settings-behavior h2").screenshot({
    path: "../output/test-ui-channel-disabled.png",
  });
  await expect(
    page.getByRole("button", { name: "测试 Telegram 连接", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "测试企业微信连接", exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel("Telegram Bot Token", { exact: true })
    .fill("fixture-bot-token");
  await page
    .getByLabel("Telegram 代理", { exact: true })
    .selectOption("project");
  await page
    .getByRole("button", { name: "测试 Telegram 连接", exact: true })
    .click();
  await expect(
    page.getByText("连接测试成功；未发送消息。", { exact: true }),
  ).toBeVisible();
  assert.equal(botSaves, 0, "testing does not save the draft");
  assert.equal(botTests.length, 1);
  assert.equal(botTests[0].channel, "tg");
  assert.equal(botTests[0].config.tg_token, "fixture-bot-token");
  assert.equal(botTests[0].config.tg_proxy_mode, "project");
  assert.equal(botTests[0].config.public_url, "");
  assert.equal(botTests[0].config.tg_allowed_users, "");
  assert.equal(botTests[0].config.tg_enabled, false);
  assert.deepEqual(botTests[0].config.clear_secrets, []);
  await expect(
    page.getByLabel("Telegram Bot Token", { exact: true }),
  ).toHaveValue("fixture-bot-token");
  await page
    .getByLabel("公网访问地址", { exact: true })
    .fill("192.168.1.20:8765");
  await expect(
    page.getByLabel("企业微信回调地址", { exact: true }),
  ).toHaveValue("http://192.168.1.20:8765/bot/wecom");
  await page.getByLabel("启用 Telegram", { exact: true }).check();
  await expect(
    page.locator('.channel-status[data-enabled="false"]'),
  ).toHaveCount(2);
  await page.getByLabel("Telegram 用户白名单", { exact: true }).fill("123456");
  await page
    .getByLabel("企业微信 CorpID", { exact: true })
    .fill("corp-fixture");
  await page.getByLabel("企业微信 AgentID", { exact: true }).fill("100001");
  await page
    .getByLabel("企业微信 Secret", { exact: true })
    .fill("fixture-secret");
  await page
    .getByRole("button", { name: "测试企业微信连接", exact: true })
    .click();
  await expect(
    page.getByText("连接测试成功；未发送消息。", { exact: true }),
  ).toBeVisible();
  assert.equal(botSaves, 0);
  assert.equal(botTests.length, 2);
  assert.equal(botTests[1].channel, "wecom");
  assert.equal(botTests[1].config.wecom_corp_id, "corp-fixture");
  assert.equal(botTests[1].config.wecom_agent_id, "100001");
  assert.equal(botTests[1].config.wecom_secret, "fixture-secret");
  assert.equal(botTests[1].config.wecom_enabled, false);
  assert.equal(botTests[1].config.wecom_allowed_users, "");
  assert.equal(botTests[1].config.wecom_token, "");
  assert.equal(botTests[1].config.wecom_aes_key, "");
  await page.getByLabel("启用企业微信", { exact: true }).check();
  await page
    .getByLabel("企业微信回调 Token", { exact: true })
    .fill("fixture-token");
  await page
    .getByLabel("企业微信 EncodingAESKey", { exact: true })
    .fill("a".repeat(43));
  await page.getByLabel("企业微信用户白名单", { exact: true }).fill("alice");
  await page.getByRole("button", { name: "保存通知配置", exact: true }).click();
  await expect(
    page.getByText("通知渠道已保存并立即生效，无需重启服务", { exact: true }),
  ).toBeVisible();
  await expect(
    page.locator('.channel-status[data-enabled="true"]'),
  ).toHaveCount(2);
  await page.locator(".bot-settings .settings-behavior h2").screenshot({
    path: "../output/test-ui-channel-enabled.png",
  });
  await changeTheme("dark");
  await page.locator(".bot-settings .settings-behavior h2").screenshot({
    path: "../output/test-ui-channel-enabled-dark.png",
  });
  await changeTheme("light");
  await expect(
    page.getByLabel("Telegram Bot Token", { exact: true }),
  ).toHaveValue("");
  assert.equal(botSaves, 1);
  await expect(page.getByLabel("公网访问地址", { exact: true })).toHaveValue(
    "http://192.168.1.20:8765",
  );
  await expect(
    page.getByLabel("企业微信回调地址", { exact: true }),
  ).toHaveValue("http://192.168.1.20:8765/bot/wecom");
  await page
    .getByRole("button", { name: "测试 Telegram 连接", exact: true })
    .click();
  await expect(
    page.getByText("连接测试成功；未发送消息。", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "测试企业微信连接", exact: true })
    .click();
  await expect(
    page.getByText("连接测试成功；未发送消息。", { exact: true }),
  ).toBeVisible();
  assert.equal(botTests.length, 4);
  assert.equal(botTests[2].config.tg_token, "");
  assert.equal(botTests[3].config.wecom_secret, "");
  assert.equal(botSaves, 1);
  await expect(page.getByLabel("Telegram 代理", { exact: true })).toHaveValue(
    "project",
  );
  await page.screenshot({ path: "../output/test-ui-bots.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  for (const width of [320, 390, 600]) {
    await page.setViewportSize({ width, height: 844 });
    assert.ok(
      await page.locator(".sidebar nav").evaluate((strip) => {
        strip.scrollLeft = strip.scrollWidth;
        const scrolls =
          strip.scrollWidth > strip.clientWidth && strip.scrollLeft > 0;
        strip.scrollLeft = 0;
        return scrolls;
      }),
      "mobile navigation remains horizontally scrollable",
    );
    const projectLink = page.locator(".sidebar-bottom").getByRole("link", {
      name: "项目地址（在新标签页打开）",
    });
    await expect(projectLink).toBeVisible();
    await expect(projectLink).toHaveAttribute(
      "href",
      "https://github.com/Agonie0v0/melokeep",
    );
    await expect(projectLink).toHaveAttribute("target", "_blank");
    await expect(page.locator(".project-link")).toHaveCount(1);
    const navButtons = page.locator(".sidebar-capsules .nav-item");
    await expect(navButtons).toHaveCount(8);
    const themeButton = await page
      .getByRole("button", { name: "切换主题", exact: true })
      .boundingBox();
    const logoutButton = page.getByRole("button", {
      name: "退出登录",
      exact: true,
    });
    const logoutBox = await logoutButton.boundingBox();
    assert.equal((await logoutButton.textContent()).trim(), "");
    assert.ok(
      themeButton.x + themeButton.width <= logoutBox.x &&
        logoutBox.x + logoutBox.width <= width &&
        themeButton.height >= 44 &&
        logoutBox.height >= 44,
      `header icon tools stay at the right edge at ${width}`,
    );
    const boxes = [];
    for (const button of await navButtons.all()) {
      await expect(button).toBeVisible();
      const box = await button.boundingBox();
      assert.ok(box.width > 44 && box.height >= 44);
      if (boxes.length)
        assert.ok(
          Math.abs(box.y - boxes[0].y) <= 2,
          `top nav capsules wrapped into multiple rows at ${width}`,
        );
      for (const other of boxes)
        assert.ok(
          box.x >= other.x + other.width ||
            other.x >= box.x + box.width ||
            box.y >= other.y + other.height ||
            other.y >= box.y + box.height,
        );
      boxes.push(box);
    }
    await expect(
      page
        .locator(".top")
        .getByRole("button", { name: "音源设置", exact: true }),
    ).toHaveCount(0);
  }
  for (const width of [320, 390, 600, 801, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    const header = await page.locator(".sidebar").boundingBox();
    const brand = await page.locator(".sidebar .brand").boundingBox();
    const tools = page.locator(".sidebar-bottom");
    const boxes = await Promise.all(
      [".project-link", ".theme-toggle", ".nav-order-toggle", ".logout"].map(
        (selector) => tools.locator(selector).boundingBox(),
      ),
    );
    for (const [index, box] of boxes.entries()) {
      assert.ok(
        box.x >= header.x &&
          box.x + box.width <= header.x + header.width &&
          box.x + box.width <= width &&
          Math.abs(box.y - boxes[0].y) < 1,
        `shared header tools stay on one row inside the viewport at ${width}`,
      );
      if (index)
        assert.ok(
          box.x >= boxes[index - 1].x + boxes[index - 1].width,
          `header tool order is project, theme, navigation, logout at ${width}`,
        );
    }
    assert.ok(
      brand.x + brand.width <= boxes[0].x,
      `brand and header tools do not overlap at ${width}`,
    );
    await tools
      .getByRole("button", { name: "调整导航顺序", exact: true })
      .click();
    await expect(page.locator("#navigation-order")).toBeVisible();
    const menu = await page.locator("#navigation-order").boundingBox();
    assert.ok(
      menu.x >= 0 && menu.x + menu.width <= width,
      `navigation menu stays inside ${width}px viewport: ${JSON.stringify(menu)}`,
    );
    await page
      .getByRole("button", { name: "关闭导航排序", exact: true })
      .click();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "../output/test-ui-bots-mobile.png",
    fullPage: true,
  });
  await page.reload();
  await openSettings("通知与机器人");
  await expect(page.getByLabel("启用 Telegram", { exact: true })).toBeChecked();
  await expect(
    page.getByLabel("Telegram Bot Token", { exact: true }),
  ).toHaveValue("");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "搜索音乐", exact: true }).click();
  await submitSearch("错误试听");
  brokenAudio = true;
  await page
    .getByRole("button", { name: "播放 测试曲目", exact: true })
    .click();
  await expect
    .poll(() =>
      playbackReports.some(
        (report) => report.event === "failed" && report.code === 4,
      ),
    )
    .toBe(true);
  await page.getByRole("button", { name: "运行日志", exact: true }).click();
  await page.getByLabel("日志类别", { exact: true }).selectOption("playback");
  await expect(page.locator(".log-lines")).toContainText("MediaError=4");
  await page.getByRole("button", { name: "搜索音乐", exact: true }).click();
  await changeTheme("system");
  await page.emulateMedia({ colorScheme: "light" });
  const loginAttempts = [];
  let releaseLogin;
  const loginGate = new Promise((resolve) => (releaseLogin = resolve));
  await page.route("**/api/auth/login", async (route) => {
    const credentials = route.request().postDataJSON();
    loginAttempts.push(credentials);
    if (credentials.password !== "correct-password") {
      await route.fulfill({
        status: 401,
        json: { detail: "用户名或密码错误，请检查后重试" },
      });
    } else {
      await loginGate;
      await route.fulfill({ json: { authenticated: true } });
    }
  });
  await page.route("**/api/auth/status", (route) =>
    route.fulfill({ json: { required: true, authenticated: false } }),
  );
  const logoutRequest = page.waitForRequest(
    (request) =>
      request.url().endsWith("/api/auth/logout") && request.method() === "POST",
  );
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await logoutRequest;
  const loginDialog = page.getByRole("dialog", { name: "登录音乐库" });
  const username = loginDialog.getByLabel("用户名", { exact: true });
  const password = loginDialog.getByLabel("密码", { exact: true });
  await expect(loginDialog).toBeVisible();
  await expect(username).toBeFocused();
  await username.press("Tab");
  await expect(password).toBeFocused();
  await password.press("Tab");
  await expect(
    loginDialog.getByRole("button", { name: "显示密码", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    loginDialog.getByRole("button", { name: "登录", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(loginDialog).toBeVisible();
  await loginDialog.locator(".login-header").click();
  for (const theme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: theme });
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({
        width,
        height: width === 1440 ? 1000 : 844,
      });
      const geometry = await loginDialog.evaluate((dialog) => {
        const card = dialog.getBoundingClientRect();
        const fields = [...dialog.querySelectorAll("input, .login-submit")].map(
          (element) => element.getBoundingClientRect(),
        );
        return {
          compact: card.width <= 408,
          insideViewport:
            card.left >= 0 &&
            card.right <= innerWidth &&
            card.bottom <= innerHeight,
          aligned: fields.every(
            (field) => Math.abs(field.width - fields[0].width) <= 1,
          ),
          noOverflow: dialog.scrollWidth <= dialog.clientWidth,
        };
      });
      assert.deepEqual(geometry, {
        compact: true,
        insideViewport: true,
        aligned: true,
        noOverflow: true,
      });
      if (width !== 320)
        await page.screenshot({
          path: `../output/test-ui-login-${theme}-${width === 1440 ? "desktop" : "mobile"}.png`,
        });
      if (theme === "light" && width === 1440) {
        const box = await loginDialog.boundingBox();
        await page.screenshot({
          path: "../output/test-ui-login-preview.png",
          clip: {
            x: box.x - 24,
            y: box.y - 24,
            width: box.width + 48,
            height: box.height + 48,
          },
        });
      }
    }
  }
  await username.fill("listener");
  await password.fill("wrong-password");
  await loginDialog.getByRole("button", { name: "显示密码" }).click();
  await expect(password).toHaveAttribute("type", "text");
  await expect(password).toHaveValue("wrong-password");
  await loginDialog.getByRole("button", { name: "隐藏密码" }).click();
  await expect(password).toHaveAttribute("type", "password");
  await password.press("Enter");
  await expect(loginDialog.getByRole("alert")).toHaveText(
    "用户名或密码错误，请检查后重试",
  );
  await expect(password).toHaveAttribute("aria-invalid", "true");
  await expect(password).toHaveAttribute("aria-describedby", "login-error");
  await page.screenshot({ path: "../output/test-ui-login-error.png" });
  await password.fill("correct-password");
  await expect(loginDialog.getByRole("alert")).toHaveCount(0);
  await password.press("Enter");
  await expect(
    loginDialog.getByRole("button", { name: "正在登录…", exact: true }),
  ).toBeDisabled();
  await expect(username).toBeDisabled();
  await expect(password).toBeDisabled();
  await loginDialog.locator("form").evaluate((form) => form.requestSubmit());
  assert.deepEqual(loginAttempts, [
    { username: "listener", password: "wrong-password" },
    { username: "listener", password: "correct-password" },
  ]);
  releaseLogin();
  await expect(loginDialog).toBeHidden();
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(loginDialog).toBeVisible();
  await expect(password).toHaveValue("");
  await expect(password).toHaveAttribute("type", "password");
  await expect(loginDialog.getByRole("alert")).toHaveCount(0);
  assert.deepEqual(errors, []);
  console.log(
    "Browser integration passed: search, real audio, lyric seeking, favorites, playlist, quality selection, queue controls, settings, responsive layout, login states and authentication.",
  );
} finally {
  await browser?.close();
  server.kill();
}
