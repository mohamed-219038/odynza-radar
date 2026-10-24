/* Dark (Radar Night) or light (Front Page, the "Brief C" newspaper look). Remembered in this browser. */
import { useState } from "react";

export type Theme = "dark" | "light";
const KEY = "odz-theme";

export function savedTheme(): Theme {
  try {
    return window.localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(theme: Theme) {
  document.body.classList.toggle("odz-light", theme === "light");
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    /* private window */
  }
}

export function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(savedTheme);
  const pick = (t: Theme) => {
    setTheme(t);
    applyTheme(t);
  };
  return (
    <div className="odz-theme" role="group" aria-label="Colour theme">
      <button aria-pressed={theme === "dark"} onClick={() => pick("dark")}>
        ☾ Dark
      </button>
      <button aria-pressed={theme === "light"} onClick={() => pick("light")}>
        ☀ Light
      </button>
    </div>
  );
}
