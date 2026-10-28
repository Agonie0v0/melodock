import assert from "node:assert/strict";
import { test } from "node:test";
import { playbackErrorMessage } from "../src/playback-errors.ts";

test("playback errors suppress interruptions and give actionable Chinese feedback", () => {
  assert.equal(
    playbackErrorMessage(new DOMException("interrupted", "AbortError")),
    null,
  );
  assert.match(
    playbackErrorMessage(new DOMException("denied", "NotAllowedError")),
    /点击播放/,
  );
  assert.match(
    playbackErrorMessage(new DOMException("unsupported", "NotSupportedError")),
    /其他音源/,
  );
  assert.match(
    playbackErrorMessage(new TypeError("Failed to fetch")),
    /检查网络/,
  );
  assert.equal(
    playbackErrorMessage(new Error("歌曲暂时不可用")),
    "歌曲暂时不可用",
  );
  assert.match(
    playbackErrorMessage(new Error("Media decoding failed")),
    /播放失败/,
  );
});
