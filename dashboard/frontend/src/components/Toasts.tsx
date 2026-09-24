import { useCallback, useState } from "react";

export interface Toast {
  id: number;
  ok: boolean;
  title: string;
  text: string;
  log?: string;
}

export type Notify = (t: Omit<Toast, "id">) => void;

let nextId = 1;

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);
  const notify: Notify = useCallback(
    (t) => {
      const id = nextId++;
      setToasts((ts) => [...ts.slice(-2), { ...t, id }]);
      if (t.ok) setTimeout(() => dismiss(id), 8000); // errors stay until closed
    },
    [dismiss],
  );
  return { toasts, notify, dismiss };
}

export function Toasts({ toasts, dismiss }: { toasts: Toast[]; dismiss: (id: number) => void }) {
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.ok ? "" : "error"}`}>
          <span className={`icon ${t.ok ? "ok" : "fail"}`} aria-hidden="true">{t.ok ? "✓" : "✕"}</span>
          <div className="t-body">
            <b>{t.title}</b>
            {t.text}
            {t.log && (
              <details>
                <summary className="muted">Lambda log</summary>
                <pre>{t.log.trim()}</pre>
              </details>
            )}
          </div>
          <button className="t-close" onClick={() => dismiss(t.id)} aria-label="Close notification">×</button>
        </div>
      ))}
    </div>
  );
}
