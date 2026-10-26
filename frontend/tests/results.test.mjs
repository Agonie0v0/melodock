import test from "node:test";
import assert from "node:assert/strict";
import { selectResults } from "../src/results.ts";

const make = (id, codec, lossless, bitrate, size, ready = true) => ({
  id,
  title: id,
  artist: id,
  source: "netease",
  duration: 100,
  size_bytes: size,
  qualities: codec ? [{ codec, lossless, bitrate }] : [],
  playback: { state: ready ? "ready" : "download_only" },
});
const tracks = [
  make("mp3-128", "mp3", false, 128, 4),
  make("unknown", "", false, null, null),
  make("flac", "flac", true, null, 40, false),
  make("mp3-320", "mp3", false, 320, 10),
];
const ids = (quality, ready, sort) =>
  selectResults(tracks, "all", quality, ready, sort).map((t) => t.id);

test("quality and playable filters combine independently", () => {
  assert.deepEqual(ids("lossless", false, "relevance"), ["flac"]);
  assert.deepEqual(ids("lossless", true, "relevance"), []);
  assert.deepEqual(ids("mp3", true, "relevance"), ["mp3-128", "mp3-320"]);
  assert.deepEqual(ids("unknown", false, "relevance"), ["unknown"]);
  assert.equal(tracks.length, 4);
});

test("size and quality sort in both directions, unknowns last", () => {
  assert.deepEqual(ids("all", false, "size-desc"), [
    "flac",
    "mp3-320",
    "mp3-128",
    "unknown",
  ]);
  assert.deepEqual(ids("all", false, "size-asc"), [
    "mp3-128",
    "mp3-320",
    "flac",
    "unknown",
  ]);
  assert.deepEqual(ids("all", false, "quality-desc"), [
    "flac",
    "mp3-320",
    "mp3-128",
    "unknown",
  ]);
  assert.deepEqual(ids("all", false, "quality-asc"), [
    "mp3-128",
    "mp3-320",
    "flac",
    "unknown",
  ]);
  assert.deepEqual(
    tracks.map((t) => t.id),
    ["mp3-128", "unknown", "flac", "mp3-320"],
  );
});

test("library formats drive quality filters and sorting without download versions", () => {
  const library = (id, codec, bitrate = null, source = "navidrome") => ({
    ...make(id, "", false, null, null),
    source,
    playback: { state: "ready", codec, bitrate },
  });
  const songs = [
    library("mp3", " MP3 ", 320),
    library("unknown", null, 1000),
    library("flac", "FLAC", 800),
    library("aac", "aac", 256),
    library("local-alac", "alac", null, "local"),
    library("missing-format", "  "),
  ];
  const selected = (quality, sort = "relevance") =>
    selectResults(songs, "all", quality, false, sort).map((t) => t.id);
  assert.deepEqual(selected("lossless"), ["flac", "local-alac"]);
  assert.deepEqual(selected("mp3"), ["mp3"]);
  assert.deepEqual(selected("lossy"), ["mp3", "aac"]);
  assert.deepEqual(selected("unknown"), ["unknown", "missing-format"]);
  assert.deepEqual(selected("all", "quality-desc"), [
    "flac",
    "local-alac",
    "mp3",
    "aac",
    "unknown",
    "missing-format",
  ]);
  assert.deepEqual(selected("all", "quality-asc"), [
    "aac",
    "mp3",
    "local-alac",
    "flac",
    "unknown",
    "missing-format",
  ]);
  assert.deepEqual(
    selectResults(songs, "navidrome", "lossless", true, "relevance").map(
      (t) => t.id,
    ),
    ["flac"],
  );
  assert.ok(songs.every((t) => t.qualities.length === 0));
});

test("search preview codecs do not establish download quality", () => {
  const candidate = {
    ...make("candidate", "", false, null, null),
    playback: {
      state: "ready",
      codec: "mp3",
      bitrate: 128,
      preview_only: true,
    },
  };
  assert.deepEqual(
    selectResults([candidate], "all", "mp3", false, "relevance"),
    [],
  );
  assert.deepEqual(
    selectResults([candidate], "all", "unknown", false, "relevance"),
    [candidate],
  );
});
