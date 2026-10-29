import { Cover, Button, Lyrics, Modal, SongTitle } from "./components";
import { SettingsWorkspace, type SettingsTab } from "./SettingsWorkspace";
import { Navigation } from "./Navigation";
import { AIAssistant } from "./AIAssistant";
import { ThemePicker } from "./ThemePicker";
import { RuntimeLogs } from "./RuntimeLogs";
import { LibraryWorkspace } from "./LibraryWorkspace";
import { processingLabels } from "./LibrarySettings";
import { PlaylistLibrary } from "./PlaylistLibrary";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AudioLines,
  Search,
  Music2,
  ListMusic,
  Download,
  Heart,
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
  Expand,
  Plus,
  X,
  Info,
  ArrowLeft,
  ArrowRight,
  Shuffle,
  Repeat,
  LogOut,
  History,
  Trash2,
  Github,
  SlidersHorizontal,
  Eye,
  EyeOff,
  CircleAlert,
} from "lucide-react";
import { api } from "./api";
import { playbackErrorMessage } from "./playback-errors";
import { selectResults } from "./results";
import { parseLrc, clock, type LyricLine } from "./lyrics";
import type {
  Track,
  Config,
  DownloadJob,
  LibraryFile,
  SourceStatus,
  SavedPlaylist,
  PlaylistSummary,
} from "./types";

const defaultSources = [
  { id: "migu", label: "咪咕" },
  { id: "netease", label: "网易云" },
  { id: "qq", label: "QQ音乐" },
  { id: "kuwo", label: "酷我" },
  { id: "qianqian", label: "千千" },
];
const views = {
  search: ["搜索音乐", "歌曲、歌手、专辑与不同音质版本"],
  assistant: ["AI 助手", "通过对话和图片搜索音乐、管理歌单与下载入库"],
  player: ["正在播放", "歌词与播放列表"],
  import: ["歌单导入", "导入后独立保存到我的歌单"],
  playlists: ["歌单", "管理自建歌单、收藏歌曲与平台歌单导入"],
  queue: ["下载队列", "下载进度与所选音质"],
  favorites: ["我的收藏", "保存喜欢的曲目与音源"],
  files: ["音乐库", "浏览与播放本地音乐和 Navidrome 曲库"],
  organize: ["刮削整理", "补全音乐资料、审核版本并安全归档"],
  logs: ["运行日志", "实时查看搜索、下载与报错详情"],
  settings: ["设置", "音源、刮削规则、服务连接与通知"],
} as const;
type View = keyof typeof views;
const bytes = (n: number) =>
  n < 1024
    ? `${n} B`
    : n < 1048576
      ? `${(n / 1024).toFixed(1)} KB`
      : `${(n / 1048576).toFixed(1)} MB`;
export function App() {
  const [theme, setTheme] = useState<"system" | "light" | "dark">(() => {
    try {
      const saved = localStorage.getItem("melokeep-theme");
      return saved === "light" || saved === "dark" ? saved : "system";
    } catch {
      return "system";
    }
  });
  const [recentSearches, setRecentSearches] = useState<string[]>(() => {
    try {
      const saved: unknown = JSON.parse(
        localStorage.getItem("melokeep-searches") || "[]",
      );
      return Array.isArray(saved)
        ? saved.filter((v): v is string => typeof v === "string").slice(0, 8)
        : [];
    } catch {
      return [];
    }
  });
  const searchInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const system = matchMedia("(prefers-color-scheme: dark)");
    const update = () => {
      document.documentElement.dataset.theme =
        theme === "system" ? (system.matches ? "dark" : "light") : theme;
    };
    update();
    try {
      localStorage.setItem("melokeep-theme", theme);
    } catch {
      /* Storage is optional. */
    }
    system.addEventListener("change", update);
    return () => system.removeEventListener("change", update);
  }, [theme]);
  const [view, setView] = useState<View>("search"),
    [returnView, setReturnView] = useState<View>("search"),
    [query, setQuery] = useState(""),
    [tracks, setTracks] = useState<Track[]>([]),
    [searching, setSearching] = useState(false),
    [statuses, setStatuses] = useState<Record<string, SourceStatus>>({}),
    [firstMs, setFirstMs] = useState<number | null>(null);
  const [config, setConfig] = useState<Config | null>(null),
    [sourceFilter, setSourceFilter] = useState("all"),
    [filter, setFilter] = useState("all"),
    [sort, setSort] = useState("relevance"),
    [selected, setSelected] = useState<Set<string>>(new Set());
  const sources = config?.available_sources || defaultSources;
  const sourceLabel = (id: string, playlistContext = false) =>
    id === "navidrome"
      ? "Navidrome"
      : id === "custom"
        ? "自建歌单"
        : id === "local"
          ? playlistContext
            ? "自建歌单"
            : "本地音乐"
          : sources.find((s) => s.id === id)?.label || id;
  useEffect(() => {
    if (view !== "player") setReturnView(view);
  }, [view]);
  const [favorites, setFavorites] = useState<Track[]>([]),
    [playlist, setPlaylist] = useState<Track[]>([]),
    [jobs, setJobs] = useState<DownloadJob[]>([]),
    [files, setFiles] = useState<LibraryFile[]>([]);
  const [savedPlaylists, setSavedPlaylists] = useState<PlaylistSummary[]>([]),
    [activePlaylist, setActivePlaylist] = useState<SavedPlaylist | null>(null),
    [importName, setImportName] = useState("");
  const [remotePlaylists, setRemotePlaylists] = useState<PlaylistSummary[]>([]);
  const [remotePlaylistError, setRemotePlaylistError] = useState("");
  const [playlistRefresh, setPlaylistRefresh] = useState(0);
  const allPlaylists = [...savedPlaylists, ...remotePlaylists];
  const [selectedJobs, setSelectedJobs] = useState<string[]>([]);
  const [queueStatus, setQueueStatus] = useState("all");
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [libraryTab, setLibraryTab] = useState("local");
  const [processingTab, setProcessingTab] = useState("workbench");
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("engine");
  const collectionView = ["playlists", "favorites", "import"].includes(view);
  function openSettings(tab: SettingsTab = "engine") {
    setSettingsTab(tab);
    setView("settings");
  }
  const [managing, setManaging] = useState(false);
  const [managementError, setManagementError] = useState("");
  const [queueManaging, setQueueManaging] = useState(false);
  const [queueSelected, setQueueSelected] = useState<Set<string>>(new Set());
  const [queueSaving, setQueueSaving] = useState(false);
  const queueWritePending = useRef(false);
  const [confirmation, setConfirmation] = useState<{
    title: string;
    description: string;
    run: () => Promise<void>;
  } | null>(null);
  const [current, setCurrent] = useState<Track | null>(null),
    [playing, setPlaying] = useState(false),
    [loadingPlay, setLoadingPlay] = useState(false),
    [time, setTime] = useState(0),
    [duration, setDuration] = useState(0),
    [volume, setVolume] = useState(0.65),
    [shuffle, setShuffle] = useState(false),
    [repeat, setRepeat] = useState(true);
  const [lyricText, setLyricText] = useState(""),
    [lines, setLines] = useState<LyricLine[]>([]),
    [follow, setFollow] = useState(true),
    [largeLyrics, setLargeLyrics] = useState(false);
  const [notice, setNotice] = useState(""),
    [loginRequired, setLoginRequired] = useState(false),
    [loginUser, setLoginUser] = useState(""),
    [loginPass, setLoginPass] = useState(""),
    [loginError, setLoginError] = useState(""),
    [loginBusy, setLoginBusy] = useState(false),
    [showLoginPassword, setShowLoginPassword] = useState(false),
    [busy, setBusy] = useState(false);
  const [qualityTracks, setQualityTracks] = useState<Track[] | null>(null),
    [qualities, setQualities] = useState<Record<string, string>>({}),
    [showPlaylist, setShowPlaylist] = useState(false),
    [playlistModalTracks, setPlaylistModalTracks] = useState<Track[] | null>(
      null,
    ),
    [targetPlaylistId, setTargetPlaylistId] = useState(""),
    [newPlaylistName, setNewPlaylistName] = useState(""),
    [importSource, setImportSource] = useState("netease"),
    [importId, setImportId] = useState("");
  const audio = useRef<HTMLAudioElement>(null),
    playGeneration = useRef(0),
    searchGeneration = useRef(0),
    searchJob = useRef<string | null>(null),
    eventSource = useRef<EventSource | null>(null),
    startTime = useRef(0),
    currentRef = useRef<Track | null>(null),
    playbackQueue = useRef<Track[]>([]),
    playingFromQueue = useRef(false),
    bufferingRef = useRef(false),
    nextRef = useRef<() => void>(() => {});
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (loginRequired || document.querySelector("dialog[open]")) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setView("search");
        requestAnimationFrame(() => searchInput.current?.focus());
      } else if (
        event.code === "Space" &&
        !(
          event.target instanceof HTMLElement &&
          (event.target.closest(
            "input,textarea,select,button,a,summary,[role=button]",
          ) ||
            event.target.isContentEditable)
        )
      ) {
        event.preventDefault();
        const element = audio.current;
        if (currentRef.current && element) {
          if (element.paused)
            void element.play().catch((error) => {
              reportPlayback(
                currentRef.current!,
                "failed",
                "play",
                error.message,
              );
              fail(error);
            });
          else element.pause();
        }
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [loginRequired]);
  const fail = (error: unknown) =>
    setNotice(error instanceof Error ? error.message : String(error));
  async function load() {
    const [cfg, favs, list, downloads, collections] = await Promise.all([
      api<Config>("/config"),
      api<Track[]>("/favorites"),
      api<Track[]>("/playlist"),
      api<DownloadJob[]>("/downloads"),
      api<PlaylistSummary[]>("/playlists"),
    ]);
    setConfig(cfg);
    setFavorites(favs);
    setPlaylist(list);
    setJobs(downloads);
    setSavedPlaylists(collections);
  }
  useEffect(() => {
    const login = () => setLoginRequired(true);
    window.addEventListener("melokeep-login", login);
    api<{ authenticated: boolean }>("/auth/status")
      .then((status) => {
        if (status.authenticated) load().catch(fail);
        else setLoginRequired(true);
      })
      .catch(fail);
    return () => {
      window.removeEventListener("melokeep-login", login);
      eventSource.current?.close();
      if (searchJob.current)
        void api(`/search/jobs/${searchJob.current}`, "DELETE").catch(() => {});
    };
  }, []);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 6500);
    return () => clearTimeout(timer);
  }, [notice]);
  const hasActiveDownloads = jobs.some((job) =>
    ["queued", "resolving", "downloading", "enriching"].includes(job.status),
  );
  useEffect(() => {
    if (loginRequired) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let running = false;
    async function poll() {
      if (running || controller.signal.aborted) return;
      clearTimeout(timer);
      running = true;
      try {
        if (!document.hidden) {
          const next = await api<DownloadJob[]>(
            "/downloads",
            "GET",
            undefined,
            controller.signal,
          );
          if (!controller.signal.aborted)
            setJobs((previous) =>
              JSON.stringify(previous) === JSON.stringify(next)
                ? previous
                : next,
            );
        }
      } catch {
        /* The next poll recovers transient network failures. */
      } finally {
        running = false;
        if (!controller.signal.aborted)
          timer = setTimeout(
            () => void poll(),
            document.hidden ? 30000 : hasActiveDownloads ? 1500 : 15000,
          );
      }
    }
    const resume = () => {
      if (!document.hidden) void poll();
    };
    timer = setTimeout(() => void poll(), hasActiveDownloads ? 1500 : 15000);
    document.addEventListener("visibilitychange", resume);
    return () => {
      controller.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [loginRequired, hasActiveDownloads]);
  useEffect(() => {
    if (view === "files" || view === "organize")
      api<LibraryFile[]>("/files").then(setFiles).catch(fail);
  }, [view]);
  useEffect(() => {
    const element = audio.current;
    if (!element) return;
    element.volume = volume;
  }, [volume]);
  currentRef.current = current;
  const favIds = useMemo(
    () => new Set(favorites.map((t) => t.id)),
    [favorites],
  );
  const tableTracks =
    view === "favorites"
      ? favorites
      : view === "playlists"
        ? activePlaylist?.tracks || []
        : tracks;
  const display = useMemo(
    () => selectResults(tableTracks, sourceFilter, filter, false, sort),
    [tableTracks, sourceFilter, filter, sort],
  );
  const lastSearch = useRef("");
  async function search(keyword = query) {
    if (!keyword.trim() || !config) return;
    const generation = ++searchGeneration.current;
    eventSource.current?.close();
    const previousJob = searchJob.current;
    searchJob.current = null;
    setView("search");
    setQuery(keyword);
    setTracks([]);
    setSelected(new Set());
    setStatuses(
      Object.fromEntries(
        config.sources.map((id) => [id, { state: "searching" }]),
      ),
    );
    setSearching(true);
    setFirstMs(null);
    startTime.current = performance.now();
    try {
      if (previousJob) await api(`/search/jobs/${previousJob}`, "DELETE");
      if (generation !== searchGeneration.current) return;
      const { id } = await api<{ id: string }>("/search/jobs", "POST", {
        keyword,
        sources: config.sources,
        refresh: lastSearch.current === keyword.trim(),
      });
      lastSearch.current = keyword.trim();
      if (generation !== searchGeneration.current) {
        void api(`/search/jobs/${id}`, "DELETE").catch(() => {});
        return;
      }
      searchJob.current = id;
      const events = new EventSource(`/api/search/jobs/${id}/events`, {
        withCredentials: true,
      });
      eventSource.current = events;
      const receive = (event: MessageEvent) => {
        if (generation !== searchGeneration.current) return;
        const track: Track = JSON.parse(event.data);
        setTracks((previous) => {
          const index = previous.findIndex((t) => t.id === track.id);
          if (index === -1) return [...previous, track];
          const next = [...previous];
          next[index] = track;
          return next;
        });
        setFirstMs(
          (previous) =>
            previous ?? Math.round(performance.now() - startTime.current),
        );
      };
      events.addEventListener("candidate", receive as EventListener);
      events.addEventListener("track", receive as EventListener);
      events.addEventListener("source", (event) => {
        if (generation !== searchGeneration.current) return;
        const value = JSON.parse((event as MessageEvent).data);
        setStatuses((previous) => ({ ...previous, [value.id]: value.status }));
      });
      const finish = (detail = "本次搜索已结束，音源未返回结果") => {
        if (generation !== searchGeneration.current) return;
        setSearching(false);
        searchJob.current = null;
        eventSource.current = null;
        setStatuses((previous) =>
          Object.fromEntries(
            Object.entries(previous).map(([id, status]) => [
              id,
              status.state === "searching"
                ? { state: "stopped", detail }
                : status,
            ]),
          ),
        );
        events.close();
      };
      events.addEventListener("done", () => finish());
      events.addEventListener("error", (event) => {
        if (generation !== searchGeneration.current) return;
        const detail =
          "data" in event
            ? JSON.parse(String(event.data)).detail
            : "搜索连接已断开，请重新搜索";
        finish(detail);
        setNotice(detail);
        void api(`/search/jobs/${id}`, "DELETE").catch(() => {});
      });
    } catch (error) {
      if (generation === searchGeneration.current) {
        setSearching(false);
        fail(error);
      }
    }
  }
  function reportPlayback(
    track: Track,
    event: "started" | "failed" | "stalled" | "recovered",
    stage: "prepare" | "format" | "play" | "media" | "buffer",
    detail = "",
  ) {
    const element = audio.current;
    void api("/playback/events", "POST", {
      track_id: track.id,
      event,
      stage,
      detail: detail.slice(0, 2000),
      code: element?.error?.code || 0,
      network_state: element?.networkState || 0,
      ready_state: element?.readyState || 0,
      position: Math.max(
        0,
        Number.isFinite(element?.currentTime) ? element!.currentTime : 0,
      ),
      browser: navigator.userAgent.slice(0, 300),
    }).catch(() => {});
  }
  async function play(
    track: Track,
    context: Track[] = [track],
    fromQueue = false,
  ) {
    playbackQueue.current = context;
    playingFromQueue.current = fromQueue;
    const generation = ++playGeneration.current;
    audio.current?.pause();
    // load() can discard the queued pause event; keep failed preparation in sync.
    setPlaying(false);
    audio.current?.removeAttribute("src");
    audio.current?.load();
    currentRef.current = track;
    bufferingRef.current = false;
    setCurrent(track);
    setLoadingPlay(true);
    setLyricText("正在获取歌词…");
    setLines([]);
    setTime(0);
    setDuration(track.duration);
    void api<{ text: string }>(`/tracks/${track.id}/lyrics`)
      .then(({ text }) => {
        if (generation !== playGeneration.current) return;
        const parsed = parseLrc(text);
        setLines(parsed);
        setLyricText(parsed.length ? "" : text || "此音源暂无歌词");
      })
      .catch((error) => {
        if (generation === playGeneration.current)
          setLyricText(error instanceof Error ? error.message : "歌词加载失败");
      });
    let stage: "prepare" | "format" | "play" = "prepare";
    try {
      const prepared = await api<Track>(`/tracks/${track.id}/playback`, "POST");
      if (generation !== playGeneration.current) return false;
      setCurrent(prepared);
      setTracks((previous) =>
        previous.map((item) => (item.id === prepared.id ? prepared : item)),
      );
      if (prepared.playback.state !== "ready" || !prepared.playback.url)
        throw new Error(
          prepared.playback.detail || "曲目暂不可试听，请更换音源",
        );
      const element = audio.current!;
      stage = "format";
      const mediaType: { [key: string]: string } = {
        flac: "audio/flac",
        mp3: "audio/mpeg",
        m4a: "audio/mp4",
        ogg: "audio/ogg",
        wav: "audio/wav",
        opus: "audio/ogg;codecs=opus",
        aac: "audio/aac",
        mp4: "audio/mp4",
      };
      if (
        prepared.playback.codec &&
        !element.canPlayType(mediaType[prepared.playback.codec] || "")
      )
        throw new Error(
          prepared.source === "local"
            ? "浏览器不支持该音频格式，可以下载到本机后播放"
            : "浏览器不支持该试听格式，请选择其他音源",
        );
      element.src = prepared.playback.url;
      element.load();
      stage = "play";
      await element.play();
      return true;
    } catch (error) {
      if (generation === playGeneration.current) {
        const message = playbackErrorMessage(error);
        if (!message) return false;
        reportPlayback(
          track,
          "failed",
          stage,
          error instanceof Error
            ? `${error.name}: ${error.message}`
            : String(error),
        );
        setNotice(message);
      }
      return false;
    } finally {
      if (generation === playGeneration.current) setLoadingPlay(false);
    }
  }
  async function playSequence(
    index: number,
    list: Track[],
    fromQueue: boolean,
    direction = 1,
  ) {
    // Try each entry at most once; an unavailable song must not block the queue.
    for (let attempted = 0; attempted < list.length; attempted++) {
      const generation = playGeneration.current + 1;
      if (await play(list[index], list, fromQueue)) return;
      if (generation !== playGeneration.current) return;
      index += direction;
      if (index < 0 || index >= list.length) {
        if (!repeat) return;
        index = (index + list.length) % list.length;
      }
    }
  }
  function seek(seconds: number) {
    if (audio.current?.src && audio.current.readyState > 0) {
      audio.current.currentTime = Math.min(
        seconds,
        audio.current.duration || duration,
      );
      setTime(seconds);
    }
  }
  async function toggle() {
    if (!current) return;
    if (audio.current?.paused) {
      if (!audio.current.src) {
        await play(current, playbackQueue.current, playingFromQueue.current);
        return;
      }
      await audio.current.play().catch((error) => {
        const message = playbackErrorMessage(error);
        if (!message) return;
        reportPlayback(
          current,
          "failed",
          "play",
          `${error.name}: ${error.message}`,
        );
        setNotice(message);
      });
    } else audio.current?.pause();
  }
  function step(direction: number) {
    const list = playingFromQueue.current ? playlist : playbackQueue.current;
    if (!list.length) return;
    const index = list.findIndex((t) => t.id === current?.id);
    let next = shuffle
      ? Math.floor(Math.random() * list.length)
      : index + direction;
    if (next >= list.length) {
      if (!repeat) return;
      next = 0;
    }
    if (next < 0) next = list.length - 1;
    void playSequence(next, list, playingFromQueue.current, direction);
  }
  nextRef.current = () => step(1);
  async function favorite(track: Track) {
    try {
      const exists = favIds.has(track.id);
      await api(`/favorites/${track.id}`, exists ? "DELETE" : "PUT");
      setFavorites((previous) =>
        exists
          ? previous.filter((t) => t.id !== track.id)
          : [track, ...previous],
      );
    } catch (error) {
      fail(error);
    }
  }
  async function savePlaybackQueue(next: Track[]) {
    if (queueWritePending.current) {
      setNotice("播放列表正在保存，请稍后再试");
      return false;
    }
    queueWritePending.current = true;
    setQueueSaving(true);
    try {
      await api(
        "/playlist",
        "PUT",
        next.map((t) => t.id),
      );
      setPlaylist(next);
      return true;
    } finally {
      queueWritePending.current = false;
      setQueueSaving(false);
    }
  }
  async function addToPlaylist(items: Track[]) {
    try {
      const next = [
        ...playlist,
        ...items.filter((t) => !playlist.some((p) => p.id === t.id)),
      ].slice(0, 1000);
      if (!(await savePlaybackQueue(next))) return;
      setNotice(`已加入播放列表，共 ${next.length} 首`);
    } catch (error) {
      fail(error);
    }
  }
  async function removeFromPlaylist(ids: string[]) {
    const removed = new Set(ids);
    const next = playlist.filter((t) => !removed.has(t.id));
    try {
      if (!(await savePlaybackQueue(next))) return;
      setQueueSelected(new Set());
      if (!next.length) setQueueManaging(false);
      setNotice(
        `已从播放列表移除 ${playlist.length - next.length} 首，音乐文件保留`,
      );
    } catch (error) {
      fail(error);
    }
  }
  async function chooseDownload(items: Track[]) {
    if (items.some((track) => track.source === "navidrome")) {
      setNotice("Navidrome 已提供原文件，可通过曲目旁的下载按钮保存到本机。");
      return;
    }
    if (items.some((track) => track.source === "local")) {
      setNotice("歌曲已在音乐库中，可在音乐文件页下载到本机");
      return;
    }
    if (!items.length) {
      setNotice("请先选择曲目");
      return;
    }
    try {
      if (items.some((t) => !t.qualities.length))
        setNotice("正在确认可下载音质…");
      const prepared: Track[] = [];
      for (let offset = 0; offset < items.length; offset += 4) {
        prepared.push(
          ...(await Promise.all(
            items
              .slice(offset, offset + 4)
              .map((t) =>
                t.qualities.length
                  ? t
                  : api<Track>(`/tracks/${t.id}/versions`, "POST"),
              ),
          )),
        );
      }
      items = prepared;
      const resolved = new Map(items.map((t) => [t.id, t]));
      setTracks((previous) => previous.map((t) => resolved.get(t.id) || t));
      setFavorites((previous) => previous.map((t) => resolved.get(t.id) || t));
      setCurrent((previous) =>
        previous ? resolved.get(previous.id) || previous : null,
      );
    } catch (error) {
      fail(error);
      return;
    }
    setQualityTracks(items);
    setQualities(
      Object.fromEntries(
        items.map((t) => [
          t.id,
          t.qualities.find((q) => q.lossless)?.id || t.qualities[0]?.id || "",
        ]),
      ),
    );
  }
  async function download() {
    if (!qualityTracks) return;
    setBusy(true);
    let queued = 0;
    try {
      for (let offset = 0; offset < qualityTracks.length; offset += 200) {
        const created = await api<DownloadJob[]>(
          "/downloads",
          "POST",
          qualityTracks.slice(offset, offset + 200).map((track) => ({
            track_id: track.id,
            quality_id: qualities[track.id],
          })),
        );
        queued += created.length;
        setJobs((previous) => [...created, ...previous]);
      }
      setQualityTracks(null);
      setNotice(`已加入 ${queued} 首下载任务`);
    } catch (error) {
      if (queued) setQualityTracks(qualityTracks.slice(queued));
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  async function importList() {
    setBusy(true);
    try {
      const id = importId.trim();
      const result = await api<{ playlist: SavedPlaylist; detail: string }>(
        "/playlist/import",
        "POST",
        { source: importSource, id, name: importName.trim() },
      );
      setActivePlaylist(result.playlist);
      resetCollectionFilters();
      setView("playlists");
      setNotice(result.detail);
      setImportId("");
      setImportName("");
      await refreshPlaylists();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  function resetCollectionFilters() {
    setSourceFilter("all");
    setFilter("all");
    setSort("relevance");
    setSelected(new Set());
  }
  async function refreshPlaylists() {
    setSavedPlaylists(await api<PlaylistSummary[]>("/playlists"));
  }
  const remotePlaylistId =
    activePlaylist?.source === "navidrome" ? activePlaylist.id : null;
  useEffect(() => {
    if (view !== "playlists" || loginRequired || !config) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function sync() {
      try {
        const lists = await api<PlaylistSummary[]>(
          "/navidrome/playlists",
          "GET",
          undefined,
          abort.signal,
        );
        if (!abort.signal.aborted) {
          setRemotePlaylists(lists);
          setRemotePlaylistError("");
          if (remotePlaylistId) {
            if (lists.some((list) => list.id === remotePlaylistId)) {
              const updated = await api<SavedPlaylist>(
                `/navidrome/playlists/${encodeURIComponent(remotePlaylistId.slice(10))}`,
                "GET",
                undefined,
                abort.signal,
              );
              if (!abort.signal.aborted)
                setActivePlaylist((current) =>
                  current?.id === remotePlaylistId ? updated : current,
                );
            } else {
              setActivePlaylist((current) =>
                current?.id === remotePlaylistId ? null : current,
              );
            }
          }
        }
      } catch (error) {
        if (!abort.signal.aborted)
          setRemotePlaylistError((error as Error).message);
      } finally {
        if (!abort.signal.aborted) timer = setTimeout(() => void sync(), 60000);
      }
    }
    void sync();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, [view, loginRequired, !!config, playlistRefresh, remotePlaylistId]);
  function openAddToPlaylistModal(items: Track[]) {
    setPlaylistModalTracks(items);
    setTargetPlaylistId(items.length ? savedPlaylists[0]?.id || "new" : "new");
    setNewPlaylistName("");
    if (items.every((track) => track.source === "navidrome"))
      void api<PlaylistSummary[]>("/navidrome/playlists")
        .then(setRemotePlaylists)
        .catch(fail);
  }
  async function submitAddToSavedPlaylist() {
    if (!playlistModalTracks) return;
    setBusy(true);
    try {
      const track_ids = playlistModalTracks.map((t) => t.id);
      let updated: SavedPlaylist;
      if (
        targetPlaylistId === "new-navidrome" ||
        targetPlaylistId.startsWith("navidrome:")
      ) {
        if (playlistModalTracks.some((track) => track.source !== "navidrome"))
          throw new Error(
            "Navidrome 歌单只能加入已经在 Navidrome 曲库中的歌曲",
          );
        const creating = targetPlaylistId === "new-navidrome";
        updated = await api<SavedPlaylist>(
          creating
            ? "/navidrome/playlists"
            : `/navidrome/playlists/${encodeURIComponent(targetPlaylistId.slice(10))}/tracks`,
          "POST",
          {
            ...(creating ? { name: newPlaylistName.trim() } : {}),
            song_ids: playlistModalTracks.map((track) => track.source_id),
          },
        );
        setRemotePlaylists(
          await api<PlaylistSummary[]>("/navidrome/playlists"),
        );
        setPlaylistRefresh((value) => value + 1);
      } else if (targetPlaylistId === "new") {
        const name = newPlaylistName.trim();
        if (!name) {
          setNotice("请输入新歌单名称");
          return;
        }
        updated = await api<SavedPlaylist>("/playlists", "POST", {
          name,
          track_ids,
        });
      } else {
        updated = await api<SavedPlaylist>(
          `/playlists/${targetPlaylistId}/tracks`,
          "POST",
          { track_ids },
        );
      }
      await refreshPlaylists();
      if (activePlaylist?.id === updated.id || !playlistModalTracks.length) {
        setActivePlaylist(updated);
        resetCollectionFilters();
        setView("playlists");
      }
      setPlaylistModalTracks(null);
      setNewPlaylistName("");
      setNotice(updated.detail || `已加入歌单“${updated.name}”`);
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  async function openPlaylist(id: string) {
    try {
      setActivePlaylist(
        await api<SavedPlaylist>(
          id.startsWith("navidrome:")
            ? `/navidrome/playlists/${encodeURIComponent(id.slice(10))}`
            : `/playlists/${encodeURIComponent(id)}`,
        ),
      );
      resetCollectionFilters();
    } catch (error) {
      fail(error);
    }
  }
  async function playCollection(items: Track[]) {
    if (!items.length) {
      setNotice("此歌单暂无曲目");
      return;
    }
    try {
      if (!(await savePlaybackQueue(items))) return;
      await playSequence(0, items, true);
    } catch (error) {
      fail(error);
    }
  }
  async function removeCollectionTrack(track: Track) {
    if (!activePlaylist || activePlaylist.read_only) return;
    const currentList = activePlaylist;
    if (currentList.source === "navidrome") {
      if (track.playlist_index === undefined || !currentList.revision) {
        setNotice("请先同步歌单，再移除歌曲");
        return;
      }
      setManagementError("");
      setConfirmation({
        title: "从 Navidrome 歌单移除歌曲",
        description: `从“${currentList.name}”移除“${track.title}”？此操作同步到 Navidrome，音乐文件会保留。`,
        run: async () => {
          setManaging(true);
          try {
            const updated = await api<SavedPlaylist>(
              `/navidrome/playlists/${encodeURIComponent(currentList.id.slice(10))}/tracks/remove`,
              "POST",
              {
                indexes: [track.playlist_index],
                revision: currentList.revision,
              },
            );
            setActivePlaylist((current) =>
              current?.id === updated.id ? updated : current,
            );
            setSelected(
              (previous) =>
                new Set([...previous].filter((id) => id !== track.id)),
            );
            setRemotePlaylists(
              await api<PlaylistSummary[]>("/navidrome/playlists"),
            );
            setConfirmation(null);
            setNotice("已从 Navidrome 歌单移除，音乐文件保留");
          } catch (error) {
            setManagementError((error as Error).message);
          } finally {
            setManaging(false);
          }
        },
      });
      return;
    }
    try {
      setActivePlaylist(
        await api<SavedPlaylist>(
          `/playlists/${activePlaylist.id}/tracks/${track.id}`,
          "DELETE",
        ),
      );
      setSelected(
        (previous) => new Set([...previous].filter((s) => s !== track.id)),
      );
      await refreshPlaylists();
    } catch (error) {
      fail(error);
    }
  }
  const selection = tableTracks.filter((t) => selected.has(t.id));
  const selectedToggle = (id: string) =>
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const statusLabels: Record<string, string> = {
    queued: "等待下载",
    resolving: "验证资源",
    downloading: "正在下载",
    enriching: "保存标签与歌词",
    complete: "已完成",
    failed: "失败",
    paused: "已暂停",
    cancelled: "已取消",
  };
  const visibleJobs = jobs.filter(
    (job) => queueStatus === "all" || job.status === queueStatus,
  );
  const chosenJobs = visibleJobs.filter((job) => selectedJobs.includes(job.id));
  const stopped = (job: DownloadJob) =>
    ["complete", "failed", "paused", "cancelled"].includes(job.status);
  async function manageJobs(action: string, targets: DownloadJob[]) {
    setManaging(true);
    setManagementError("");
    try {
      for (const job of targets) {
        await api(
          action === "remove"
            ? `/downloads/${job.id}`
            : `/downloads/${job.id}/${action === "resume" && job.status === "cancelled" ? "retry" : action}`,
          action === "remove" ? "DELETE" : "POST",
        );
        if (action === "remove")
          setSelectedJobs((previous) => previous.filter((id) => id !== job.id));
      }
      setNotice(
        action === "remove"
          ? "下载记录已移除，已下载文件保留"
          : "下载任务已更新",
      );
      setConfirmation(null);
    } catch (error) {
      setManagementError((error as Error).message);
      setConfirmation(null);
    } finally {
      await api<DownloadJob[]>("/downloads").then(setJobs).catch(fail);
      setManaging(false);
    }
  }
  function confirmRemoval(targets: DownloadJob[]) {
    setManagementError("");
    setConfirmation({
      title: "移除下载记录",
      description: `移除 ${targets.length} 条记录及未完成的临时文件。已下载的音乐文件会保留。`,
      run: () => manageJobs("remove", targets),
    });
  }
  function confirmFileDeletion(targets: LibraryFile[]) {
    setManagementError("");
    setConfirmation({
      title: "删除音乐文件",
      description: `将从音乐库所在磁盘永久删除 ${targets.length} 个文件，无法撤销。${targets
        .slice(0, 3)
        .map((file) => file.name)
        .join("、")}${targets.length > 3 ? "…" : ""}`,
      run: async () => {
        setManaging(true);
        try {
          for (const file of targets) {
            await api(`/files?path=${encodeURIComponent(file.path)}`, "DELETE");
            if (file.track) {
              playbackQueue.current = playbackQueue.current.filter(
                (track) => track.id !== file.track!.id,
              );
              setPlaylist((previous) =>
                previous.filter((track) => track.id !== file.track!.id),
              );
              setFavorites((previous) =>
                previous.filter((track) => track.id !== file.track!.id),
              );
              if (current?.id === file.track.id) {
                ++playGeneration.current;
                audio.current?.pause();
                audio.current?.removeAttribute("src");
                audio.current?.load();
                setCurrent(null);
                setLoadingPlay(false);
              }
            }
            setSelectedFiles((previous) =>
              previous.filter((path) => path !== file.path),
            );
          }
          setConfirmation(null);
          setNotice("音乐文件已删除");
        } catch (error) {
          setManagementError((error as Error).message);
          setConfirmation(null);
        } finally {
          await api<LibraryFile[]>("/files").then(setFiles).catch(fail);
          await api<DownloadJob[]>("/downloads").then(setJobs).catch(fail);
          setManaging(false);
        }
      },
    });
  }
  const playbackLabel =
    current?.playback.state === "ready"
      ? `${current.playback.preview_only ? "片段试听 · " : ""}${current.playback.codec?.toUpperCase()}${current.playback.bitrate ? ` ${current.playback.bitrate} kbps` : ""}`
      : loadingPlay
        ? "正在准备试听"
        : current?.playback.detail || "尚未播放";
  const queueSelection = playlist.filter((track) =>
    queueSelected.has(track.id),
  );
  function toggleQueueSelection(id: string) {
    setQueueSelected((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  const listContent = (
    <div className="playback-list" aria-busy={queueSaving}>
      {!!playlist.length && (
        <div className="playback-list-toolbar">
          <span aria-live="polite">
            {queueManaging
              ? `已选 ${queueSelection.length} / ${playlist.length} 首`
              : `共 ${playlist.length} 首`}
          </span>
          <button
            disabled={queueSaving}
            aria-pressed={queueManaging}
            onClick={() => {
              setQueueManaging(!queueManaging);
              setQueueSelected(new Set());
            }}
          >
            {queueManaging ? "完成" : "批量管理"}
          </button>
        </div>
      )}
      {queueManaging && !!playlist.length && (
        <>
          <div className="playback-list-toolbar playback-list-actions">
            <label className="playback-list-select">
              <input
                type="checkbox"
                aria-label="全选播放列表"
                checked={queueSelection.length === playlist.length}
                ref={(input) => {
                  if (input)
                    input.indeterminate =
                      queueSelection.length > 0 &&
                      queueSelection.length < playlist.length;
                }}
                disabled={queueSaving}
                onChange={(event) =>
                  setQueueSelected(
                    new Set(
                      event.target.checked ? playlist.map((t) => t.id) : [],
                    ),
                  )
                }
              />
              全选
            </label>
            <button
              className="playback-list-remove"
              disabled={queueSaving || !queueSelection.length}
              onClick={() =>
                void removeFromPlaylist(queueSelection.map((track) => track.id))
              }
            >
              <Trash2 aria-hidden="true" />
              {queueSaving
                ? "正在移除…"
                : `移除所选（${queueSelection.length}）`}
            </button>
          </div>
          <p className="playback-list-hint">仅从播放列表移除，保留音乐文件。</p>
        </>
      )}
      <div className="playlist-items">
        {playlist.length ? (
          playlist.map((track) => (
            <div
              className={`playlist-item ${current?.id === track.id ? "active" : ""}`}
              key={track.id}
            >
              {queueManaging && (
                <label className="playback-list-select">
                  <input
                    type="checkbox"
                    aria-label={`选择待播曲目 ${track.title}`}
                    checked={queueSelected.has(track.id)}
                    disabled={queueSaving}
                    onChange={() => toggleQueueSelection(track.id)}
                  />
                </label>
              )}
              <button
                className="playlist-song"
                disabled={queueManaging && queueSaving}
                aria-label={
                  queueManaging ? `切换选择 ${track.title}` : undefined
                }
                aria-pressed={
                  queueManaging ? queueSelected.has(track.id) : undefined
                }
                onClick={() =>
                  queueManaging
                    ? toggleQueueSelection(track.id)
                    : void play(track, playlist, true)
                }
              >
                <Cover track={track} />
                <span>
                  <strong>{track.title}</strong>
                  <small>{track.artist}</small>
                </span>
              </button>
              {!queueManaging && (
                <Button
                  label={`移除 ${track.title}`}
                  disabled={queueSaving}
                  onClick={() => void removeFromPlaylist([track.id])}
                >
                  <X />
                </Button>
              )}
            </div>
          ))
        ) : (
          <p className="empty">选择搜索结果，加入待播列表。</p>
        )}
      </div>
    </div>
  );
  const lyricContent = (
    <Lyrics
      lines={lines}
      text={lyricText}
      time={time}
      onSeek={seek}
      follow={follow}
    />
  );
  const volumeControl = (
    <div className="player-extras">
      <Button
        label={volume ? "静音" : "取消静音"}
        active={volume === 0}
        onClick={() => setVolume((v) => (v ? 0 : 0.65))}
      >
        {volume ? <Volume2 /> : <VolumeX />}
      </Button>
      <input
        type="range"
        min="0"
        max="1"
        step=".01"
        value={volume}
        style={
          {
            "--progress": `${Math.round(volume * 100)}%`,
          } as React.CSSProperties
        }
        onChange={(e) => setVolume(Number(e.target.value))}
        aria-label="音量"
        aria-valuetext={`${Math.round(volume * 100)}%`}
      />
      <span className="volume-value" aria-hidden="true">
        {Math.round(volume * 100)}%
      </span>
    </div>
  );
  const trackTable = (
    <>
      <section className="results">
        <div className="result-tools">
          <strong>
            {view === "favorites"
              ? "收藏曲目"
              : view === "playlists"
                ? "歌单曲目"
                : "搜索结果"}{" "}
            <span>{display.length}</span>
          </strong>
          <div className="filter-group" role="group" aria-label="音质筛选">
            {[
              ["all", "全部"],
              ["lossless", "仅无损"],
              ["lossy", "普通音质"],
              ["mp3", "MP3"],
              ["unknown", "音质未知"],
            ].map(([id, label]) => (
              <button
                key={id}
                className={filter === id ? "active" : ""}
                aria-pressed={filter === id}
                onClick={() => setFilter(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <select
            aria-label="结果排序"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            <option value="relevance">
              {view === "playlists"
                ? "歌单曲序"
                : view === "favorites"
                  ? "收藏顺序"
                  : "相关度"}
            </option>
            <option value="name">曲名</option>
            <option value="artist">歌手</option>
            <option value="source">音源</option>
            <option value="size-desc">大小：大到小</option>
            <option value="size-asc">大小：小到大</option>
            <option value="quality-desc">品质：高到低</option>
            <option value="quality-asc">品质：低到高</option>
            <option value="duration-asc">时长：短到长</option>
            <option value="duration-desc">时长：长到短</option>
          </select>
        </div>
        <table className="track-table">
          <thead>
            <tr>
              <th>
                <input
                  aria-label="全选当前结果"
                  type="checkbox"
                  checked={
                    display.length > 0 &&
                    display.every((t) => selected.has(t.id))
                  }
                  onChange={(e) =>
                    setSelected(
                      e.target.checked
                        ? new Set(display.map((t) => t.id))
                        : new Set(),
                    )
                  }
                />
              </th>
              <th>曲目 / 专辑</th>
              <th>音源</th>
              <th>曲目版本</th>
              <th>大小</th>
              <th>时长</th>
              <th>收藏</th>
              <th>播放</th>
              <th>下载</th>
              <th>待播</th>
              {view === "playlists" && !activePlaylist?.read_only && (
                <th>移出</th>
              )}
            </tr>
          </thead>
          <tbody>
            {display.map((track, index) => (
              <tr
                key={`${track.id}:${index}`}
                className={`${selected.has(track.id) ? "selected" : ""} ${current?.id === track.id ? "current" : ""}`}
              >
                <td>
                  <input
                    type="checkbox"
                    aria-label={`选择 ${track.title}`}
                    checked={selected.has(track.id)}
                    onChange={() => selectedToggle(track.id)}
                  />
                </td>
                <td>
                  <div className="track">
                    <Cover
                      track={track}
                      onPlay={() => void play(track, display)}
                    />
                    <div className="song-copy">
                      <SongTitle
                        className="song-name"
                        track={track}
                        onPlay={() => void play(track, display)}
                      />
                      {!!track.episodes && (
                        <button
                          className="text-button"
                          onClick={() => {
                            void api<Track[]>(`/tracks/${track.id}/episodes`)
                              .then((items) => {
                                setTracks(items);
                                setSelected(new Set());
                                setView("search");
                              })
                              .catch(fail);
                          }}
                        >
                          展开 {track.episodes} 个分集
                        </button>
                      )}
                      <div
                        className="song-meta"
                        title={`${track.artist} / ${track.album}`}
                      >
                        {track.artist} / {track.album || "未知专辑"}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="track-source" data-label="音源">
                  {sourceLabel(track.source)}
                </td>
                <td className="track-versions" data-label="曲目版本">
                  {track.source === "navidrome" ? (
                    <span className="badge">
                      {track.playback.codec?.toUpperCase() || "原格式"}
                    </span>
                  ) : (
                    <button
                      className="quality"
                      aria-label={`选择 ${track.title} 下载版本`}
                      onClick={() => chooseDownload([track])}
                    >
                      {track.qualities.map((q) => (
                        <span
                          className={`badge ${q.lossless ? "flac" : ""}`}
                          title={
                            q.evidence === "engine"
                              ? "原音源解析器返回的实际版本"
                              : `${q.availability === "login_required" ? "需要登录 · " : ""}音源标注，下载前验证`
                          }
                          key={q.id}
                        >
                          {q.label}
                        </span>
                      ))}
                      {!track.qualities.length && (
                        <span className="badge pending">音质待确认</span>
                      )}
                    </button>
                  )}
                </td>
                <td className="track-size" data-label="大小">
                  {track.size_bytes != null
                    ? bytes(track.size_bytes)
                    : track.size_label || "未知"}
                </td>
                <td className="duration" data-label="时长">
                  {track.duration ? clock(track.duration) : "—"}
                </td>
                <td className="track-action">
                  <button
                    className={`icon-button favorite ${favIds.has(track.id) ? "on" : ""}`}
                    aria-label={`收藏 ${track.title}`}
                    title={favIds.has(track.id) ? "取消收藏" : "收藏"}
                    aria-pressed={favIds.has(track.id)}
                    onClick={() => void favorite(track)}
                  >
                    <Heart />
                    <span>收藏</span>
                  </button>
                </td>
                <td className="track-action">
                  <button
                    className="row-play"
                    aria-label={`播放 ${track.title}`}
                    title="播放"
                    onClick={() => void play(track, display)}
                  >
                    <Play />
                    <span>播放</span>
                  </button>
                </td>
                <td className="track-action">
                  {track.source === "navidrome" ? (
                    <a
                      className="icon-button"
                      aria-label={`下载 ${track.title}`}
                      title="下载 Navidrome 原文件"
                      href={`/api/navidrome/stream/${encodeURIComponent(track.source_id)}`}
                      download={`${track.title}.${track.playback.codec || "audio"}`}
                    >
                      <Download />
                      <span>下载</span>
                    </a>
                  ) : (
                    <button
                      className="icon-button"
                      aria-label={`下载 ${track.title}`}
                      title="下载"
                      onClick={() => chooseDownload([track])}
                    >
                      <Download />
                      <span>下载</span>
                    </button>
                  )}
                </td>
                <td className="track-action">
                  <button
                    className="icon-button"
                    aria-label={`加入播放列表 ${track.title}`}
                    title="加入待播"
                    onClick={() => void addToPlaylist([track])}
                  >
                    <Plus />
                    <span>加入待播</span>
                  </button>
                </td>
                {view === "playlists" && !activePlaylist?.read_only && (
                  <td className="track-action">
                    <Button
                      label={`移出歌单 ${track.title}`}
                      onClick={() => void removeCollectionTrack(track)}
                    >
                      <Trash2 />
                      <span>移出歌单</span>
                    </Button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {!display.length && (
          <div className="empty">
            {view === "search" && searching
              ? "正在搜索，结果将逐步显示…"
              : view === "favorites"
                ? "还没有收藏，点击曲目旁的爱心保存。"
                : tableTracks.length
                  ? "没有符合筛选条件的曲目。"
                  : view === "playlists"
                    ? "歌单暂无可用曲目，可在上方查看未导入原因。"
                    : "输入歌曲、歌手或专辑开始搜索。"}
          </div>
        )}
      </section>
      <div className="result-foot">
        <Info />
        {view === "playlists" && activePlaylist?.source === "navidrome"
          ? "曲库音质由服务器音频文件直接提供"
          : "音源标注的音质将在下载前验证"}
        <span>
          {view !== "search"
            ? ""
            : firstMs !== null
              ? `首个结果 ${(firstMs / 1000).toFixed(2)} 秒`
              : searching
                ? "正在准备试听资源"
                : ""}
        </span>
      </div>
      <div className="selection-bar">
        <span>
          已选择 <b>{selection.length}</b> 首
        </span>
        <div>
          <button onClick={() => setSelected(new Set())}>取消选择</button>
          <button
            className="secondary"
            aria-label="加入播放列表"
            disabled={!selection.length}
            onClick={() => void addToPlaylist(selection)}
          >
            <Plus />
            加入待播
          </button>
          <button
            className="secondary"
            disabled={!selection.length}
            onClick={() => openAddToPlaylistModal(selection)}
          >
            <ListMusic />
            加入歌单
          </button>
          <button
            className="primary"
            disabled={!selection.length}
            onClick={() => chooseDownload(selection)}
          >
            <Download />
            批量下载
          </button>
        </div>
      </div>
    </>
  );
  return (
    <>
      <audio
        ref={audio}
        preload="none"
        onTimeUpdate={() => setTime(audio.current?.currentTime || 0)}
        onDurationChange={() =>
          setDuration(
            Number.isFinite(audio.current?.duration)
              ? audio.current!.duration
              : currentRef.current?.duration || 0,
          )
        }
        onPlay={() => setPlaying(true)}
        onPlaying={() => {
          if (currentRef.current)
            reportPlayback(
              currentRef.current,
              bufferingRef.current ? "recovered" : "started",
              bufferingRef.current ? "buffer" : "play",
            );
          bufferingRef.current = false;
        }}
        onStalled={() => {
          if (
            currentRef.current &&
            audio.current?.getAttribute("src") &&
            !bufferingRef.current
          ) {
            bufferingRef.current = true;
            reportPlayback(
              currentRef.current,
              "stalled",
              "buffer",
              "浏览器未能继续获取音频，等待网络恢复",
            );
          }
        }}
        onPause={() => setPlaying(false)}
        onEnded={() => nextRef.current()}
        onError={() => {
          if (!audio.current?.getAttribute("src") || !currentRef.current)
            return;
          const code = audio.current.error?.code || 0;
          const reason =
            (
              {
                1: "播放请求被中止",
                2: "音频网络请求失败或传输中断",
                3: "音频解码失败，内容损坏或编码不支持",
                4: "音频地址不可用或浏览器不支持该格式",
              } as Record<number, string>
            )[code] || "未知媒体错误";
          reportPlayback(
            currentRef.current,
            "failed",
            "media",
            `${reason}；${audio.current.error?.message || "浏览器未提供更多信息"}`,
          );
          setLoadingPlay(false);
          setPlaying(false);
          setNotice(`${reason}，请查看运行日志或重新试听`);
        }}
      />
      <div className="app">
        <aside className="sidebar">
          <div className="brand">
            <AudioLines />
            MeloKeep
          </div>
          <div className="sidebar-capsules">
            <Navigation
              active={collectionView ? "playlists" : view}
              change={(name) => {
                setView(name);
                if (name === "playlists")
                  setPlaylistRefresh((value) => value + 1);
                setSourceFilter("all");
                setSelected(new Set());
              }}
              downloads={
                jobs.filter(
                  (job) => !["complete", "cancelled"].includes(job.status),
                ).length
              }
            />
          </div>
          <div className="sidebar-bottom">
            <a
              className="icon-button project-link"
              href="https://github.com/Agonie0v0/melokeep"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="项目地址（在新标签页打开）"
              title="GitHub 项目地址"
            >
              <Github aria-hidden="true" />
            </a>
            <ThemePicker theme={theme} change={setTheme} />
            <button
              className="icon-button nav-order-toggle"
              aria-label="调整导航顺序"
              title="调整导航顺序"
              popoverTarget="navigation-order"
            >
              <SlidersHorizontal aria-hidden="true" />
            </button>
            {current && (
              <button
                className="sidebar-record"
                onClick={() => setView("player")}
              >
                <Cover track={current} />
                <span>
                  <strong>{current.title}</strong>
                  <small>{current.artist}</small>
                </span>
                <AudioLines />
              </button>
            )}
            <div className="user">
              <span className="avatar">
                <Music2 />
              </span>
              <span>
                本地音乐库
                <small>
                  {favorites.length} 首收藏 · {playlist.length} 首待播
                </small>
              </span>
            </div>
            <button
              className="icon-button logout"
              aria-label="退出登录"
              title="退出登录"
              onClick={() =>
                void api("/auth/logout", "POST")
                  .then(() => api<{ required: boolean }>("/auth/status"))
                  .then((s) => s.required && setLoginRequired(true))
                  .catch(fail)
              }
            >
              <LogOut aria-hidden="true" />
            </button>
          </div>
        </aside>
        <main className="workspace">
          {view !== "search" && view !== "player" && (
            <header className="top">
              <div>
                <h1>{collectionView ? views.playlists[0] : views[view][0]}</h1>
                <p>{collectionView ? views.playlists[1] : views[view][1]}</p>
              </div>
            </header>
          )}
          {collectionView && (
            <nav className="library-tabs collection-tabs" aria-label="歌单分类">
              <button
                aria-current={view === "playlists" ? "page" : undefined}
                onClick={() => {
                  setView("playlists");
                  setSelected(new Set());
                }}
              >
                <ListMusic />
                我的歌单 · {allPlaylists.length}
              </button>
              <button
                aria-current={view === "favorites" ? "page" : undefined}
                onClick={() => {
                  setView("favorites");
                  setSelected(new Set());
                  resetCollectionFilters();
                }}
              >
                <Heart />
                我的收藏 · {favorites.length}
              </button>
              <button
                aria-current={view === "import" ? "page" : undefined}
                onClick={() => setView("import")}
              >
                <Plus />
                歌单导入
              </button>
            </nav>
          )}
          {(view === "search" || view === "favorites") && (
            <section className="view search-view">
              <div className="search-grid">
                <div className="result-column">
                  {view === "search" && (
                    <header className="top">
                      <div>
                        <h1>{views[view][0]}</h1>
                        <p>{views[view][1]}</p>
                      </div>
                      <div className="top-actions">
                        {searching && (
                          <button
                            className="secondary"
                            onClick={() => {
                              searchGeneration.current++;
                              eventSource.current?.close();
                              if (searchJob.current)
                                void api(
                                  `/search/jobs/${searchJob.current}`,
                                  "DELETE",
                                ).catch(fail);
                              searchJob.current = null;
                              eventSource.current = null;
                              setSearching(false);
                            }}
                          >
                            停止搜索
                          </button>
                        )}
                      </div>
                    </header>
                  )}
                  {view === "search" && (
                    <>
                      <form
                        className="searchbox"
                        onSubmit={(e) => {
                          e.preventDefault();
                          const keyword = query.trim();
                          if (keyword) {
                            const history = [
                              keyword,
                              ...recentSearches.filter((v) => v !== keyword),
                            ].slice(0, 8);
                            setRecentSearches(history);
                            try {
                              localStorage.setItem(
                                "melokeep-searches",
                                JSON.stringify(history),
                              );
                            } catch {
                              /* Storage is optional. */
                            }
                          }
                          void search();
                        }}
                      >
                        <Search />
                        <input
                          ref={searchInput}
                          aria-label="搜索音乐"
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                          placeholder="搜索歌曲、歌手或专辑"
                          maxLength={200}
                        />
                        <kbd className="search-shortcut" title="聚焦搜索">
                          Ctrl K
                        </kbd>
                        <button
                          type="button"
                          className="scope"
                          onClick={() => openSettings()}
                        >
                          音源设置
                        </button>
                        <button
                          className="primary"
                          type="submit"
                          disabled={!query.trim() || !config}
                        >
                          搜索
                        </button>
                      </form>
                      {!tracks.length &&
                        !searching &&
                        !!recentSearches.length && (
                          <div className="recent-searches">
                            <History />
                            <span>最近搜索</span>
                            {recentSearches.map((keyword) => (
                              <button
                                key={keyword}
                                onClick={() => {
                                  setQuery(keyword);
                                  searchInput.current?.focus();
                                }}
                              >
                                {keyword}
                              </button>
                            ))}
                            <button
                              aria-label="清空搜索历史"
                              onClick={() => {
                                setRecentSearches([]);
                                try {
                                  localStorage.removeItem("melokeep-searches");
                                } catch {
                                  /* Storage is optional. */
                                }
                              }}
                            >
                              <X />
                            </button>
                          </div>
                        )}
                      {!tracks.length && !searching && !!favorites.length && (
                        <section
                          className="collection-shelf"
                          aria-label="收藏速览"
                        >
                          <div className="section-heading">
                            <h2>从收藏开始听</h2>
                            <button
                              className="text-button"
                              onClick={() => setView("favorites")}
                            >
                              查看全部
                              <ArrowRight />
                            </button>
                          </div>
                          <div className="collection-covers">
                            {favorites.slice(0, 6).map((track) => (
                              <button
                                key={track.id}
                                onClick={() => void play(track, favorites)}
                              >
                                <Cover track={track} large />
                                <strong>{track.title}</strong>
                                <small>{track.artist}</small>
                              </button>
                            ))}
                          </div>
                        </section>
                      )}
                      <div className="sources">
                        <button
                          className={`source ${sourceFilter === "all" ? "active" : ""}`}
                          aria-pressed={sourceFilter === "all"}
                          onClick={() => setSourceFilter("all")}
                        >
                          全部音源<span>{tracks.length}</span>
                        </button>
                        {sources
                          .filter((s) => config?.sources.includes(s.id))
                          .map((s) => (
                            <button
                              key={s.id}
                              className={`source ${sourceFilter === s.id ? "active" : ""}`}
                              aria-pressed={sourceFilter === s.id}
                              onClick={() => setSourceFilter(s.id)}
                            >
                              <i />
                              {s.label}
                              <span>
                                {statuses[s.id]?.state === "searching"
                                  ? "搜索中"
                                  : tracks.filter((t) => t.source === s.id)
                                      .length}
                              </span>
                            </button>
                          ))}
                        <span className="source-note">
                          {
                            Object.values(statuses).filter(
                              (s) => s.state === "complete",
                            ).length
                          }{" "}
                          个音源已返回
                        </span>
                      </div>
                    </>
                  )}
                  {trackTable}
                </div>
                <aside className="now-panel" aria-label="播放控制与歌词">
                  <div className="current-track mini-track">
                    <Cover track={current} />
                    <div className="current-track-copy">
                      <div className="current-track-top">
                        <strong>{current?.title || "尚未播放"}</strong>
                        <div className="panel-heading-actions">
                          <Button
                            label="播放列表"
                            onClick={() => setShowPlaylist(true)}
                          >
                            <ListMusic />
                          </Button>
                          <Button
                            label="展开播放界面"
                            onClick={() => setView("player")}
                          >
                            <Expand />
                          </Button>
                        </div>
                      </div>
                      <p>
                        {current
                          ? `${current.artist} · ${current.album || "未知专辑"}`
                          : "点击曲目的播放按钮开始试听"}
                      </p>
                      <span className="listen-badge">{playbackLabel}</span>
                    </div>
                  </div>
                  <div
                    className="now-track-actions"
                    role="group"
                    aria-label="当前曲目操作"
                  >
                    <button
                      type="button"
                      className={`now-action-btn ${current && favIds.has(current.id) ? "active" : ""}`}
                      aria-label="收藏当前曲目"
                      aria-pressed={!!current && favIds.has(current.id)}
                      title="收藏当前曲目"
                      disabled={!current}
                      onClick={() => current && void favorite(current)}
                    >
                      <Heart />
                      <span>
                        {current && favIds.has(current.id) ? "已收藏" : "收藏"}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="now-action-btn"
                      aria-label="选择版本并下载"
                      title="选择版本并下载"
                      disabled={!current}
                      onClick={() => current && void chooseDownload([current])}
                    >
                      <Download />
                      <span>下载</span>
                    </button>
                    <button
                      type="button"
                      className="now-action-btn"
                      aria-label="加入播放列表"
                      title="加入播放列表"
                      disabled={!current}
                      onClick={() => current && void addToPlaylist([current])}
                    >
                      <Plus />
                      <span>加入待播</span>
                    </button>
                    <button
                      type="button"
                      className="now-action-btn"
                      aria-label="加入歌单"
                      title="加入歌单"
                      disabled={!current}
                      onClick={() =>
                        current && openAddToPlaylistModal([current])
                      }
                    >
                      <ListMusic />
                      <span>加入歌单</span>
                    </button>
                  </div>
                  <div className="now-controls">
                    <div className="timeline">
                      <span>{clock(time)}</span>
                      <input
                        aria-label="播放进度"
                        type="range"
                        min="0"
                        max={duration || 1}
                        step=".1"
                        value={Math.min(time, duration || 1)}
                        style={
                          {
                            "--progress": `${duration ? Math.min(100, (time / duration) * 100) : 0}%`,
                          } as React.CSSProperties
                        }
                        onChange={(e) => seek(Number(e.target.value))}
                        disabled={!current}
                      />
                      <span>{clock(duration)}</span>
                    </div>
                    <div className="now-transport-row">
                      <div className="transport">
                        <Button
                          label="随机播放"
                          active={shuffle}
                          onClick={() => setShuffle((v) => !v)}
                        >
                          <Shuffle />
                        </Button>
                        <Button
                          label="上一首"
                          onClick={() => step(-1)}
                          disabled={!current}
                        >
                          <SkipBack />
                        </Button>
                        <button
                          className="pause"
                          aria-label={playing ? "暂停" : "播放"}
                          disabled={!current || loadingPlay}
                          onClick={() => void toggle()}
                        >
                          {loadingPlay ? (
                            <span className="loading-dot" />
                          ) : playing ? (
                            <Pause />
                          ) : (
                            <Play />
                          )}
                        </button>
                        <Button
                          label="下一首"
                          onClick={() => step(1)}
                          disabled={!current}
                        >
                          <SkipForward />
                        </Button>
                        <Button
                          label="列表循环"
                          active={repeat}
                          onClick={() => setRepeat((v) => !v)}
                        >
                          <Repeat />
                        </Button>
                      </div>
                      {volumeControl}
                    </div>
                  </div>
                  <div className="panel-content" role="tabpanel">
                    {lyricContent}
                  </div>
                </aside>
              </div>
            </section>
          )}
          {view === "player" && (
            <section className="view full-player">
              {current?.cover && (
                <div
                  className="player-atmosphere"
                  aria-hidden="true"
                  style={{
                    backgroundImage: `url(${JSON.stringify(current.cover)})`,
                  }}
                />
              )}
              <div className="playback-top">
                <button
                  className="text-button"
                  onClick={() => setView(returnView)}
                >
                  <ArrowLeft />
                  {returnView === "search"
                    ? "返回搜索结果"
                    : `返回${["playlists", "favorites", "import"].includes(returnView) ? views.playlists[0] : views[returnView][0]}`}
                </button>
                <span className="badge">{playbackLabel}</span>
              </div>
              {current ? (
                <div
                  className={`playback-grid ${playlist.length ? "has-queue" : ""}`}
                >
                  <div className="album-column">
                    <Cover track={current} large />
                    <div className="album-info">
                      <div>
                        <h2>{current.title}</h2>
                        <p>{current.artist}</p>
                      </div>
                      <Button
                        label="收藏当前曲目"
                        active={favIds.has(current.id)}
                        onClick={() => void favorite(current)}
                      >
                        <Heart />
                      </Button>
                    </div>
                    <div className="album-metadata">
                      <span>{sourceLabel(current.source)}</span>
                      <span>{current.album}</span>
                      <span>{clock(duration)}</span>
                    </div>
                    <div className="now-controls full-player-controls">
                      <div className="timeline">
                        <span>{clock(time)}</span>
                        <input
                          aria-label="播放进度"
                          type="range"
                          min="0"
                          max={duration || 1}
                          step=".1"
                          value={Math.min(time, duration || 1)}
                          style={
                            {
                              "--progress": `${duration ? Math.min(100, (time / duration) * 100) : 0}%`,
                            } as React.CSSProperties
                          }
                          onChange={(e) => seek(Number(e.target.value))}
                        />
                        <span>{clock(duration)}</span>
                      </div>
                      <div className="now-transport-row">
                        <div className="transport">
                          <Button
                            label="切换随机播放"
                            active={shuffle}
                            onClick={() => setShuffle((v) => !v)}
                          >
                            <Shuffle />
                          </Button>
                          <Button label="上一首" onClick={() => step(-1)}>
                            <SkipBack />
                          </Button>
                          <button
                            className="pause"
                            aria-label={playing ? "暂停" : "播放"}
                            disabled={loadingPlay}
                            onClick={() => void toggle()}
                          >
                            {loadingPlay ? (
                              <span className="loading-dot" />
                            ) : playing ? (
                              <Pause />
                            ) : (
                              <Play />
                            )}
                          </button>
                          <Button label="下一首" onClick={() => step(1)}>
                            <SkipForward />
                          </Button>
                          <Button
                            label="切换列表循环"
                            active={repeat}
                            onClick={() => setRepeat((v) => !v)}
                          >
                            <Repeat />
                          </Button>
                        </div>
                        {volumeControl}
                      </div>
                    </div>
                    <div className="album-actions">
                      <button
                        className="secondary"
                        onClick={() => chooseDownload([current])}
                      >
                        <Download />
                        选择下载音质
                      </button>
                      <button
                        className="secondary"
                        aria-label="加入播放列表"
                        onClick={() => void addToPlaylist([current])}
                      >
                        <Plus />
                        加入待播
                      </button>
                      <button
                        className="secondary"
                        onClick={() => openAddToPlaylistModal([current])}
                      >
                        <ListMusic />
                        加入歌单
                      </button>
                    </div>
                  </div>
                  <section className="lyrics-column">
                    <div className="lyrics-toolbar">
                      <div className="lyrics-label">歌词</div>
                      <div>
                        <Button
                          label="调整歌词字号"
                          onClick={() => setLargeLyrics((v) => !v)}
                          active={largeLyrics}
                        >
                          Aa
                        </Button>
                        <button
                          className={`lyric-follow ${follow ? "active" : ""}`}
                          aria-pressed={follow && lines.length > 0}
                          disabled={!lines.length}
                          title={
                            lines.length
                              ? "跟随当前播放位置"
                              : "歌词没有时间轴，无法跟随进度"
                          }
                          onClick={() => setFollow((v) => !v)}
                        >
                          跟随进度
                        </button>
                      </div>
                    </div>
                    <Lyrics
                      lines={lines}
                      text={lyricText}
                      time={time}
                      onSeek={seek}
                      large
                      follow={follow}
                      size={largeLyrics}
                    />
                  </section>
                  <section className="album-queue">
                    <div className="section-heading">
                      <h3>
                        待播列表 <span>{playlist.length}</span>
                      </h3>
                      <Button
                        label="打开播放列表"
                        onClick={() => setShowPlaylist(true)}
                      >
                        <ListMusic />
                      </Button>
                    </div>
                    {listContent}
                  </section>
                </div>
              ) : (
                <div className="empty">
                  尚未播放曲目。返回搜索，选择一首音乐。
                </div>
              )}
            </section>
          )}
          {view === "queue" && (
            <section className="view">
              <div className="queue-toolbar">
                <label className="queue-status-filter">
                  <span>状态</span>
                  <select
                    aria-label="筛选下载状态"
                    value={queueStatus}
                    onChange={(e) => {
                      setQueueStatus(e.target.value);
                      setSelectedJobs([]);
                    }}
                  >
                    <option value="all">全部状态（{jobs.length}）</option>
                    {Object.entries(statusLabels).map(([status, label]) => (
                      <option key={status} value={status}>
                        {label}（
                        {jobs.filter((job) => job.status === status).length}）
                      </option>
                    ))}
                  </select>
                </label>
                <span aria-live="polite">
                  {visibleJobs.length} / {jobs.length} 首曲目
                </span>
                <button
                  className="secondary"
                  onClick={() =>
                    void api<DownloadJob[]>("/downloads")
                      .then(setJobs)
                      .catch(fail)
                  }
                >
                  刷新进度
                </button>
              </div>
              {!!visibleJobs.length && (
                <div className="management-toolbar">
                  <label className="check-label">
                    <input
                      type="checkbox"
                      aria-label="全选下载任务"
                      checked={
                        visibleJobs.length > 0 &&
                        chosenJobs.length === visibleJobs.length
                      }
                      disabled={managing}
                      onChange={(e) =>
                        setSelectedJobs(
                          e.target.checked
                            ? visibleJobs.map((job) => job.id)
                            : [],
                        )
                      }
                    />
                    全选
                  </label>
                  <span>已选 {chosenJobs.length} 项</span>
                  <button
                    className="secondary"
                    disabled={
                      managing || !chosenJobs.some((job) => !stopped(job))
                    }
                    onClick={() =>
                      void manageJobs(
                        "pause",
                        chosenJobs.filter((job) => !stopped(job)),
                      )
                    }
                  >
                    暂停选中
                  </button>
                  <button
                    className="secondary"
                    disabled={
                      managing ||
                      !chosenJobs.some((job) =>
                        ["paused", "failed", "cancelled"].includes(job.status),
                      )
                    }
                    onClick={() =>
                      void manageJobs(
                        "resume",
                        chosenJobs.filter((job) =>
                          ["paused", "failed", "cancelled"].includes(
                            job.status,
                          ),
                        ),
                      )
                    }
                  >
                    继续选中
                  </button>
                  <button
                    className="secondary"
                    disabled={
                      managing ||
                      !chosenJobs.some(
                        (job) =>
                          !["complete", "cancelled"].includes(job.status),
                      )
                    }
                    onClick={() =>
                      void manageJobs(
                        "cancel",
                        chosenJobs.filter(
                          (job) =>
                            !["complete", "cancelled"].includes(job.status),
                        ),
                      )
                    }
                  >
                    取消选中
                  </button>
                  <button
                    className="secondary"
                    disabled={
                      managing ||
                      !chosenJobs.length ||
                      !chosenJobs.every(stopped)
                    }
                    onClick={() => confirmRemoval(chosenJobs)}
                  >
                    移除选中记录
                  </button>
                  <button
                    className="secondary"
                    disabled={
                      managing ||
                      !visibleJobs.some((job) =>
                        ["complete", "cancelled"].includes(job.status),
                      )
                    }
                    onClick={() =>
                      confirmRemoval(
                        visibleJobs.filter((job) =>
                          ["complete", "cancelled"].includes(job.status),
                        ),
                      )
                    }
                  >
                    清理已结束记录
                  </button>
                </div>
              )}
              <p className="management-help">
                先暂停或取消进行中的任务，再移除记录。移除记录会保留已下载的文件。
              </p>
              {managementError && <p role="alert">{managementError}</p>}
              {visibleJobs.map((job) => (
                <div className="download-row" key={job.id}>
                  <div className="job-selection">
                    <input
                      type="checkbox"
                      aria-label={`选择下载任务 ${job.track.title}`}
                      checked={selectedJobs.includes(job.id)}
                      disabled={managing}
                      onChange={(e) =>
                        setSelectedJobs(
                          e.target.checked
                            ? [...selectedJobs, job.id]
                            : selectedJobs.filter((id) => id !== job.id),
                        )
                      }
                    />
                    <Cover
                      track={job.track}
                      onPlay={() => void play(job.track)}
                    />
                  </div>
                  <div>
                    <strong>
                      <SongTitle
                        track={job.track}
                        onPlay={() => void play(job.track)}
                      />
                    </strong>
                    <small>
                      {job.track.artist} · {job.quality_label}
                      {job.download_source &&
                        ` · 下载音源：${sources.find((source) => source.id === job.download_source)?.label || job.download_source}`}
                    </small>
                    <div className="progress">
                      <span
                        style={{
                          width:
                            job.status === "complete"
                              ? "100%"
                              : job.total_bytes
                                ? `${Math.min(100, (job.bytes / job.total_bytes) * 100)}%`
                                : "0%",
                        }}
                      />
                    </div>
                    <small>
                      {bytes(job.bytes)}
                      {job.total_bytes ? ` / ${bytes(job.total_bytes)}` : ""}
                      {job.detail && ` · ${job.detail}`}
                    </small>
                    {job.processing && (
                      <small
                        className={`processing-inline is-${job.processing.status}`}
                        role="status"
                      >
                        {processingLabels[job.processing.status] ||
                          job.processing.status}{" "}
                        · {job.processing.detail}
                      </small>
                    )}
                    {job.file && (
                      <a
                        href={`/api/files/content?path=${encodeURIComponent(job.file)}`}
                        download
                      >
                        下载到本机
                      </a>
                    )}
                  </div>
                  <span className="badge">{job.quality_label}</span>
                  <span
                    className={`state ${job.status === "complete" ? "done" : ""}`}
                  >
                    {statusLabels[job.status]}
                  </span>
                  <div className="job-actions">
                    {["failed", "paused", "cancelled"].includes(job.status) ? (
                      <button
                        className="secondary"
                        disabled={managing}
                        onClick={() =>
                          void api<DownloadJob>(
                            `/downloads/${job.id}/${job.status === "cancelled" ? "retry" : "resume"}`,
                            "POST",
                          )
                            .then((updated) =>
                              setJobs((old) =>
                                old.map((j) =>
                                  j.id === updated.id ? updated : j,
                                ),
                              ),
                            )
                            .catch(fail)
                        }
                      >
                        {job.status === "cancelled" ? "重新下载" : "继续下载"}
                      </button>
                    ) : (
                      job.status !== "complete" && (
                        <>
                          <Button
                            label="暂停下载"
                            disabled={managing}
                            onClick={() =>
                              void api(`/downloads/${job.id}/pause`, "POST")
                                .then(() => api<DownloadJob[]>("/downloads"))
                                .then(setJobs)
                                .catch(fail)
                            }
                          >
                            <Pause />
                          </Button>
                          <Button
                            label="取消下载"
                            disabled={managing}
                            onClick={() =>
                              void api(`/downloads/${job.id}/cancel`, "POST")
                                .then(() => api<DownloadJob[]>("/downloads"))
                                .then(setJobs)
                                .catch(fail)
                            }
                          >
                            <X />
                          </Button>
                        </>
                      )
                    )}
                    {stopped(job) && (
                      <Button
                        label={`移除下载记录 ${job.track.title}`}
                        disabled={managing}
                        onClick={() => confirmRemoval([job])}
                      >
                        <Trash2 />
                      </Button>
                    )}
                  </div>
                </div>
              ))}
              {!jobs.length && (
                <div className="empty">
                  选择曲目和音质后，下载任务将在这里显示。
                </div>
              )}
              {!!jobs.length && !visibleJobs.length && (
                <div className="empty" role="status">
                  当前没有“{statusLabels[queueStatus]}
                  ”的任务，可切换状态查看其他下载。
                </div>
              )}
            </section>
          )}
          {view === "playlists" && (
            <PlaylistLibrary
              lists={allPlaylists}
              syncError={remotePlaylistError}
              sync={() => {
                setPlaylistRefresh((value) => value + 1);
                void refreshPlaylists().catch(fail);
              }}
              current={activePlaylist}
              sourceName={(id) => sourceLabel(id, true)}
              open={(id) => void openPlaylist(id)}
              back={() => {
                setActivePlaylist(null);
                setSelected(new Set());
                void refreshPlaylists().catch(fail);
              }}
              onImport={() => setView("import")}
              onCreate={() => openAddToPlaylistModal([])}
              changed={(list) => {
                setActivePlaylist(list);
                void refreshPlaylists().catch(fail);
                if (list.source === "navidrome")
                  setPlaylistRefresh((value) => value + 1);
              }}
              deleted={(id) => {
                setActivePlaylist(null);
                setSavedPlaylists((previous) =>
                  previous.filter((l) => l.id !== id),
                );
                setRemotePlaylists((previous) =>
                  previous.filter((list) => list.id !== id),
                );
                setSelected(new Set());
              }}
              playAll={(items) => void playCollection(items)}
              queueAll={(items) => void addToPlaylist(items)}
              downloadAll={(items) => void chooseDownload(items)}
              search={(keyword) => {
                resetCollectionFilters();
                setQuery(keyword);
                void search(keyword);
              }}
              logs={() => setView("logs")}
            >
              {trackTable}
            </PlaylistLibrary>
          )}
          {view === "import" && (
            <section className="view">
              <form
                className="form-panel"
                onSubmit={(e) => {
                  e.preventDefault();
                  void importList();
                }}
              >
                <h2>导入平台歌单</h2>
                <p>
                  选择音源，粘贴公开歌单链接或歌单
                  ID。导入后将保存在“我的歌单”。
                </p>
                <label>
                  歌单名称（可选）
                  <input
                    value={importName}
                    onChange={(e) => setImportName(e.target.value)}
                    maxLength={100}
                    placeholder="例如：通勤时光"
                  />
                </label>
                <label>
                  歌单音源
                  <select
                    value={importSource}
                    onChange={(e) => setImportSource(e.target.value)}
                  >
                    {sources.map((s) => (
                      <option value={s.id} key={s.id}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  歌单链接 / ID
                  <input
                    value={importId}
                    onChange={(e) => setImportId(e.target.value)}
                    placeholder="https://music.163.com/playlist?id=…"
                    required
                  />
                </label>
                <p>
                  私有歌单可能需要配置音源
                  Cookie。可导入数量取决于原音源解析器；未获得资源的曲目会单独列出。
                </p>
                <button className="primary" disabled={busy || !importId.trim()}>
                  {busy ? "正在解析并保存…" : "导入并保存歌单"}
                </button>
              </form>
            </section>
          )}
          {(view === "files" || view === "organize") && (
            <LibraryWorkspace
              mode={view === "files" ? "library" : "processing"}
              tab={view === "files" ? libraryTab : processingTab}
              setTab={view === "files" ? setLibraryTab : setProcessingTab}
              openSettings={openSettings}
              process={(items) => {
                setSelectedFiles(items.map((file) => file.path));
                setProcessingTab("workbench");
                setView("organize");
              }}
              files={files}
              selected={selectedFiles}
              setSelected={setSelectedFiles}
              current={current}
              busy={managing}
              error={managementError}
              refresh={() =>
                void api<LibraryFile[]>("/files").then(setFiles).catch(fail)
              }
              play={(track, context) => void play(track, context)}
              playAll={(items) => void playCollection(items)}
              queue={(items) => void addToPlaylist(items)}
              savePlaylist={openAddToPlaylistModal}
              remove={confirmFileDeletion}
              remoteDeleted={(ids) => {
                playbackQueue.current = playbackQueue.current.filter(
                  (track) => !ids.includes(track.id),
                );
                setPlaylist((previous) =>
                  previous.filter((track) => !ids.includes(track.id)),
                );
                setFavorites((previous) =>
                  previous.filter((track) => !ids.includes(track.id)),
                );
                if (current && ids.includes(current.id)) {
                  ++playGeneration.current;
                  audio.current?.pause();
                  audio.current?.removeAttribute("src");
                  audio.current?.load();
                  setCurrent(null);
                  setLoadingPlay(false);
                }
                setPlaylistRefresh((value) => value + 1);
                void api<LibraryFile[]>("/files").then(setFiles).catch(fail);
              }}
              changed={(file) => {
                setFiles((previous) =>
                  previous.map((item) =>
                    item.path === file.path ? file : item,
                  ),
                );
                if (file.track) {
                  const updated = file.track;
                  setPlaylist((previous) =>
                    previous.map((track) =>
                      track.id === updated.id ? updated : track,
                    ),
                  );
                  setFavorites((previous) =>
                    previous.map((track) =>
                      track.id === updated.id ? updated : track,
                    ),
                  );
                  setCurrent((previous) =>
                    previous?.id === updated.id ? updated : previous,
                  );
                }
              }}
            />
          )}
          {view === "settings" && config && (
            <SettingsWorkspace
              sources={sources}
              saved={load}
              tab={settingsTab}
              setTab={setSettingsTab}
            />
          )}
          {view === "logs" && <RuntimeLogs active={!loginRequired} />}
          {view === "assistant" && !loginRequired && (
            <AIAssistant
              openSettings={() => openSettings("ai")}
              changed={load}
              navigate={setView}
            />
          )}
          {current &&
            view !== "search" &&
            view !== "favorites" &&
            view !== "player" && (
              <aside className="global-mini-player" aria-label="全局播放控制">
                <div className="global-mini-track">
                  <Cover track={current} />
                  <div className="global-mini-copy">
                    <strong>{current.title}</strong>
                    <span>
                      {current.artist} · {current.album || "未知专辑"}
                    </span>
                  </div>
                </div>
                <div className="timeline global-mini-timeline">
                  <span>{clock(time)}</span>
                  <input
                    aria-label="全局播放进度"
                    type="range"
                    min="0"
                    max={duration || 1}
                    step=".1"
                    value={Math.min(time, duration || 1)}
                    style={
                      {
                        "--progress": `${duration ? Math.min(100, (time / duration) * 100) : 0}%`,
                      } as React.CSSProperties
                    }
                    onChange={(e) => seek(Number(e.target.value))}
                  />
                  <span>{clock(duration)}</span>
                </div>
                <div className="global-mini-actions">
                  <div className="global-mini-transport">
                    <Button label="上一首全局曲目" onClick={() => step(-1)}>
                      <SkipBack />
                    </Button>
                    <button
                      type="button"
                      className="pause"
                      aria-label={playing ? "暂停全局播放" : "继续全局播放"}
                      disabled={loadingPlay}
                      onClick={() => void toggle()}
                    >
                      {loadingPlay ? (
                        <span className="loading-dot" />
                      ) : playing ? (
                        <Pause />
                      ) : (
                        <Play />
                      )}
                    </button>
                    <Button label="下一首全局曲目" onClick={() => step(1)}>
                      <SkipForward />
                    </Button>
                  </div>
                  <div className="global-mini-utilities">
                    <details className="global-mini-volume">
                      <summary aria-label="调节全局音量" title="调节音量">
                        {volume ? <Volume2 /> : <VolumeX />}
                      </summary>
                      <div className="global-mini-volume-panel">
                        {volumeControl}
                      </div>
                    </details>
                    <Button
                      label="查看待播列表"
                      onClick={() => setShowPlaylist(true)}
                    >
                      <ListMusic />
                    </Button>
                    <Button
                      label="展开全屏播放器"
                      onClick={() => setView("player")}
                    >
                      <Expand />
                    </Button>
                  </div>
                </div>
              </aside>
            )}
        </main>
      </div>
      {notice && (
        <div id="toast" role="status">
          {notice}
          <button aria-label="关闭提示" onClick={() => setNotice("")}>
            <X />
          </button>
        </div>
      )}
      {confirmation && (
        <Modal
          title={confirmation.title}
          close={managing ? undefined : () => setConfirmation(null)}
        >
          <p>{confirmation.description}</p>
          {managementError && <p role="alert">{managementError}</p>}
          <div className="management-toolbar">
            <button
              className="secondary"
              disabled={managing}
              onClick={() => setConfirmation(null)}
            >
              取消
            </button>
            <button
              className="primary danger"
              disabled={managing}
              onClick={() => void confirmation.run()}
            >
              {managing ? "正在处理…" : "确认操作"}
            </button>
          </div>
        </Modal>
      )}
      {qualityTracks && (
        <Modal
          title={qualityTracks.length > 1 ? "批量选择下载音质" : "选择下载音质"}
          close={() => setQualityTracks(null)}
        >
          <p>下载前验证所选资源，无损版本不可用时任务会失败。</p>
          <div className="quality-list">
            {qualityTracks.map((track) => (
              <fieldset key={track.id}>
                <legend>
                  {track.title} · {track.artist}
                </legend>
                {track.qualities.length ? (
                  track.qualities.map((q) => (
                    <label className="version-option" key={q.id}>
                      <input
                        type="radio"
                        name={track.id}
                        value={q.id}
                        checked={qualities[track.id] === q.id}
                        onChange={() =>
                          setQualities((previous) => ({
                            ...previous,
                            [track.id]: q.id,
                          }))
                        }
                      />
                      <span>
                        {q.label}
                        <small>
                          {q.availability === "login_required"
                            ? "需要账号权限"
                            : "音源标注，下载前验证"}
                        </small>
                      </span>
                    </label>
                  ))
                ) : (
                  <p>音源未提供音质信息，请选择其他曲目或音源。</p>
                )}
              </fieldset>
            ))}
          </div>
          <div className="dialog-actions">
            <button onClick={() => setQualityTracks(null)}>取消</button>
            <button
              className="primary"
              disabled={busy || qualityTracks.some((t) => !qualities[t.id])}
              onClick={() => void download()}
            >
              {busy ? "正在加入…" : "加入下载队列"}
            </button>
          </div>
        </Modal>
      )}
      {showPlaylist && (
        <Modal title="播放列表" close={() => setShowPlaylist(false)}>
          {listContent}
        </Modal>
      )}
      {playlistModalTracks && (
        <Modal
          title={playlistModalTracks.length ? "加入歌单" : "新建歌单"}
          close={busy ? undefined : () => setPlaylistModalTracks(null)}
        >
          <p>
            {playlistModalTracks.length
              ? `将已选的 ${playlistModalTracks.length} 首曲目保存到歌单。`
              : "选择歌单保存位置，并填写名称。"}
          </p>
          <div className="playlist-picker-list">
            {!!playlistModalTracks.length &&
              savedPlaylists.map((list) => (
                <label className="version-option" key={list.id}>
                  <input
                    type="radio"
                    name="target-playlist"
                    value={list.id}
                    checked={targetPlaylistId === list.id}
                    onChange={() => setTargetPlaylistId(list.id)}
                  />
                  <span>
                    {list.name}
                    <small>{list.track_count} 首曲目</small>
                  </span>
                </label>
              ))}
            <label className="version-option">
              <input
                type="radio"
                name="target-playlist"
                value="new"
                checked={targetPlaylistId === "new"}
                onChange={() => setTargetPlaylistId("new")}
              />
              <span>
                新建歌单
                <small>创建一个新的自定义歌单并加入曲目</small>
              </span>
            </label>
            {playlistModalTracks.every(
              (track) => track.source === "navidrome",
            ) && (
              <>
                {!!playlistModalTracks.length &&
                  remotePlaylists
                    .filter((list) => !list.read_only)
                    .map((list) => (
                      <label className="version-option" key={list.id}>
                        <input
                          type="radio"
                          name="target-playlist"
                          value={list.id}
                          checked={targetPlaylistId === list.id}
                          onChange={() => setTargetPlaylistId(list.id)}
                        />
                        <span>
                          {list.name}
                          <small>Navidrome · {list.track_count} 首曲目</small>
                        </span>
                      </label>
                    ))}
                <label className="version-option">
                  <input
                    type="radio"
                    name="target-playlist"
                    value="new-navidrome"
                    checked={targetPlaylistId === "new-navidrome"}
                    onChange={() => setTargetPlaylistId("new-navidrome")}
                  />
                  <span>
                    新建 Navidrome 歌单
                    <small>保存到已连接的 Navidrome 服务器</small>
                  </span>
                </label>
              </>
            )}
          </div>
          {(targetPlaylistId === "new" ||
            targetPlaylistId === "new-navidrome") && (
            <label className="playlist-new-field">
              <span>新歌单名称</span>
              <input
                aria-label="新歌单名称"
                placeholder="例如：华语精选、通勤歌单"
                maxLength={100}
                value={newPlaylistName}
                onChange={(e) => setNewPlaylistName(e.target.value)}
                autoFocus
              />
            </label>
          )}
          <div className="dialog-actions">
            <button
              type="button"
              disabled={busy}
              onClick={() => setPlaylistModalTracks(null)}
            >
              取消
            </button>
            <button
              type="button"
              className="primary"
              disabled={
                busy ||
                ((targetPlaylistId === "new" ||
                  targetPlaylistId === "new-navidrome") &&
                  !newPlaylistName.trim())
              }
              onClick={() => void submitAddToSavedPlaylist()}
            >
              {busy
                ? "正在保存…"
                : playlistModalTracks.length
                  ? "确定加入"
                  : "创建歌单"}
            </button>
          </div>
        </Modal>
      )}
      {loginRequired && (
        <Modal
          title="登录音乐库"
          className="login-dialog"
          heading={
            <header className="login-header">
              <div className="login-brand">
                <AudioLines aria-hidden="true" />
                <span>MeloKeep</span>
              </div>
              <h2>登录音乐库</h2>
              <p>登录以继续搜索、播放和下载音乐</p>
            </header>
          }
        >
          <form
            className="login-form"
            aria-busy={loginBusy}
            onSubmit={async (e) => {
              e.preventDefault();
              if (loginBusy) return;
              setLoginBusy(true);
              setLoginError("");
              try {
                await api("/auth/login", "POST", {
                  username: loginUser,
                  password: loginPass,
                });
                setLoginRequired(false);
                setLoginPass("");
                setShowLoginPassword(false);
                await load().catch(fail);
              } catch (error) {
                setLoginError(
                  error instanceof Error ? error.message : String(error),
                );
              } finally {
                setLoginBusy(false);
              }
            }}
          >
            <div className="login-field">
              <label htmlFor="login-username">用户名</label>
              <input
                id="login-username"
                className="login-input"
                autoFocus
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                placeholder="输入用户名"
                value={loginUser}
                disabled={loginBusy}
                aria-invalid={!!loginError}
                aria-describedby={loginError ? "login-error" : undefined}
                onChange={(e) => {
                  setLoginUser(e.target.value);
                  setLoginError("");
                }}
                required
              />
            </div>
            <div className="login-field">
              <label htmlFor="login-password">密码</label>
              <div className="login-password">
                <input
                  id="login-password"
                  className="login-input"
                  autoComplete="current-password"
                  type={showLoginPassword ? "text" : "password"}
                  placeholder="输入密码"
                  value={loginPass}
                  disabled={loginBusy}
                  aria-invalid={!!loginError}
                  aria-describedby={loginError ? "login-error" : undefined}
                  onChange={(e) => {
                    setLoginPass(e.target.value);
                    setLoginError("");
                  }}
                  required
                />
                <button
                  type="button"
                  className="login-reveal"
                  aria-label={showLoginPassword ? "隐藏密码" : "显示密码"}
                  aria-pressed={showLoginPassword}
                  aria-controls="login-password"
                  disabled={loginBusy}
                  onClick={() => setShowLoginPassword(!showLoginPassword)}
                >
                  {showLoginPassword ? (
                    <EyeOff aria-hidden="true" />
                  ) : (
                    <Eye aria-hidden="true" />
                  )}
                </button>
              </div>
            </div>
            {loginError && (
              <p className="login-error" id="login-error" role="alert">
                <CircleAlert aria-hidden="true" />
                <span>{loginError}</span>
              </p>
            )}
            <button
              className="primary login-submit"
              type="submit"
              disabled={loginBusy}
            >
              {loginBusy ? "正在登录…" : "登录"}
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}
