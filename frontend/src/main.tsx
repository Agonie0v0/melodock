import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./style.css";
// Move existing preferences once so clearing a new preference cannot revive it.
try {
  if (localStorage.getItem("melokeep-naming-version") !== "1") {
    for (const prefix of ["melodock-", "musicdl-"]) {
      for (const key of Object.keys(localStorage)) {
        if (!key.startsWith(prefix)) continue;
        const next = "melokeep-" + key.slice(prefix.length);
        if (localStorage.getItem(next) === null)
          localStorage.setItem(next, localStorage.getItem(key)!);
        localStorage.removeItem(key);
      }
    }
    localStorage.setItem("melokeep-naming-version", "1");
  }
} catch {
  // Playback remains available when browser storage is blocked.
}
createRoot(document.getElementById("root")!).render(<App />);
