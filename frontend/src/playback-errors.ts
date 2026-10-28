export function playbackErrorMessage(error: unknown): string | null {
  const name = error instanceof Error ? error.name : "";
  if (name === "AbortError") return null;
  if (name === "NotAllowedError")
    return "浏览器阻止了自动播放，请点击播放按钮继续。";
  if (name === "NotSupportedError")
    return "暂时无法播放此音频，请重试或选择其他音源。";
  if (error instanceof TypeError) return "音频连接失败，请检查网络后重试。";
  const message = error instanceof Error ? error.message : String(error);
  return /[\u3400-\u9fff]/.test(message)
    ? message
    : "播放失败，请重试；仍无法播放时可更换音源或查看运行日志。";
}
