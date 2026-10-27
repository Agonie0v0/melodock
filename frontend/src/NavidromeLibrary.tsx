import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Disc3,
  Play,
  Plus,
  RefreshCw,
  Search,
  Users,
  Music2,
  LayoutGrid,
  List,
  ListMusic,
  Trash2,
} from "lucide-react";
import { api } from "./api";
import { Cover, Button, Modal, SongTitle } from "./components";
import { clock } from "./lyrics";
import type { Track } from "./types";

interface Album {
  id: string;
  name: string;
  artist: string;
  year?: number;
  song_count: number;
  cover: string | null;
}
interface Artist {
  id: string;
  name: string;
  album_count: number;
}
interface AlbumDetail extends Album {
  tracks: Track[];
}

function preference(key: string, values: string[], fallback: string) {
  try {
    const value = localStorage.getItem(key);
    return value && values.includes(value) ? value : fallback;
  } catch {
    return fallback;
  }
}

export function NavidromeLibrary({
  play,
  queue,
  savePlaylist,
  deleted,
  openSettings,
}: {
  play: (track: Track) => void;
  queue: (tracks: Track[]) => void;
  savePlaylist?: (tracks: Track[]) => void;
  deleted?: (ids: string[]) => void;
  openSettings: () => void;
}) {
  const [mode, setMode] = useState(() =>
    preference(
      "melokeep-navidrome-mode",
      ["songs", "albums", "artists"],
      "songs",
    ),
  );
  const [layout, setLayout] = useState(() =>
    preference("melokeep-navidrome-layout", ["cards", "list"], "list"),
  );
  useEffect(() => {
    try {
      localStorage.setItem("melokeep-navidrome-mode", mode);
      localStorage.setItem("melokeep-navidrome-layout", layout);
    } catch {
      /* Preferences are optional. */
    }
  }, [mode, layout]);
  const [sort, setSort] = useState("newest");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [albums, setAlbums] = useState<Album[]>([]);
  const [artists, setArtists] = useState<Artist[]>([]);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [artist, setArtist] = useState<Artist | null>(null);
  const [album, setAlbum] = useState<AlbumDetail | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [scan, setScan] = useState<{
    scanning?: boolean;
    count?: number;
  } | null>(null);
  const [scanBusy, setScanBusy] = useState(false);
  const [canDelete, setCanDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [deleteNotice, setDeleteNotice] = useState("");
  const [deletePreview, setDeletePreview] = useState<{
    track: Track;
    path: string;
    revision: string;
  } | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    void api<{ delete_songs: boolean }>(
      "/navidrome/capabilities",
      "GET",
      undefined,
      abort.signal,
    )
      .then((value) => setCanDelete(value.delete_songs === true))
      .catch(() => setCanDelete(false));
    return () => abort.abort();
  }, [refresh]);
  async function previewDeletion(track: Track) {
    setDeleting(true);
    setDeleteError("");
    setDeleteNotice("");
    try {
      const value = await api<{ path: string; revision: string }>(
        `/navidrome/songs/${encodeURIComponent(track.source_id)}/deletion`,
      );
      setDeletePreview({ ...value, track });
    } catch (e) {
      setDeleteError((e as Error).message);
    } finally {
      setDeleting(false);
    }
  }
  async function deleteSong() {
    if (!deletePreview) return;
    setDeleting(true);
    setDeleteError("");
    try {
      const result = await api<{
        track_ids: string[];
        warning?: string;
        scan?: { scanning?: boolean; count?: number };
      }>(
        `/navidrome/songs/${encodeURIComponent(deletePreview.track.source_id)}?revision=${encodeURIComponent(deletePreview.revision)}`,
        "DELETE",
      );
      const id = deletePreview.track.id;
      setTracks((items) => items.filter((track) => track.id !== id));
      setAlbum((value) =>
        value
          ? {
              ...value,
              tracks: value.tracks.filter((track) => track.id !== id),
            }
          : value,
      );
      deleted?.(result.track_ids);
      setDeletePreview(null);
      setDeleteNotice(
        result.warning ||
          "音乐文件已删除，Navidrome 将在扫描后更新曲库和歌单。",
      );
      if (result.scan) setScan(result.scan);
    } catch (e) {
      setDeletePreview(null);
      setDeleteError((e as Error).message);
    } finally {
      setDeleting(false);
    }
  }
  const albumRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    albumRequest.current?.abort();
    const abort = new AbortController();
    setBusy(true);
    setError("");
    setAlbum(null);
    async function load() {
      if (query) {
        const data = await api<{
          albums: Album[];
          tracks: Track[];
          has_more: boolean;
        }>(
          `/navidrome/search?query=${encodeURIComponent(query)}&offset=${offset}`,
          "GET",
          undefined,
          abort.signal,
        );
        setAlbums(data.albums);
        setTracks(data.tracks);
        setHasMore(data.has_more);
      } else if (artist) {
        const data = await api<{ albums: Album[] }>(
          `/navidrome/artists/${encodeURIComponent(artist.id)}`,
          "GET",
          undefined,
          abort.signal,
        );
        setAlbums(data.albums);
        setTracks([]);
        setHasMore(false);
      } else if (mode === "songs") {
        const data = await api<{ tracks: Track[]; has_more: boolean }>(
          `/navidrome/songs?offset=${offset}&size=50`,
          "GET",
          undefined,
          abort.signal,
        );
        setTracks(data.tracks);
        setAlbums([]);
        setHasMore(data.has_more);
      } else if (mode === "artists") {
        setTracks([]);
        setAlbums([]);
        setArtists(
          await api<Artist[]>(
            "/navidrome/artists",
            "GET",
            undefined,
            abort.signal,
          ),
        );
        setHasMore(false);
      } else {
        const data = await api<{ albums: Album[]; has_more: boolean }>(
          `/navidrome/albums?offset=${offset}&size=48&sort=${sort}`,
          "GET",
          undefined,
          abort.signal,
        );
        setAlbums(data.albums);
        setTracks([]);
        setHasMore(data.has_more);
      }
    }
    void load()
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setBusy(false);
      });
    return () => {
      abort.abort();
      albumRequest.current?.abort();
    };
  }, [mode, sort, offset, query, artist, refresh]);
  useEffect(() => {
    if (!scan?.scanning) return;
    const timer = window.setTimeout(() => {
      void api<{ scanning: boolean; count: number }>("/navidrome/scan")
        .then((result) => {
          setScan(result);
          if (!result.scanning) setRefresh((value) => value + 1);
        })
        .catch((e) => {
          setError(e.message);
          setScan(null);
        });
    }, 2500);
    return () => window.clearTimeout(timer);
  }, [scan]);
  async function openAlbum(item: Album) {
    albumRequest.current?.abort();
    const abort = new AbortController();
    albumRequest.current = abort;
    setBusy(true);
    setError("");
    try {
      setAlbum(
        await api<AlbumDetail>(
          `/navidrome/albums/${encodeURIComponent(item.id)}`,
          "GET",
          undefined,
          abort.signal,
        ),
      );
    } catch (e) {
      if (!abort.signal.aborted) setError((e as Error).message);
    } finally {
      if (!abort.signal.aborted) setBusy(false);
    }
  }
  function reset(nextMode: string) {
    setMode(nextMode);
    setArtist(null);
    setAlbum(null);
    setQuery("");
    setSearch("");
    setOffset(0);
  }
  const shownTracks = album?.tracks || tracks;
  const pageSize = query || mode === "songs" ? 50 : 48;
  return (
    <section className="view navidrome-library">
      {deletePreview && (
        <Modal
          title="删除 Navidrome 原文件"
          close={deleting ? undefined : () => setDeletePreview(null)}
        >
          <p>
            将永久删除“{deletePreview.track.title}
            ”的音频文件，无法撤销。Navidrome
            及其他客户端也将失去此歌曲。歌词、封面和其他文件保留。
          </p>
          <p className="setting-help" style={{ overflowWrap: "anywhere" }}>
            {deletePreview.path}
          </p>
          <div className="management-toolbar">
            <button
              className="secondary"
              disabled={deleting}
              onClick={() => setDeletePreview(null)}
            >
              取消
            </button>
            <button
              className="primary danger"
              disabled={deleting}
              onClick={() => void deleteSong()}
            >
              {deleting ? "正在删除…" : "确认永久删除"}
            </button>
          </div>
        </Modal>
      )}
      {deleteError && (
        <p role="alert" className="library-error">
          {deleteError}
        </p>
      )}
      {deleteNotice && (
        <p role="status" className="setting-help">
          {deleteNotice}
        </p>
      )}
      <div className="library-heading">
        <div>
          <h2>Navidrome 音乐库</h2>
          <p>直接浏览全部歌曲，或按专辑、歌手查找。</p>
        </div>
        <div className="library-heading-actions">
          <button
            className="secondary"
            onClick={() => setRefresh((value) => value + 1)}
            disabled={busy}
          >
            <RefreshCw />
            刷新
          </button>
          <button
            className="secondary"
            disabled={scanBusy || scan?.scanning}
            onClick={() => {
              setScanBusy(true);
              setError("");
              void api<{ scanning: boolean; count: number }>(
                "/navidrome/scan",
                "POST",
              )
                .then(setScan)
                .catch((e) => setError(e.message))
                .finally(() => setScanBusy(false));
            }}
          >
            {scanBusy || scan?.scanning ? "正在扫描…" : "扫描服务器曲库"}
          </button>
        </div>
      </div>
      {scan && (
        <p role="status" className="setting-help">
          {scan.scanning ? "Navidrome 正在扫描" : "Navidrome 扫描已完成"}
          {scan.count !== undefined ? `，已发现 ${scan.count} 首` : ""}
        </p>
      )}
      <div className="library-toolbar">
        <div className="library-modes" aria-label="曲库分类">
          <button
            className={mode === "songs" && !query ? "active" : ""}
            aria-pressed={mode === "songs" && !query}
            onClick={() => reset("songs")}
          >
            <Music2 />
            全部歌曲
          </button>
          <button
            className={mode === "albums" && !query ? "active" : ""}
            aria-pressed={mode === "albums" && !query}
            onClick={() => reset("albums")}
          >
            <Disc3 />
            专辑
          </button>
          <button
            className={mode === "artists" && !query ? "active" : ""}
            aria-pressed={mode === "artists" && !query}
            onClick={() => reset("artists")}
          >
            <Users />
            歌手
          </button>
        </div>
        <form
          className="library-search"
          onSubmit={(e) => {
            e.preventDefault();
            setArtist(null);
            setOffset(0);
            setQuery(search.trim());
          }}
        >
          <Search />
          <input
            aria-label="搜索 Navidrome 音乐库"
            placeholder="搜索歌曲、歌手或专辑"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button
            type="submit"
            className="secondary"
            disabled={busy || !search.trim()}
          >
            搜索
          </button>
        </form>
        <div className="library-modes" role="group" aria-label="曲库显示方式">
          <button
            aria-label="卡片显示"
            aria-pressed={layout === "cards"}
            className={layout === "cards" ? "active" : ""}
            onClick={() => setLayout("cards")}
          >
            <LayoutGrid />
            卡片
          </button>
          <button
            aria-label="列表显示"
            aria-pressed={layout === "list"}
            className={layout === "list" ? "active" : ""}
            onClick={() => setLayout("list")}
          >
            <List />
            列表
          </button>
        </div>
        {!query && mode === "albums" && !artist && (
          <select
            aria-label="Navidrome 专辑排序"
            value={sort}
            onChange={(e) => {
              setSort(e.target.value);
              setOffset(0);
            }}
          >
            <option value="newest">最近添加</option>
            <option value="alphabeticalByName">专辑名称</option>
            <option value="alphabeticalByArtist">歌手名称</option>
            <option value="recent">最近播放</option>
            <option value="starred">收藏专辑</option>
          </select>
        )}
      </div>
      {(album || artist || query) && (
        <button
          className="playlist-back"
          onClick={() => {
            if (album) setAlbum(null);
            else reset(mode);
          }}
        >
          <ArrowLeft />
          {album ? "返回专辑列表" : "返回全部"}
        </button>
      )}
      {error ? (
        <div className="library-empty">
          <Disc3 />
          <h3>暂时无法读取 Navidrome</h3>
          <p role="alert">{error}</p>
          <button className="primary" onClick={openSettings}>
            前往连接设置
          </button>
          <button
            className="secondary"
            onClick={() => setRefresh((value) => value + 1)}
          >
            重试
          </button>
        </div>
      ) : busy ? (
        <p className="library-loading" role="status">
          正在读取 Navidrome 音乐库…
        </p>
      ) : (
        <>
          {album && (
            <div className="nav-album-heading">
              <Cover track={album} large />
              <div>
                <h3>{album.name}</h3>
                <p>
                  {album.artist}
                  {album.year ? ` · ${album.year}` : ""}
                </p>
                <p>{album.tracks.length} 首歌曲</p>
                <div className="management-toolbar">
                  <button
                    className="primary"
                    disabled={!album.tracks.length}
                    onClick={() => play(album.tracks[0])}
                  >
                    <Play />
                    播放
                  </button>
                  <button
                    className="secondary"
                    disabled={!album.tracks.length}
                    onClick={() => queue(album.tracks)}
                  >
                    <Plus />
                    全部加入待播
                  </button>
                </div>
              </div>
            </div>
          )}
          {!album && artist && <h3>{artist.name}的专辑</h3>}
          {!album && query && <h3>“{query}”的搜索结果</h3>}
          {shownTracks.length > 0 && layout === "cards" && (
            <div className="nav-song-cards">
              {shownTracks.map((track) => (
                <article className="nav-song-card" key={track.id}>
                  <Cover track={track} large onPlay={() => play(track)} />
                  <strong>
                    <SongTitle track={track} onPlay={() => play(track)} />
                  </strong>
                  <span>{track.artist || "未知歌手"}</span>
                  <small>
                    {track.album || "未知专辑"} · {clock(track.duration)}
                  </small>
                  <div className="library-actions">
                    <Button
                      label={`播放 ${track.title}`}
                      onClick={() => play(track)}
                    >
                      <Play />
                    </Button>
                    <Button
                      label={`加入待播 ${track.title}`}
                      onClick={() => queue([track])}
                    >
                      <Plus />
                    </Button>
                    {savePlaylist && (
                      <Button
                        label={`加入歌单 ${track.title}`}
                        onClick={() => savePlaylist([track])}
                      >
                        <ListMusic />
                      </Button>
                    )}
                    {canDelete && (
                      <Button
                        label={`删除原文件 ${track.title}`}
                        disabled={deleting}
                        onClick={() => void previewDeletion(track)}
                      >
                        <Trash2 />
                      </Button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
          {shownTracks.length > 0 && layout === "list" && (
            <div className="music-table-wrap">
              <table className="music-table">
                <thead>
                  <tr>
                    <th>歌曲</th>
                    <th className="library-artist">歌手</th>
                    <th className="library-album">专辑</th>
                    <th>时长</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {shownTracks.map((track) => (
                    <tr key={track.id}>
                      <td>
                        <div className="library-song">
                          <Cover track={track} onPlay={() => play(track)} />
                          <span>
                            <strong>
                              <SongTitle
                                track={track}
                                onPlay={() => play(track)}
                              />
                            </strong>
                            <small className="mobile-meta-sub">
                              {track.artist}
                            </small>
                          </span>
                        </div>
                      </td>
                      <td className="library-artist">{track.artist}</td>
                      <td className="library-album">{track.album}</td>
                      <td>{clock(track.duration)}</td>
                      <td>
                        <div className="library-actions">
                          <Button
                            label={`播放 ${track.title}`}
                            onClick={() => play(track)}
                          >
                            <Play />
                          </Button>
                          <Button
                            label={`加入待播 ${track.title}`}
                            onClick={() => queue([track])}
                          >
                            <Plus />
                          </Button>
                          {savePlaylist && (
                            <Button
                              label={`加入歌单 ${track.title}`}
                              onClick={() => savePlaylist([track])}
                            >
                              <ListMusic />
                            </Button>
                          )}
                          {canDelete && (
                            <Button
                              label={`删除原文件 ${track.title}`}
                              disabled={deleting}
                              onClick={() => void previewDeletion(track)}
                            >
                              <Trash2 />
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!album &&
            !(mode === "artists" && !query && !artist) &&
            albums.length > 0 && (
              <div
                className={
                  layout === "cards"
                    ? "saved-playlists nav-albums"
                    : "nav-album-list"
                }
              >
                {albums.map((item) => (
                  <button
                    key={item.id}
                    className={
                      layout === "cards" ? "saved-playlist" : "nav-album-row"
                    }
                    onClick={() => void openAlbum(item)}
                  >
                    <Cover track={item} large />
                    <strong>{item.name}</strong>
                    <span>{item.artist || "未知歌手"}</span>
                    <small>
                      {item.song_count} 首{item.year ? ` · ${item.year}` : ""}
                    </small>
                  </button>
                ))}
              </div>
            )}
          {!album && mode === "artists" && !query && !artist && (
            <div className={`nav-artists nav-artists-${layout}`}>
              {artists.map((item) => (
                <button
                  className="nav-artist"
                  key={item.id}
                  onClick={() => {
                    setArtist(item);
                    setOffset(0);
                  }}
                >
                  <Users />
                  <span>
                    <strong>{item.name}</strong>
                    <small>{item.album_count} 张专辑</small>
                  </span>
                </button>
              ))}
            </div>
          )}
          {!album &&
            !shownTracks.length &&
            (mode === "artists" && !query && !artist
              ? !artists.length
              : !albums.length) && (
              <div className="empty">
                {query
                  ? "没有匹配的歌曲或专辑，请更换搜索内容。"
                  : "此范围还没有音乐。可先确认 Navidrome 的音乐目录并扫描曲库。"}
              </div>
            )}
          {!album && !artist && (offset > 0 || hasMore) && (
            <div className="library-pagination">
              <button
                className="secondary"
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
              >
                上一页
              </button>
              <span>第 {Math.floor(offset / pageSize) + 1} 页</span>
              <button
                className="secondary"
                disabled={!hasMore}
                onClick={() => setOffset(offset + pageSize)}
              >
                下一页
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
