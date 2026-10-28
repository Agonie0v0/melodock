import { useEffect, useId, useRef, type ReactNode } from "react";
import { Music2, X, Play, Plus, ListMusic, MoreHorizontal } from "lucide-react";
import { activeLine, clock, type LyricLine } from "./lyrics";
import type { Track } from "./types";
export function Cover({
  track,
  large = false,
  onPlay,
}: {
  track?: (Pick<Track, "cover"> & Partial<Pick<Track, "title">>) | null;
  large?: boolean;
  onPlay?: () => void;
}) {
  const Element = onPlay ? "button" : "span";
  return (
    <Element
      className={`${large ? "album-art" : "cover"}${onPlay ? " song-cover-play" : ""}`}
      type={onPlay ? "button" : undefined}
      aria-label={onPlay ? `播放封面 ${track?.title || "歌曲"}` : undefined}
      title={onPlay ? `播放 ${track?.title || "歌曲"}` : undefined}
      onClick={onPlay}
    >
      <span className="record-fallback" aria-hidden="true">
        <span>
          <Music2 />
        </span>
      </span>
      {track?.cover && (
        <img
          key={track.cover}
          src={track.cover}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={(e) => (e.currentTarget.style.display = "none")}
        />
      )}
    </Element>
  );
}
export function SongTitle({
  track,
  onPlay,
  className = "",
}: {
  track: Pick<Track, "title">;
  onPlay: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      className={`song-title-play ${className}`}
      aria-label={`播放歌名 ${track.title}`}
      title={`播放 ${track.title}`}
      onClick={onPlay}
    >
      {track.title}
    </button>
  );
}
export function Button({
  label,
  children,
  onClick,
  active,
  disabled = false,
  text,
}: {
  label: string;
  children: ReactNode;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  text?: string;
}) {
  return (
    <button
      className={`icon-button ${active ? "active" : ""}`}
      aria-label={label}
      aria-pressed={active}
      title={label}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
      {text && <span className="action-label">{text}</span>}
    </button>
  );
}
export function SongActions({
  track,
  play,
  queue,
  savePlaylist,
  children,
}: {
  track: Track;
  play: () => void;
  queue: () => void;
  savePlaylist?: () => void;
  children?: ReactNode;
}) {
  const id = useId();
  const anchor = `--song-${id.replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <div className="library-actions song-actions">
      <Button label={`播放 ${track.title}`} text="播放" onClick={play}>
        <Play />
      </Button>
      <Button label={`加入待播 ${track.title}`} text="加入待播" onClick={queue}>
        <Plus />
      </Button>
      {savePlaylist && (
        <Button
          label={`加入歌单 ${track.title}`}
          text="加入歌单"
          onClick={savePlaylist}
        >
          <ListMusic />
        </Button>
      )}
      {children && (
        <>
          <button
            type="button"
            className="icon-button song-more-trigger"
            aria-label={`更多歌曲操作 ${track.title}`}
            popoverTarget={id}
            style={{ anchorName: anchor } as React.CSSProperties}
          >
            <MoreHorizontal />
            <span className="action-label">更多</span>
          </button>
          <div
            id={id}
            popover="auto"
            className="song-action-menu"
            style={{ positionAnchor: anchor } as React.CSSProperties}
            onClick={(event) => {
              if (
                (event.target as HTMLElement).closest(
                  "button:not(:disabled), a",
                )
              )
                event.currentTarget.hidePopover();
            }}
          >
            {children}
          </div>
        </>
      )}
    </div>
  );
}
export function Lyrics({
  lines,
  text,
  time,
  onSeek,
  large = false,
  follow = true,
  size = false,
}: {
  lines: LyricLine[];
  text: string;
  time: number;
  onSeek: (s: number) => void;
  large?: boolean;
  follow?: boolean;
  size?: boolean;
}) {
  const current = activeLine(lines, time);
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (container.current) container.current.scrollTop = 0;
  }, [lines, text]);
  useEffect(() => {
    const center = () => {
      if (large && container.current)
        container.current.style.setProperty(
          "--lyrics-center",
          `${Math.max(44, Math.round(container.current.clientHeight / 2 - 44))}px`,
        );
      if (follow && current >= 0) {
        const element = container.current?.querySelector<HTMLElement>(
          '[data-active="true"]',
        );
        if (element && container.current)
          container.current.scrollTop =
            container.current.scrollTop +
            element.getBoundingClientRect().top -
            container.current.getBoundingClientRect().top -
            container.current.clientHeight / 2 +
            element.offsetHeight / 2;
      }
    };
    center();
    const observer = new ResizeObserver(center);
    if (container.current) observer.observe(container.current);
    return () => observer.disconnect();
  }, [current, follow, size, lines, large]);
  return (
    <div
      ref={container}
      className={`${large ? "full-lyrics" : "compact-lyrics"} ${size ? "large" : ""} ${lines.length ? "" : "untimed"}`}
    >
      {lines.length ? (
        lines.map((line, i) => (
          <button
            key={`${line.time}-${i}`}
            className={i === current ? "active" : ""}
            data-active={i === current}
            onClick={() => onSeek(line.time)}
          >
            <span>{line.text}</span>
            {large && <small className="lyric-time">{clock(line.time)}</small>}
          </button>
        ))
      ) : (
        <div className="lyric-empty">{text || "选择曲目后加载歌词"}</div>
      )}
    </div>
  );
}

export function Modal({
  title,
  close,
  className,
  heading,
  children,
}: {
  title: string;
  close?: () => void;
  className?: string;
  heading?: ReactNode;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
    return () => ref.current?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={className}
      onCancel={(e) => {
        e.preventDefault();
        close?.();
      }}
      aria-label={title}
    >
      <div className="dialog-heading">
        {heading || <h2>{title}</h2>}
        {close && (
          <Button label="关闭" onClick={close}>
            <X />
          </Button>
        )}
      </div>
      {children}
    </dialog>
  );
}
