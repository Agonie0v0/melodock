import type { Track } from "./types";

export function trackSize(track: Track): number | null {
  if (
    typeof track.size_bytes === "number" &&
    Number.isFinite(track.size_bytes) &&
    track.size_bytes >= 0
  )
    return track.size_bytes;
  const match = track.size_label?.match(
    /^\s*([\d.]+)\s*(bytes?|[kmgt]i?b)\s*$/i,
  );
  if (!match) return null;
  const unit = match[2].toLowerCase();
  const power = { k: 1, m: 2, g: 3, t: 4 }[unit[0]] || 0;
  const size = Number(match[1]) * 1024 ** power;
  return Number.isFinite(size) ? size : null;
}

function qualityScore(track: Track): number | null {
  const known = trackQualities(track).filter(
    (q) => q.codec || q.lossless || q.bitrate,
  );
  if (!known.length) return null;
  return Math.max(
    ...known.map((q) =>
      q.lossless
        ? 1_000_000 + (q.bitrate || 0)
        : q.bitrate || (q.codec ? 0 : -1),
    ),
  );
}

function trackQualities(track: Track) {
  // Library streams are original files; search previews may be transcoded.
  if (track.source !== "navidrome" && track.source !== "local")
    return track.qualities;
  const codec = track.playback.codec?.trim().toLowerCase();
  if (!codec) return [];
  return [
    {
      codec,
      bitrate: track.playback.bitrate,
      lossless: [
        "flac",
        "alac",
        "ape",
        "wav",
        "aiff",
        "aif",
        "wv",
        "tta",
        "tak",
        "pcm",
        "dsf",
        "dff",
      ].includes(codec),
    },
  ];
}

function numeric(a: number | null, b: number | null, descending: boolean) {
  // Unknown values always follow known values, in either direction.
  if (a === null) return b === null ? 0 : 1;
  if (b === null) return -1;
  return descending ? b - a : a - b;
}

export function selectResults(
  tracks: Track[],
  source: string,
  quality: string,
  readyOnly: boolean,
  sort: string,
): Track[] {
  return tracks
    .filter((track) => {
      const qualities = trackQualities(track);
      return (
        (source === "all" || track.source === source) &&
        (!readyOnly || track.playback.state === "ready") &&
        (quality !== "lossless" || qualities.some((q) => q.lossless)) &&
        (quality !== "lossy" ||
          qualities.some((q) => !q.lossless && !!q.codec)) &&
        (quality !== "mp3" ||
          qualities.some((q) => q.codec.toLowerCase() === "mp3")) &&
        (quality !== "unknown" ||
          !qualities.length ||
          qualities.every((q) => !q.codec))
      );
    })
    .sort((a, b) => {
      if (sort === "name") return a.title.localeCompare(b.title, "zh");
      if (sort === "artist") return a.artist.localeCompare(b.artist, "zh");
      if (sort === "source") return a.source.localeCompare(b.source, "zh");
      if (sort.startsWith("duration"))
        return numeric(
          a.duration > 0 ? a.duration : null,
          b.duration > 0 ? b.duration : null,
          sort.endsWith("desc"),
        );
      if (sort.startsWith("size"))
        return numeric(trackSize(a), trackSize(b), sort.endsWith("desc"));
      if (sort.startsWith("quality"))
        return numeric(qualityScore(a), qualityScore(b), sort.endsWith("desc"));
      return 0;
    });
}
