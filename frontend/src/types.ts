export interface Quality {
  id: string;
  label: string;
  codec: string;
  bitrate: number | null;
  lossless: boolean;
  availability: string;
  evidence: string;
}
export interface Track {
  id: string;
  source: string;
  source_id: string;
  title: string;
  artist: string;
  album: string;
  duration: number;
  cover: string | null;
  size_bytes?: number | null;
  size_label?: string | null;
  episodes?: number;
  root_source?: string;
  qualities: Quality[];
  playback: {
    state: string;
    url: string | null;
    codec: string | null;
    bitrate: number | null;
    detail: string | null;
    preview_only: boolean;
  };
}
export interface Config {
  available_sources?: {
    id: string;
    label: string;
    category?: string;
    engine_name?: string;
    proxy_recommended?: boolean;
    init_error?: string | null;
  }[];
  engine?: string;
  sources: string[];
  results_per_source: number;
  search_timeout_seconds: number;
  playback_timeout_seconds: number;
  download_concurrency: number;
  download_layout: string;
  lyrics_mode: string;
  embed_metadata: boolean;
  source_settings: Record<string, { cookie: string; proxy: string }>;
}
export interface DownloadJob {
  id: string;
  track: Track;
  quality_id: string;
  quality_label: string;
  status: string;
  bytes: number;
  total_bytes: number | null;
  detail: string;
  file: string | null;
  processing?: { id: string; status: string; detail: string };
}
export interface LibraryFile {
  path: string;
  name: string;
  size: number;
  root?: string;
  folder?: string;
  track?: Track;
  editable?: boolean;
  metadata?: Record<string, string>;
  locked_fields?: string[];
}

export interface NavidromeConfig {
  enabled: boolean;
  url: string;
  username: string;
  auto_scan: boolean;
  has_password: boolean;
  has_api_key: boolean;
}
export interface LibraryConfig {
  auto_scrape: boolean;
  auto_organize: boolean;
  library_dir: string;
  file_root: string;
  folder_template: string;
  filename_template: string;
  sources: string[];
  overwrite: boolean;
  lyrics_mode: string;
  cover_mode: string;
  fields: string[];
  backup_days: number;
  navidrome: NavidromeConfig;
  metadata_sources?: MetadataSource[];
  chinese?: string;
  repair_encoding?: boolean;
  watch_enabled?: boolean;
  watch_dirs?: string[];
  watch_interval?: number;
  watch_stable_seconds?: number;
  watch_action?: string;
  watch_apply?: boolean;
  watch_failure_dir?: string;
  has_acoustid_key?: boolean;
  tools?: Record<string, boolean>;
}
export interface MetadataSource {
  id: string;
  label: string;
  description: string;
  fields: string[];
  note: string;
  url: string;
}
export interface MetadataCandidate {
  id: string;
  source: string;
  title: string;
  artist: string;
  album: string;
  score: number;
  reasons: string[];
  conflicts: string[];
  field_sources?: Record<string, string>;
  [key: string]: unknown;
}
export interface LibraryJobItem {
  id: string;
  path: string;
  name: string;
  original_path: string;
  target: string;
  status: string;
  before: Record<string, string>;
  after: Record<string, string>;
  candidates: MetadataCandidate[];
  chosen: string | null;
  locks: string[];
  warnings: string[];
  error?: string;
  operation_id?: string;
  quality?: Record<string, number | null>;
  outputs?: { path: string; start?: number; end?: number }[];
  artwork?: { artist: string; source: string; url: string };
}
export interface LibraryJob {
  id: string;
  action: string;
  status: string;
  created_at: number;
  updated_at: number;
  total: number;
  processed: number;
  detail: string;
  items?: LibraryJobItem[];
  warnings: string[];
  settings?: Pick<LibraryConfig, "sources" | "overwrite" | "fields">;
  duplicates?: { id: string; name: string; path: string }[][];
}
export interface SourceStatus {
  state: string;
  count?: number;
  detail?: string;
}
export interface PlaylistIssue {
  source_id: string;
  title: string;
  artist: string;
  reason: string;
}
export interface SavedPlaylist {
  id: string;
  name: string;
  source: string;
  source_url: string;
  created_at: number;
  tracks: Track[];
  issues: PlaylistIssue[];
  detail: string;
  task_id: string;
}
export interface PlaylistSummary extends Omit<
  SavedPlaylist,
  "tracks" | "issues"
> {
  track_count: number;
  issue_count: number;
  cover: string | null;
}
