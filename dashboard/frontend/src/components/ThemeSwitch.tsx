import { useEffect, useState } from "react";

export type Theme = "light" | "dark" | "auto";
const KEY = "parking-bot-theme";

function readTheme(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    if (t === "light" || t === "dark" || t === "auto") return t;
  } catch {
    /* storage unavailable: fall back to the default */
  }
  return "light";
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  return [theme, setTheme] as const;
}

const OPTIONS: { value: Theme; label: string }[] = [
  { value: "light", label: "☀️ Light blue" },
  { value: "dark", label: "🌙 Dark" },
  { value: "auto", label: "🖥️ Auto" },
];

export function ThemeSwitch({ theme, onChange }: { theme: Theme; onChange: (t: Theme) => void }) {
  return (
    <div className="segmented" role="group" aria-label="Color theme">
      {OPTIONS.map((o) => (
        <button key={o.value} aria-pressed={theme === o.value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
