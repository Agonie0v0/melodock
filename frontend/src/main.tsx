import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./style.css";
// Move existing preferences once so clearing a new preference cannot revive it.
try {
  for (const key of Object.keys(localStorage)) {
    if (!key.startsWith("musicdl-")) continue;
    const next = "melodock-" + key.slice("musicdl-".length);
    if (localStorage.getItem(next) === null)
      localStorage.setItem(next, localStorage.getItem(key)!);
    localStorage.removeItem(key);
  }
} catch {
  // Playback remains available when browser storage is blocked.
}
createRoot(document.getElementById("root")!).render(<App />);
